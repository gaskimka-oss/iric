"""Отложенные муты и баны для пока неизвестных Telegram ID.

Bot API не позволяет найти обычного пользователя только по @username. Если ID
ещё нет в базе, команда сохраняется и автоматически применяется при следующем
сообщении, входе или membership-событии этого пользователя.
"""
from __future__ import annotations

import html
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.types import ChatPermissions, User

import db
from core_punish import log_punish
from core_resolve import human_period
from utils import mention_id

MUTE_OFF = ChatPermissions(
    can_send_messages=False, can_send_audios=False, can_send_documents=False,
    can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
    can_send_voice_notes=False, can_send_polls=False,
    can_send_other_messages=False, can_add_web_page_previews=False)


async def schedule(chat_id: int, username: str, kind: str, reason: str,
                   seconds: int, by_id: int) -> None:
    await db.execute(
        "INSERT INTO pending_punishments(chat_id,username,kind,reason,seconds,by_id,ts) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(chat_id,username,kind) DO UPDATE SET "
        "reason=excluded.reason, seconds=excluded.seconds, by_id=excluded.by_id, ts=excluded.ts",
        (chat_id, username.lstrip("@"), kind, reason, seconds, by_id, int(time.time())))


async def apply_for_user(bot: Bot, chat_id: int, user: User) -> int:
    """Применяет ожидающие наказания, когда username наконец связан с ID."""
    if not user.username or user.is_bot:
        return 0
    rows = await db.fetchall(
        "SELECT * FROM pending_punishments WHERE chat_id=? "
        "AND lower(username)=lower(?) ORDER BY id", (chat_id, user.username))
    done = 0
    for row in rows:
        kind = row["kind"]
        seconds = int(row["seconds"] or 0)
        reason = row["reason"] or "Без причины"
        try:
            if kind == "mute":
                until = datetime.now(timezone.utc) + timedelta(
                    seconds=seconds or 366 * 86400)
                await bot.restrict_chat_member(chat_id, user.id, MUTE_OFF,
                                               until_date=until)
                await db.execute(
                    "INSERT INTO mutes(chat_id,user_id,reason,by_id,until,ts) "
                    "VALUES (?,?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET "
                    "reason=excluded.reason, by_id=excluded.by_id, "
                    "until=excluded.until, ts=excluded.ts",
                    (chat_id, user.id, reason, row["by_id"],
                     int(time.time()) + seconds if seconds else 0, int(time.time())))
            elif kind == "ban":
                until = (datetime.now(timezone.utc) + timedelta(seconds=seconds)) \
                    if seconds else None
                await bot.ban_chat_member(chat_id, user.id, until_date=until)
                await db.execute(
                    "INSERT INTO bans(chat_id,user_id,reason,by_id,until,ts) "
                    "VALUES (?,?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET "
                    "reason=excluded.reason, by_id=excluded.by_id, "
                    "until=excluded.until, ts=excluded.ts",
                    (chat_id, user.id, reason, row["by_id"],
                     int(time.time()) + seconds if seconds else 0, int(time.time())))
            else:
                await db.execute("DELETE FROM pending_punishments WHERE id=?", (row["id"],))
                continue

            pid = await log_punish(chat_id, user.id, kind, reason, seconds, row["by_id"])
            await db.execute("DELETE FROM pending_punishments WHERE id=?", (row["id"],))
            label = "🔇 Мут" if kind == "mute" else "🔨 Бан"
            await bot.send_message(
                chat_id,
                f"{label} <b>применён автоматически</b>\n"
                f"👤 {mention_id(user.id, user.first_name)}\n"
                f"⏱ Срок: <b>{human_period(seconds)}</b>\n"
                f"📝 Причина: {html.escape(reason)}\n<code>#{pid}</code>")
            done += 1
        except Exception:
            # Оставляем запись: бот повторит попытку при следующем событии.
            continue
    return done
