"""Журнал модерации: контекст диалога, запись наказаний, автоудаление."""
from __future__ import annotations

import asyncio
import logging
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
                seconds: int, source: str, context: str = "",
                bot: Bot | None = None) -> int:
    await db.execute(
        "INSERT INTO mod_log (chat_id,punish_id,target_id,target_name,by_id,by_name,"
        "kind,reason,seconds,context,source,ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (chat_id, punish_id, target_id, target_name or str(target_id), by_id,
         by_name or ("автомодерация" if not by_id else str(by_id)),
         kind, reason, seconds, context, source, int(time.time())))
    row = await db.fetchone("SELECT last_insert_rowid() id")
    log_id = row["id"] if row else 0

    # ИИ проверяет справедливость наказания в фоне
    try:
        import core_ai as ai
        if ai.available() and log_id:
            asyncio.create_task(_ai_review(
                log_id, chat_id, kind, reason, seconds,
                target_name or str(target_id),
                by_name or "автомодерация", context, bot))
    except Exception:
        pass
    return log_id


async def _ai_review(log_id: int, chat_id: int, kind: str, reason: str,
                     seconds: int, target: str, moderator: str,
                     context: str, bot: Bot | None) -> None:
    """Фоновая проверка наказания. Спорные — показываем владельцу."""
    import core_ai as ai
    try:
        r = await ai.review_punishment(kind, reason, seconds, target,
                                       moderator, context)
        if not r:
            return
        await db.execute(
            "UPDATE mod_log SET ai_verdict=?, ai_score=?, ai_reason=?, "
            "ai_advice=? WHERE id=?",
            (r["verdict"], r["score"], r["reason"], r.get("advice", ""),
             log_id))

        # молча пропускаем справедливые и неуверенные оценки
        if r["verdict"] == "ok" or r["score"] < 6 or bot is None:
            return
        if await db.get_setting(chat_id, "ai_alerts", "1") != "1":
            return

        from core_resolve import human_period
        kinds = {"mute": "🔇 Мут", "ban": "🔨 Бан",
                 "warn": "⚠️ Варн", "kick": "👢 Кик"}
        term = human_period(seconds) if seconds else "бессрочно"
        text = ai.render_review(r, kinds.get(kind, kind), target,
                                moderator, term)
        text += f"\n\n<code>#{log_id}</code> · разбор: <code>админ</code>"

        import config
        try:
            await bot.send_message(config.OWNER_ID, text,
                                   disable_web_page_preview=True)
        except Exception:
            pass
    except Exception as e:
        logging.getLogger("irisbot.ai").warning("разбор наказания: %s", e)


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
