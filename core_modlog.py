"""Журнал модерации: контекст диалога, запись наказаний, автоудаление."""
from __future__ import annotations

import asyncio
import html
import time

from aiogram import Bot
from aiogram.types import Message

import db

BUFFER_KEEP = 400          # сколько сообщений держать на чат
CONTEXT_BEFORE = 6         # реплик до нарушения
AUTODEL_MUTE = 180         # 3 минуты


async def remember(message: Message) -> None:
    """Складывает сообщение в буфер — для восстановления контекста."""
    if message.chat.type == "private" or not message.from_user:
        return
    text = (message.text or message.caption or "")[:300]
    if not text:
        return
    await db.execute(
        "INSERT OR REPLACE INTO msg_buffer (chat_id,msg_id,user_id,user_name,text,ts) "
        "VALUES (?,?,?,?,?,?)",
        (message.chat.id, message.message_id, message.from_user.id,
         message.from_user.first_name or "", text, int(time.time())))
    # чистим старое, чтобы база не пухла
    if message.message_id % 50 == 0:
        await db.execute(
            "DELETE FROM msg_buffer WHERE chat_id=? AND msg_id NOT IN "
            "(SELECT msg_id FROM msg_buffer WHERE chat_id=? "
            " ORDER BY ts DESC LIMIT ?)",
            (message.chat.id, message.chat.id, BUFFER_KEEP))


async def build_context(chat_id: int, target_id: int,
                        trigger_text: str = "") -> str:
    """Собирает переписку вокруг нарушения."""
    rows = await db.fetchall(
        "SELECT user_name, text, ts, user_id FROM msg_buffer WHERE chat_id=? "
        "ORDER BY ts DESC LIMIT ?", (chat_id, CONTEXT_BEFORE))
    rows = list(reversed(rows))
    lines = []
    for r in rows:
        mark = "👉 " if r["user_id"] == target_id else "   "
        t = time.strftime("%H:%M", time.localtime(r["ts"]))
        lines.append(f"{mark}[{t}] {r['user_name']}: {r['text'][:120]}")
    if trigger_text and not any(trigger_text[:40] in l for l in lines):
        lines.append(f"👉 [нарушение] {trigger_text[:150]}")
    return "\n".join(lines[-CONTEXT_BEFORE - 1:]) if lines else "(нет данных)"


async def write(chat_id: int, punish_id: int, target_id: int, target_name: str,
                by_id: int, by_name: str, kind: str, reason: str,
                seconds: int, source: str, context: str = "") -> int:
    await db.execute(
        "INSERT INTO mod_log (chat_id,punish_id,target_id,target_name,by_id,by_name,"
        "kind,reason,seconds,context,source,ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (chat_id, punish_id, target_id, target_name or str(target_id), by_id,
         by_name or ("автомодерация" if not by_id else str(by_id)),
         kind, reason, seconds, context, source, int(time.time())))
    row = await db.fetchone("SELECT last_insert_rowid() id")
    return row["id"] if row else 0


async def autodelete(bot: Bot, chat_id: int, message_id: int,
                     delay: int = AUTODEL_MUTE) -> None:
    """Удаляет уведомление о наказании через N секунд."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


def schedule_autodelete(bot: Bot, msg: Message | None,
                        delay: int = AUTODEL_MUTE) -> None:
    if msg is None:
        return
    try:
        asyncio.create_task(autodelete(bot, msg.chat.id, msg.message_id, delay))
    except Exception:
        pass
