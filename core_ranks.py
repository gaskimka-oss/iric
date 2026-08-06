"""Система рангов модераторов (0–5), как в Ирисе."""
from __future__ import annotations

import time
from typing import Optional

from aiogram import Bot
from aiogram.types import Message

import db
from config import ADMINS, OWNER_ID
from core_registry import MAX_RANK, RANK_NAMES, RANK_TITLES, stars


async def get_rank(chat_id: int, user_id: int) -> int:
    """0 — участник … 8 — лидер клана. Владелец бота всегда 8.

    Ранг единый для всех тем чата. Если включён глобальный режим
    (настройка global_ranks), берётся максимальный ранг по всем чатам —
    тогда звание одинаково во всех беседах сетки.
    """
    if user_id == OWNER_ID or user_id in ADMINS:
        return MAX_RANK
    row = await db.fetchone(
        "SELECT rank FROM ranks WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    r = int(row["rank"]) if row else 0
    # состав, загруженный через «импорт состава», тоже даёт ранг
    srow = await db.fetchone(
        "SELECT rank FROM staff WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    if srow:
        r = max(r, int(srow["rank"]))

    # глобальные ранги: одно звание во всех чатах
    if await db.get_setting(chat_id, "global_ranks", "1") == "1":
        grow = await db.fetchone(
            "SELECT MAX(rank) m FROM ranks WHERE user_id=?", (user_id,))
        if grow and grow["m"]:
            r = max(r, int(grow["m"]))
        grow2 = await db.fetchone(
            "SELECT MAX(rank) m FROM staff WHERE user_id=?", (user_id,))
        if grow2 and grow2["m"]:
            r = max(r, int(grow2["m"]))
    return r


async def set_rank(chat_id: int, user_id: int, rank: int, by: int = 0) -> None:
    """Устанавливает ранг с учётом режима «глобальные ранги».

    Раньше при снятии должности запись удалялась только в текущем чате, но
    get_rank сразу возвращал старый ранг из второй группы. Поэтому визуально
    админа было невозможно снять. В глобальном режиме меняем все его записи.
    """
    global_mode = await db.get_setting(chat_id, "global_ranks", "1") == "1"
    now = int(time.time())

    if rank <= 0:
        if global_mode:
            await db.execute("DELETE FROM ranks WHERE user_id=?", (user_id,))
            await db.execute("DELETE FROM staff WHERE user_id=?", (user_id,))
        else:
            await db.execute("DELETE FROM ranks WHERE chat_id=? AND user_id=?",
                             (chat_id, user_id))
            await db.execute("DELETE FROM staff WHERE chat_id=? AND user_id=?",
                             (chat_id, user_id))
    else:
        if global_mode:
            # Обновляем существующие назначения и импортированный состав, чтобы
            # старший ранг из другой связанной группы не перекрывал понижение.
            await db.execute(
                "UPDATE ranks SET rank=?, granted_by=?, ts=? WHERE user_id=?",
                (rank, by, now, user_id))
            await db.execute("UPDATE staff SET rank=?, ts=? WHERE user_id=?",
                             (rank, now, user_id))
        await db.execute(
            "INSERT INTO ranks (chat_id, user_id, rank, granted_by, ts) VALUES (?,?,?,?,?) "
            "ON CONFLICT(chat_id, user_id) DO UPDATE SET rank=excluded.rank, "
            "granted_by=excluded.granted_by, ts=excluded.ts",
            (chat_id, user_id, rank, by, now))
    await db.execute(
        "INSERT INTO rank_log (chat_id, user_id, rank, by_id, ts) VALUES (?,?,?,?,?)",
        (chat_id, user_id, rank, by, now))


async def effective_rank(message: Message, bot: Bot) -> int:
    """Ранг с учётом ТГ-админки и анонимных админов."""
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        return MAX_RANK  # анонимный админ группы = высший ранг
    if not message.from_user:
        return 0
    uid = message.from_user.id
    if uid == OWNER_ID or uid in ADMINS:
        return MAX_RANK
    if message.chat.type == "private":
        return MAX_RANK  # в личке пользователь «сам себе создатель»
    r = await get_rank(message.chat.id, uid)
    if r:
        return r
    # ТГ-создатель чата получает высший ранг, ТГ-админ — 3
    try:
        m = await bot.get_chat_member(message.chat.id, uid)
        if m.status == "creator":
            return MAX_RANK
        if m.status == "administrator":
            return 3
    except Exception:
        pass
    return 0


def rank_name(rank: int) -> str:
    return RANK_NAMES.get(rank, "Участник")


def rank_label(rank: int) -> str:
    """«⭐⭐⭐ Младший админ» — для ответов бота."""
    return f"{stars(rank)} {RANK_NAMES.get(rank, 'Участник')}".strip()


async def require(message: Message, bot: Bot, need: int, key: str = "") -> bool:
    """Проверка ранга с автоответом. Учитывает переопределение ранга через ДК."""
    # ДК уже пропустил команду в middleware — не перепроверяем строже
    if getattr(message, "_dk_ok", False):
        return True
    r = await effective_rank(message, bot)
    if r >= need:
        return True

    # Фраза без префикса случайно совпала с командой («всем привет») —
    # молча пропускаем, ругаться на обычное сообщение нельзя.
    text = (message.text or message.caption or "").strip()
    if text and text[0] not in "!./":
        low = text.lower()
        if not (low.startswith("ирис") or low.startswith("ириска")):
            return False

    await message.reply(
        f"⛔️ Недостаточно прав.\n"
        f"Нужен ранг: <b>{rank_label(need)}</b>\n"
        f"Ваш ранг: <b>{rank_label(r) if r else 'Участник'}</b>")
    return False
