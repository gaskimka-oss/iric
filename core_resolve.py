"""Разбор {ссылка}: реплай, @username, t.me/..., числовой id, text_mention."""
from __future__ import annotations

import re
from typing import Optional

from aiogram import Bot
from aiogram.types import Message

import db

LINK_RE = re.compile(r"(?:https?://)?t\.me/([A-Za-z0-9_]{4,})", re.I)
USER_RE = re.compile(r"@([A-Za-z0-9_]{4,})")
ID_RE = re.compile(r"\b(\d{5,15})\b")


async def resolve_target(message: Message, args: str, bot: Bot) -> tuple[Optional[int], Optional[str], str]:
    """-> (user_id, имя, остаток_текста). Поддерживает реплай/@ник/ссылку/id."""
    rest = args or ""

    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        return u.id, u.first_name, rest.strip()

    for ent in (message.entities or []):
        if ent.type == "text_mention" and ent.user:
            return ent.user.id, ent.user.first_name, rest.strip()

    m = LINK_RE.search(rest) or USER_RE.search(rest)
    if m:
        uname = m.group(1)
        rest = (rest[:m.start()] + rest[m.end():]).strip()
        row = await db.fetchone(
            "SELECT user_id, first_name FROM users WHERE lower(username)=lower(?)", (uname,))
        if row:
            return row["user_id"], row["first_name"], rest
        try:
            chat = await bot.get_chat(f"@{uname}")
            await db.touch_user(chat.id, chat.username, chat.first_name or chat.title)
            return chat.id, chat.first_name or chat.title, rest
        except Exception:
            return None, uname, rest

    m = ID_RE.search(rest)
    if m:
        uid = int(m.group(1))
        rest = (rest[:m.start()] + rest[m.end():]).strip()
        row = await db.fetchone("SELECT first_name FROM users WHERE user_id=?", (uid,))
        return uid, (row["first_name"] if row else str(uid)), rest

    return None, None, rest.strip()


PERIOD_RE = re.compile(
    r"(\d+)\s*(минут\w*|мин|м|час\w*|ч|сут\w*|день|дня|дней|д|недел\w*|нед|н|месяц\w*|мес|год\w*|г)\b",
    re.I)

UNITS = {
    "м": 60, "мин": 60, "минут": 60,
    "ч": 3600, "час": 3600,
    "д": 86400, "сут": 86400, "день": 86400, "дня": 86400, "дней": 86400,
    "н": 604800, "нед": 604800, "недел": 604800,
    "мес": 2592000, "месяц": 2592000,
    "г": 31536000, "год": 31536000,
}


def parse_period(text: str) -> tuple[int, str]:
    """'2 часа спам' -> (7200, 'спам'). Без периода -> (0, текст)."""
    if not text:
        return 0, ""
    m = PERIOD_RE.search(text)
    if not m:
        return 0, text.strip()
    num = int(m.group(1))
    unit = m.group(2).lower()
    secs = 0
    for k in sorted(UNITS, key=len, reverse=True):
        if unit.startswith(k):
            secs = num * UNITS[k]
            break
    rest = (text[:m.start()] + text[m.end():]).strip()
    return secs, rest


def human_period(seconds: int) -> str:
    if seconds <= 0:
        return "навсегда"
    for label, size in (("г", 31536000), ("мес", 2592000), ("нед", 604800),
                        ("д", 86400), ("ч", 3600), ("мин", 60)):
        if seconds >= size:
            return f"{seconds // size} {label}"
    return f"{seconds} сек"
