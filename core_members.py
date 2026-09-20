"""Учёт и безопасная проверка участников Telegram-чата.

Telegram Bot API не отдаёт боту полный список обычных участников. Поэтому бот
запоминает людей по сообщениям/событиям входа, а перед массовым упоминанием
обязательно перепроверяет каждого через getChatMember. Ушедшие, кикнутые и
забаненные пользователи в созыв не попадают.
"""
from __future__ import annotations

import asyncio
import html
import re
import time
from collections.abc import Iterable, Mapping
from typing import Any

from aiogram import Bot

import db

PRESENT = {"member", "administrator", "creator"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{4,32}$")
CHECK_CONCURRENCY = 8


def member_status(member: Any) -> str:
    """Возвращает строковый статус независимо от enum/версии aiogram."""
    raw = getattr(member, "status", "")
    value = getattr(raw, "value", raw)
    return str(value).lower().rsplit(".", 1)[-1]


def member_is_present(member: Any) -> bool:
    status = member_status(member)
    if status in PRESENT:
        return True
    if status == "restricted":
        return bool(getattr(member, "is_member", False))
    return False


async def remember_member(chat_id: int, user_id: int, status: str = "member",
                          is_member: bool = True) -> None:
    """Сохраняет последнее достоверное состояние участника."""
    await db.execute(
        "INSERT INTO chat_members(chat_id,user_id,status,is_member,updated_at) "
        "VALUES (?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET "
        "status=excluded.status,is_member=excluded.is_member,"
        "updated_at=excluded.updated_at",
        (chat_id, user_id, status, 1 if is_member else 0, int(time.time())))


async def remember_chat_member(chat_id: int, member: Any) -> bool:
    present = member_is_present(member)
    user = getattr(member, "user", None)
    if user and not getattr(user, "is_bot", False):
        await db.touch_user(user.id, user.username, user.first_name)
        await remember_member(chat_id, user.id, member_status(member), present)
    return present


def summon_mention(user_id: int, name: str | None,
                    username: str | None = None) -> str:
    """Видимое @username-упоминание; при его отсутствии — кликабельный ID.

    Оба варианта являются Telegram-упоминаниями и отправляют уведомление.
    """
    uname = (username or "").strip().lstrip("@")
    if USERNAME_RE.fullmatch(uname):
        return "@" + html.escape(uname)
    label = html.escape(name or str(user_id))
    return f'<a href="tg://user?id={user_id}">{label}</a>'


def _get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        value = row[key]
        return default if value is None else value
    except (KeyError, IndexError, TypeError):
        return default


async def verified_members(bot: Bot, chat_id: int, rows: Iterable[Any],
                           exclude: Iterable[int] = ()) -> list[dict[str, Any]]:
    """Оставляет только реально состоящих в чате пользователей.

    Проверка строгая: если Telegram не подтвердил членство, пользователь не
    упоминается. Это лучше, чем снова позвать человека, который вышел/забанен.
    Результат сохраняется в ``chat_members`` для следующих команд.
    """
    excluded = {int(x) for x in exclude}
    unique: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            uid = int(_get(row, "user_id", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not uid or uid in excluded or uid in unique:
            continue
        unique[uid] = {
            "user_id": uid,
            "first_name": _get(row, "first_name"),
            "username": _get(row, "username"),
            "last_seen": int(_get(row, "last_seen", 0) or 0),
        }

    if not unique:
        return []

    now = int(time.time())
    banned: set[int] = set()
    ids = list(unique)
    # Не превышаем лимит параметров SQLite даже в очень большом чате.
    for start in range(0, len(ids), 800):
        part = ids[start:start + 800]
        placeholders = ",".join("?" for _ in part)
        records = await db.fetchall(
            f"SELECT user_id FROM bans WHERE chat_id=? AND user_id IN ({placeholders}) "
            "AND (until IS NULL OR until=0 OR until>?)",
            (chat_id, *part, now))
        banned.update(int(r["user_id"]) for r in records)

    semaphore = asyncio.Semaphore(CHECK_CONCURRENCY)

    async def check(person: dict[str, Any]) -> dict[str, Any] | None:
        uid = int(person["user_id"])
        if uid in banned:
            await remember_member(chat_id, uid, "kicked", False)
            return None
        try:
            async with semaphore:
                member = await bot.get_chat_member(chat_id, uid)
        except Exception:
            # Не рискуем тегать неподтверждённого пользователя.
            return None

        present = member_is_present(member)
        user = getattr(member, "user", None)
        if user:
            person["first_name"] = user.first_name or person["first_name"]
            # None означает, что @username удалён: нельзя использовать старый,
            # он уже мог перейти к другому аккаунту.
            person["username"] = user.username
            if not getattr(user, "is_bot", False):
                await db.touch_user(user.id, user.username, user.first_name)
            else:
                present = False
        await remember_member(chat_id, uid, member_status(member), present)
        return person if present else None

    checked = await asyncio.gather(*(check(p) for p in unique.values()))
    return [p for p in checked if p is not None]


async def known_chat_rows(chat_id: int, limit: int = 0) -> list[Any]:
    """Все известные боту люди чата: писавшие и замеченные при входе."""
    sql = (
        "SELECT k.user_id,u.first_name,u.username,MAX(k.last_seen) last_seen FROM ("
        " SELECT user_id,last_seen FROM chat_stats WHERE chat_id=?"
        " UNION ALL"
        " SELECT user_id,updated_at last_seen FROM chat_members"
        " WHERE chat_id=? AND is_member=1"
        ") k LEFT JOIN users u ON u.user_id=k.user_id"
        " GROUP BY k.user_id,u.first_name,u.username"
        " ORDER BY last_seen DESC"
    )
    params: tuple[Any, ...] = (chat_id, chat_id)
    if limit > 0:
        sql += " LIMIT ?"
        params += (limit,)
    return await db.fetchall(sql, params)
