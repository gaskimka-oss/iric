"""Реестр команд: единый источник правды для диспетчера И для справки.

Каждая команда объявляется декоратором-фильтром Cmd(...) прямо в хэндлере,
попадает в REGISTRY и автоматически появляется в /help и в telegra.ph-справке.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from aiogram.filters import Filter
from aiogram.types import Message

# Префиксы как в Ирисе: !, ., /, «Ирис», «Ириска» + без префикса
PREFIX_CHARS = "!./"
PREFIX_WORDS = ("ириска", "ирис")

SECTIONS: dict[int, str] = {
    1: "Команды модерации",
    2: "Система банов и предупреждений",
    3: "Триггеры и автонаказания",
    4: "Настройка доступа команд",
    5: "Чистка чата",
    6: "Настройка чата",
    7: "Сетка чатов",
    8: "Анкета пользователя",
    9: "Статистическая информация",
    10: "Темы модераторов",
    11: "Голосование за команды",
    12: "Антиспам и SCAM",
    13: "Ириски, бонусы, магазин",
    14: "Развлекательные команды",
    15: "Модуль «Дуэли»",
    16: "Модуль «Кубы»",
    17: "Модуль «Кланы»",
    18: "Модуль «Кружки»",
    19: "РП-команды (действия)",
    20: "Модуль «Браки»",
    21: "Модуль «Репутация»",
    22: "Модуль «Награды»",
    23: "Модуль «Закладки»",
    24: "Модуль «Заметки»",
    25: "Модуль «Таймеры»",
    26: "Модуль «Каталог»",
    27: "Модуль «Ирис-биржа»",
    28: "Инлайн-режим",
    29: "Бизнес-бот",
    30: "Модуль «Репорты»",
    31: "Модуль «Розыгрыши»",
    32: "Интеграция с Telegram",
    33: "Граммы и игры",
}

SECTION_EMOJI: dict[int, str] = {
    1: "🛡", 2: "🚫", 3: "⚡️", 4: "🔐", 5: "🧹", 6: "⚙️", 7: "🕸", 8: "📝",
    9: "📊", 10: "🧵", 11: "🗳", 12: "🛰", 13: "🍬", 14: "🎲", 15: "⚔️",
    16: "🎯", 17: "🏰", 18: "⭕️", 19: "💞", 20: "💍", 21: "⭐️", 22: "🏅",
    23: "🔖", 24: "🗒", 25: "⏰", 26: "📚", 27: "💱", 28: "🔎", 29: "💼",
    30: "📣", 31: "🎁", 32: "🔗",
}

MAX_RANK = 8

RANK_NAMES = {
    0: "Участник",
    1: "Младший модератор",
    2: "Старший модератор",
    3: "Младший админ",
    4: "Старший админ",
    5: "Создатель",
    6: "Технический администратор",
    7: "Заместитель лидера",
    8: "Лидер клана",
}

# Заголовки групп в составе модерации (множественное число)
RANK_TITLES = {
    1: "Младшие модераторы",
    2: "Старшие модераторы",
    3: "Младшие админы",
    4: "Старшие админы",
    5: "Создатели",
    6: "Технические администраторы",
    7: "Заместители лидера",
    8: "Лидеры клана",
}


def stars(rank: int) -> str:
    return "⭐" * max(0, min(rank, MAX_RANK))


@dataclass
class CmdInfo:
    names: tuple[str, ...]
    section: int
    usage: str = ""
    desc: str = ""
    rank: int = 0
    anchor: str = ""
    key: str = ""          # каноничное имя — ключ настроек ДК
    group_only: bool = False

    @property
    def base_rank(self) -> int:
        return self.rank


REGISTRY: list[CmdInfo] = []

# Все известные имена команд (включая скрытые) — для разрешения конфликтов
ALL_NAMES: set[str] = set()


def _norm(s: str) -> str:
    return s.lower().replace("ё", "е").strip()


class Cmd(Filter):
    """Фильтр команды в стиле Ириса.

    Понимает префиксы !, ., /, «Ирис», «Ириска» и работу вообще без префикса.
    В хэндлер передаёт args — остаток строки после названия команды.
    """

    __slots__ = ("names", "need_prefix", "key", "base_rank", "group_only")

    def __init__(self, *names: str, section: int = 14, usage: str = "",
                 desc: str = "", rank: int = 0, need_prefix: bool = False,
                 hidden: bool = False, group_only: bool = False) -> None:
        # длинные названия первыми: «снять всех» должно матчиться раньше «снять»
        self.names = tuple(sorted((_norm(n) for n in names), key=len, reverse=True))
        self.key = _norm(names[0])      # каноничное имя — ключ для ДК
        self.base_rank = rank
        self.need_prefix = need_prefix
        self.group_only = group_only
        ALL_NAMES.update(self.names)
        if not hidden:
            REGISTRY.append(CmdInfo(tuple(names), section, usage or names[0],
                                    desc, rank, key=self.key,
                                    group_only=group_only))

    async def __call__(self, message: Message) -> bool | dict[str, Any]:
        text = (message.text or message.caption or "").strip()
        if not text:
            return False
        # команды чата не работают в личных сообщениях
        if self.group_only and getattr(message.chat, "type", "") == "private":
            return False
        body = text
        had_prefix = False

        # символьный префикс: !, ., / (в т.ч. повторы !!! для рангов)
        if body[0] in PREFIX_CHARS:
            body = body.lstrip(PREFIX_CHARS).strip()
            had_prefix = True
        else:
            low = _norm(body)
            for w in PREFIX_WORDS:
                if low == w or low.startswith(w + " ") or low.startswith(w + ","):
                    body = body[len(w):].lstrip(" ,").strip()
                    had_prefix = True
                    break

        if self.need_prefix and not had_prefix:
            return False
        if not body:
            return False

        low = _norm(body)

        def shadowed(matched: str) -> bool:
            """Есть ли более длинная команда, которая тоже подходит под текст.

            «кто» не должно перехватывать «кто админ», «топ» — «топ дня».
            """
            for other in ALL_NAMES:
                if len(other) <= len(matched) or not low.startswith(other):
                    continue
                if len(low) == len(other) or low[len(other)] in (" ", "\n", ",", ":"):
                    return True
            return False

        for name in self.names:
            if low == name:
                if shadowed(name):
                    return False
                return {"args": "", "cmd_name": name,
                        "cmd_key": self.key, "cmd_rank": self.base_rank,
                        "had_prefix": had_prefix}
            if low.startswith(name):
                nxt = low[len(name):]
                # следующий символ — разделитель (пробел/перенос), а не часть слова
                if nxt[:1] in (" ", "\n", ",", ":"):
                    if shadowed(name):
                        return False
                    return {"args": body[len(name):].lstrip(" ,:\n").strip(),
                            "cmd_name": name, "cmd_key": self.key,
                            "cmd_rank": self.base_rank,
                            "had_prefix": had_prefix}
        return False


def registry_by_section() -> dict[int, list[CmdInfo]]:
    out: dict[int, list[CmdInfo]] = {}
    for c in REGISTRY:
        out.setdefault(c.section, []).append(c)
    return out


def find_commands(query: str) -> list[CmdInfo]:
    """Поиск команды по подстроке — для /найти."""
    q = _norm(query)
    res = []
    for c in REGISTRY:
        if any(q in _norm(n) for n in c.names) or q in _norm(c.desc):
            res.append(c)
    return res
