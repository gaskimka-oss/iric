"""Вспомогательные функции: форматирование, парсинг сумм, уровни, доступ."""
from __future__ import annotations

import html
import re
from typing import Optional

from aiogram.types import Message, User

from config import ADMINS, CURRENCY, LEVELS, OWNER_ID


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


def money(n: int) -> str:
    return f"{n:,}".replace(",", " ") + f" {CURRENCY}"


def mention(user: User) -> str:
    name = html.escape(user.first_name or "user")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def mention_id(user_id: int, name: str | None = None) -> str:
    return f'<a href="tg://user?id={user_id}">{html.escape(name or str(user_id))}</a>'


def level_of(xp: int) -> tuple[int, str, int, int]:
    """-> (номер уровня, название, xp текущего порога, xp следующего порога)"""
    idx = 0
    for i, (need, _) in enumerate(LEVELS):
        if xp >= need:
            idx = i
    cur_need, title = LEVELS[idx]
    nxt = LEVELS[idx + 1][0] if idx + 1 < len(LEVELS) else cur_need
    return idx + 1, title, cur_need, nxt


def parse_amount(text: str, balance: int, minimum: int = 1) -> Optional[int]:
    """Понимает: 100, 1k, 2.5кк, 10%, все/всё/all, половина/half."""
    if not text:
        return None
    t = text.strip().lower().replace(" ", "")
    if t in {"все", "всё", "all", "va", "макс", "max"}:
        return balance if balance >= minimum else None
    if t in {"половина", "half", "пол"}:
        return balance // 2
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)%", t)
    if m:
        pct = float(m.group(1).replace(",", "."))
        return int(balance * min(pct, 100) / 100)
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)(k|к|kk|кк|m|м|kkk|ккк|b|б)?", t)
    if not m:
        return None
    val = float(m.group(1).replace(",", "."))
    suf = m.group(2) or ""
    mult = {"": 1, "k": 1e3, "к": 1e3, "kk": 1e6, "кк": 1e6, "m": 1e6, "м": 1e6,
            "kkk": 1e9, "ккк": 1e9, "b": 1e9, "б": 1e9}[suf]
    return int(val * mult)


def hms(seconds: int) -> str:
    h, rem = divmod(max(0, seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} ч {m} мин"
    if m:
        return f"{m} мин {s} сек"
    return f"{s} сек"


async def target_user(message: Message) -> Optional[User]:
    """Цель команды: реплай или @упоминание/числовой id в аргументах."""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user
    if message.entities:
        for ent in message.entities:
            if ent.type == "text_mention" and ent.user:
                return ent.user
    return None


def arg_text(message: Message) -> str:
    parts = (message.text or message.caption or "").split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


def args_list(message: Message) -> list[str]:
    return (message.text or "").split()[1:]
