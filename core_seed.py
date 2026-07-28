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


async def mark_filled_profiles() -> int:
    """Тем, кто уже присылал анкету, ставим метку «заполнено».

    Раньше метка требовала 3 распознанных поля, из-за чего людей
    переспрашивали в других темах. Теперь достаточно двух — проходим
    по старым профилям и проставляем метку задним числом.
    """
    from h_userinfo import FIELDS, MIN_FIELDS
    rows = await db.fetchall("SELECT * FROM profiles WHERE filled=0")
    n = 0
    for p in rows:
        if sum(1 for _, _, c in FIELDS if c in p.keys() and p[c]) >= MIN_FIELDS:
            await db.execute(
                "UPDATE profiles SET filled=1, filled_ts=COALESCE(filled_ts,?) "
                "WHERE user_id=?", (int(time.time()), p["user_id"]))
            n += 1
    if n:
        log.info("Отмечено как заполненные: %d анкет", n)
    return n


async def fix_topic_note() -> None:
    """Убирает старую общечатовую подпись вида «граммы»/«описание».

    Из-за неё команда «тема» показывала одно и то же во всех темах:
    в теме описаний могло писать «граммы». Настоящие привязки тем
    хранятся в form_topic / gram_topic и не затрагиваются.
    """
    rows = await db.fetchall("SELECT chat_id, value FROM settings WHERE key='topic'")
    for r in rows:
        val = (r["value"] or "").strip().lower()
        if val in {"граммы", "граммов", "грамм", "описание", "описания",
                   "казино", "игры", "анкета", "анкеты"}:
            await db.execute("DELETE FROM settings WHERE chat_id=? AND key='topic'",
                             (r["chat_id"],))
            log.info("Убрана устаревшая подпись темы «%s» в чате %s",
                     val, r["chat_id"])


# Чьё описание считать настоящим, если одна анкета оказалась у нескольких.
# Ключ — user_id владельца анкеты. У остальных копия стирается.
TRUE_OWNERS = {
    6592023977,        # @L_I_ZAVETKA — «Лизавета Сергеевна»
}


async def wipe_duplicate_profiles() -> int:
    """Стирает чужие копии одной и той же анкеты.

    Из-за старого бага бот подставлял чужое описание другим людям,
    и оно сохранялось им в профиль. Настоящий владелец определяется
    по TRUE_OWNERS, а при равных условиях — по самой ранней записи.
    """
    from h_userinfo import FIELDS

    rows = await db.fetchall("SELECT * FROM profiles")
    groups: dict[tuple, list] = {}
    for r in rows:
        key = tuple((r[c] or "").strip().lower() for _, _, c in FIELDS)
        if not any(key):
            continue
        groups.setdefault(key, []).append(r)

    cols = ", ".join(f"{c}=NULL" for _, _, c in FIELDS)
    wiped = 0
    for key, people in groups.items():
        if len(people) < 2:
            continue
        owner = next((p for p in people if p["user_id"] in TRUE_OWNERS), None)
        if owner is None:
            owner = min(people, key=lambda p: p["filled_ts"] or 0)
        for p in people:
            if p["user_id"] == owner["user_id"]:
                continue
            await db.execute(
                f"UPDATE profiles SET {cols}, about=NULL, custom=NULL, "
                f"custom_by=NULL, custom_ts=NULL, filled=0, filled_ts=NULL "
                f"WHERE user_id=?", (p["user_id"],))
            wiped += 1
            log.info("Стёрта чужая копия анкеты у %s (владелец %s)",
                     p["user_id"], owner["user_id"])
    if wiped:
        log.info("Всего стёрто чужих копий анкет: %d", wiped)
    return wiped


async def apply() -> None:
    now = int(time.time())
    added_s = added_st = 0

    try:
        await mark_filled_profiles()
    except Exception as e:
        log.warning("отметка анкет: %s", e)

    try:
        await fix_topic_note()
    except Exception as e:
        log.warning("чистка подписи темы: %s", e)

    try:
        await wipe_duplicate_profiles()
    except Exception as e:
        log.warning("чистка дублей анкет: %s", e)

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
