"""Стартовые настройки чата.

Если база пустая (хостинг стёр диск, а резервной копии ещё нет), бот
не должен «забывать» тему описаний, тему граммов и состав модерации.
Здесь зашиты значения по умолчанию — они применяются ТОЛЬКО когда
соответствующей записи в базе нет. Ручные изменения не перетираются.
"""
from __future__ import annotations

import logging
import time

import db

log = logging.getLogger("irisbot.seed")

MAIN_CHAT = -1003934033202

# ключ -> значение (ставится, только если ключа ещё нет)
SETTINGS: dict[int, dict[str, str]] = {
    MAIN_CHAT: {
        "form_topic": "148507",     # тема, где новички пишут описание
        "form_required": "1",       # описание обязательно
        "gram_topic": "132681",     # тема для граммов и игр
        "topic": "описание",
    },
}

# состав модерации: username -> (имя, ранг, user_id)
STAFF: dict[int, dict[str, tuple[str, int, int]]] = {
    MAIN_CHAT: {
        "Kaktys6390": ("Kaktys6390", 8, 8297844640),
        "Ksyxa0201": ("D乇尺ZK卂ㄚ卂", 7, 682842064),
        "Simba253": ("Simba", 6, 8412527198),
        "sneik132": ("Sssss🔥", 3, 5955897143),
        "L_I_ZAVETKA": ("✃𝐿𝒾𝓏𝒶𝓋𝑒𝓉𝒶 ✁", 3, 6592023977),
        "Fil1003": ("Fil1003", 3, 0),
    },
}


async def apply() -> None:
    now = int(time.time())
    added_s = added_st = 0

    for chat_id, kv in SETTINGS.items():
        for key, val in kv.items():
            cur = await db.get_setting(chat_id, key, "")
            if cur == "":
                await db.set_setting(chat_id, key, val)
                added_s += 1

    for chat_id, people in STAFF.items():
        row = await db.fetchone(
            "SELECT COUNT(*) c FROM staff WHERE chat_id=?", (chat_id,))
        if row and int(row["c"]) > 0:
            continue                      # состав уже есть — не трогаем
        for pos, (uname, (name, rank, uid)) in enumerate(people.items()):
            await db.execute(
                "INSERT OR IGNORE INTO staff "
                "(chat_id, username, name, rank, user_id, left_chat, pos, ts) "
                "VALUES (?,?,?,?,?,0,?,?)",
                (chat_id, uname, name, rank, uid, pos, now))
            if uid:
                await db.execute(
                    "INSERT OR IGNORE INTO ranks "
                    "(chat_id, user_id, rank, granted_by, ts) VALUES (?,?,?,0,?)",
                    (chat_id, uid, rank, now))
            added_st += 1

    if added_s or added_st:
        log.info("Восстановлены значения по умолчанию: настроек %d, состав %d",
                 added_s, added_st)
