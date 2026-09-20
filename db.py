"""Слой базы данных (SQLite через aiosqlite). Одно соединение + WAL."""
from __future__ import annotations

import time
from typing import Any, Iterable, Optional

import aiosqlite

from config import DB_PATH, START_BALANCE

_conn: Optional[aiosqlite.Connection] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    nick        TEXT,
    balance     INTEGER NOT NULL DEFAULT 0,
    bank        INTEGER NOT NULL DEFAULT 0,
    bank_ts     INTEGER NOT NULL DEFAULT 0,
    xp          INTEGER NOT NULL DEFAULT 0,
    rep         INTEGER NOT NULL DEFAULT 0,
    messages    INTEGER NOT NULL DEFAULT 0,
    married_to  INTEGER,
    married_at  INTEGER,
    banned      INTEGER NOT NULL DEFAULT 0,
    verified    INTEGER NOT NULL DEFAULT 0,
    grams       INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chat_stats (
    chat_id   INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    messages  INTEGER NOT NULL DEFAULT 0,
    xp        INTEGER NOT NULL DEFAULT 0,
    last_seen INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);

-- Последнее известное состояние членства. Перед массовым созывом бот всё
-- равно перепроверяет пользователя через Telegram API.
CREATE TABLE IF NOT EXISTS chat_members (
    chat_id   INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    status    TEXT NOT NULL DEFAULT 'member',
    is_member INTEGER NOT NULL DEFAULT 1,
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_chat_members_active
    ON chat_members(chat_id, is_member, updated_at);

CREATE TABLE IF NOT EXISTS chats (
    chat_id   INTEGER PRIMARY KEY,
    title     TEXT,
    added_at  INTEGER NOT NULL DEFAULT 0,
    silent    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cooldowns (
    user_id INTEGER NOT NULL,
    key     TEXT    NOT NULL,
    ts      INTEGER NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS warns (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    admin_id INTEGER NOT NULL,
    reason  TEXT,
    ts      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS marry_requests (
    from_id INTEGER NOT NULL,
    to_id   INTEGER NOT NULL,
    ts      INTEGER NOT NULL,
    PRIMARY KEY (from_id, to_id)
);

CREATE TABLE IF NOT EXISTS log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action  TEXT,
    amount  INTEGER,
    meta    TEXT,
    ts      INTEGER
);

CREATE TABLE IF NOT EXISTS ranks (
    chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
    rank INTEGER NOT NULL DEFAULT 0, granted_by INTEGER, ts INTEGER,
    PRIMARY KEY (chat_id, user_id));

CREATE TABLE IF NOT EXISTS staff (
    chat_id  INTEGER NOT NULL,
    username TEXT    NOT NULL,
    name     TEXT,
    rank     INTEGER NOT NULL DEFAULT 1,
    user_id  INTEGER DEFAULT 0,
    left_chat INTEGER NOT NULL DEFAULT 0,
    pos      INTEGER NOT NULL DEFAULT 0,
    ts       INTEGER,
    PRIMARY KEY (chat_id, username));

CREATE TABLE IF NOT EXISTS rank_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER,
    rank INTEGER, by_id INTEGER, ts INTEGER);

CREATE TABLE IF NOT EXISTS bans (
    chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, reason TEXT,
    by_id INTEGER, until INTEGER DEFAULT 0, ts INTEGER,
    PRIMARY KEY (chat_id, user_id));

CREATE TABLE IF NOT EXISTS mutes (
    chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, reason TEXT,
    by_id INTEGER, until INTEGER DEFAULT 0, ts INTEGER,
    PRIMARY KEY (chat_id, user_id));

CREATE TABLE IF NOT EXISTS settings (
    chat_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT,
    PRIMARY KEY (chat_id, key));

CREATE TABLE IF NOT EXISTS cmd_access (
    chat_id INTEGER NOT NULL, cmd TEXT NOT NULL, rank INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (chat_id, cmd));

CREATE TABLE IF NOT EXISTS cmd_personal (
    chat_id INTEGER NOT NULL, cmd TEXT NOT NULL, user_id INTEGER NOT NULL,
    mode TEXT NOT NULL DEFAULT 'allow',   -- allow | deny
    by_id INTEGER, ts INTEGER, PRIMARY KEY (chat_id, cmd, user_id));

CREATE TABLE IF NOT EXISTS punishments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,                   -- mute | ban | warn | kick
    reason TEXT, rule TEXT, seconds INTEGER DEFAULT 0,
    by_id INTEGER, ts INTEGER, active INTEGER NOT NULL DEFAULT 1,
    lifted_by INTEGER, lifted_ts INTEGER);
CREATE INDEX IF NOT EXISTS idx_pun_chat ON punishments(chat_id, user_id);

CREATE TABLE IF NOT EXISTS daily_stats (
    day TEXT NOT NULL, chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
    messages INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, chat_id, user_id));
CREATE INDEX IF NOT EXISTS idx_daily ON daily_stats(day, chat_id);

CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, item TEXT,
    stars INTEGER, amount INTEGER, ts INTEGER);

CREATE TABLE IF NOT EXISTS mod_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL, punish_id INTEGER,
    target_id INTEGER, target_name TEXT,
    by_id INTEGER, by_name TEXT,
    kind TEXT, reason TEXT, seconds INTEGER DEFAULT 0,
    context TEXT,              -- переписка вокруг нарушения
    source TEXT,               -- 'админ' | 'автомодерация'
    reviewed INTEGER NOT NULL DEFAULT 0,
    ai_verdict TEXT,           -- ok | soft | harsh | wrong
    ai_score INTEGER DEFAULT 0,
    ai_reason TEXT,
    ai_advice TEXT,
    ts INTEGER);
CREATE INDEX IF NOT EXISTS idx_modlog_chat ON mod_log(chat_id, ts);

CREATE TABLE IF NOT EXISTS lift_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL, log_id INTEGER, punish_id INTEGER,
    target_id INTEGER, target_name TEXT,
    kind TEXT, reason TEXT,            -- за что было наказание
    by_id INTEGER, by_name TEXT,       -- кто выдал
    lifted_by INTEGER, lifted_name TEXT,   -- кто снял
    ts INTEGER);
CREATE INDEX IF NOT EXISTS idx_liftlog ON lift_log(chat_id, ts);

CREATE TABLE IF NOT EXISTS msg_buffer (
    chat_id INTEGER NOT NULL, msg_id INTEGER NOT NULL,
    user_id INTEGER, user_name TEXT, text TEXT, ts INTEGER,
    PRIMARY KEY (chat_id, msg_id));
CREATE INDEX IF NOT EXISTS idx_buf ON msg_buffer(chat_id, ts);

CREATE TABLE IF NOT EXISTS chat_schedule (
    chat_id INTEGER PRIMARY KEY,
    open_at TEXT, close_at TEXT,          -- 'HH:MM' или NULL
    tz_offset INTEGER NOT NULL DEFAULT 3, -- часовой пояс (МСК по умолчанию)
    enabled INTEGER NOT NULL DEFAULT 0,
    last_open TEXT, last_close TEXT);

CREATE TABLE IF NOT EXISTS access_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, cmd TEXT,
    rank INTEGER, enabled INTEGER, by_id INTEGER, ts INTEGER);

CREATE TABLE IF NOT EXISTS triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, pattern TEXT,
    answer TEXT, action TEXT, by_id INTEGER, ts INTEGER);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER,
    name TEXT, text TEXT, ts INTEGER);

CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT,
    link TEXT, ts INTEGER);

CREATE TABLE IF NOT EXISTS timers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER,
    text TEXT, fire_at INTEGER, done INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS clans (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, owner_id INTEGER,
    balance INTEGER DEFAULT 0, descr TEXT, ts INTEGER);

CREATE TABLE IF NOT EXISTS clan_members (
    clan_id INTEGER NOT NULL, user_id INTEGER NOT NULL PRIMARY KEY, ts INTEGER);

CREATE TABLE IF NOT EXISTS relations (
    user_id INTEGER NOT NULL, target_id INTEGER NOT NULL, kind TEXT NOT NULL,
    ts INTEGER, count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, target_id, kind));

CREATE TABLE IF NOT EXISTS awards (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER,
    title TEXT, by_id INTEGER, ts INTEGER);

CREATE TABLE IF NOT EXISTS profiles (
    user_id INTEGER PRIMARY KEY, about TEXT, city TEXT, age TEXT,
    birthday TEXT, hobby TEXT, contact TEXT,
    real_name TEXT, country TEXT, tz TEXT, family TEXT, nick2 TEXT,
    gender TEXT,               -- пол, если человек его указал
    custom TEXT,               -- описание, вписанное админом вручную
    custom_by INTEGER, custom_ts INTEGER,
    filled INTEGER NOT NULL DEFAULT 0, filled_ts INTEGER);

CREATE TABLE IF NOT EXISTS first_seen (
    chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
    ts INTEGER NOT NULL, PRIMARY KEY (chat_id, user_id));

CREATE TABLE IF NOT EXISTS vip (
    user_id INTEGER PRIMARY KEY, until INTEGER, level INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS vip_settings (
    user_id INTEGER PRIMARY KEY,
    color_theme TEXT NOT NULL DEFAULT 'default'
);

CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user1_id INTEGER NOT NULL,
    user2_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    xp INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 1,
    offended_by INTEGER DEFAULT NULL,
    soothe_points INTEGER NOT NULL DEFAULT 0,
    soothe_last_ts INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user1_id, user2_id)
);
CREATE INDEX IF NOT EXISTS idx_rel_u1 ON relationships(user1_id);
CREATE INDEX IF NOT EXISTS idx_rel_u2 ON relationships(user2_id);

CREATE TABLE IF NOT EXISTS relationship_cooldowns (
    rel_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    action_key TEXT NOT NULL,
    last_ts INTEGER NOT NULL,
    PRIMARY KEY (rel_id, user_id, action_key)
);

CREATE TABLE IF NOT EXISTS relationship_property (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rel_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    item_name TEXT NOT NULL,
    price INTEGER NOT NULL DEFAULT 0,
    bought_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS relationship_children (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rel_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    gender TEXT NOT NULL,
    born_at INTEGER NOT NULL,
    care_last_ts INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS spam_base (
    user_id INTEGER PRIMARY KEY, reason TEXT, by_id INTEGER, ts INTEGER);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER,
    target_id INTEGER, text TEXT, status TEXT DEFAULT 'open', ts INTEGER);

CREATE TABLE IF NOT EXISTS giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, prize TEXT,
    owner_id INTEGER, until INTEGER, done INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS giveaway_members (
    gid INTEGER NOT NULL, user_id INTEGER NOT NULL, PRIMARY KEY (gid, user_id));

CREATE TABLE IF NOT EXISTS market (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT,
    amount INTEGER, price INTEGER, ts INTEGER);

CREATE TABLE IF NOT EXISTS net_chats (
    net_id INTEGER NOT NULL, chat_id INTEGER NOT NULL, num INTEGER,
    PRIMARY KEY (net_id, chat_id));

CREATE TABLE IF NOT EXISTS votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, cmd TEXT,
    target_id INTEGER, by_id INTEGER, need INTEGER, ts INTEGER);

CREATE TABLE IF NOT EXISTS vote_marks (
    vote_id INTEGER NOT NULL, user_id INTEGER NOT NULL, PRIMARY KEY (vote_id, user_id));

-- Две связанные группы клана. Роли: admin и clan.
CREATE TABLE IF NOT EXISTS clan_groups (
    role TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL UNIQUE,
    title TEXT,
    updated_by INTEGER,
    ts INTEGER);

-- Защита от повторной обработки двух Telegram-событий одного сквозного бана.
CREATE TABLE IF NOT EXISTS clan_crossban_lock (
    user_id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL);

-- Отложенный мут/бан по @username. Нужен, потому что Bot API не умеет
-- мгновенно преобразовывать неизвестный username обычного пользователя в ID.
CREATE TABLE IF NOT EXISTS pending_punishments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    kind TEXT NOT NULL,
    reason TEXT,
    seconds INTEGER NOT NULL DEFAULT 0,
    by_id INTEGER NOT NULL DEFAULT 0,
    ts INTEGER NOT NULL,
    UNIQUE(chat_id, username, kind));

CREATE INDEX IF NOT EXISTS idx_log_user ON log(user_id);
CREATE INDEX IF NOT EXISTS idx_stats_chat ON chat_stats(chat_id);
"""


async def init() -> None:
    global _conn
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _conn = await aiosqlite.connect(DB_PATH)
    _conn.row_factory = aiosqlite.Row
    await _conn.execute("PRAGMA journal_mode=WAL")
    await _conn.execute("PRAGMA foreign_keys=ON")
    await _conn.executescript(SCHEMA)
    await _migrate()
    await _conn.commit()


async def _migrate() -> None:
    """Добавляет недостающие колонки в уже существующих базах."""
    wanted = {
        "staff": [("pos", "INTEGER NOT NULL DEFAULT 0"),
                  ("left_chat", "INTEGER NOT NULL DEFAULT 0")],
        "cmd_personal": [("mode", "TEXT NOT NULL DEFAULT 'allow'")],
        "mod_log": [("ai_verdict", "TEXT"), ("ai_score", "INTEGER DEFAULT 0"),
                    ("ai_reason", "TEXT"), ("ai_advice", "TEXT")],
        "users": [("verified", "INTEGER NOT NULL DEFAULT 0"),
                  ("grams", "INTEGER NOT NULL DEFAULT 0")],
        "relations": [("count", "INTEGER NOT NULL DEFAULT 1")],
        "profiles": [("gender", "TEXT"), ("custom", "TEXT"), ("custom_by", "INTEGER"),
                     ("custom_ts", "INTEGER"),
                     ("real_name", "TEXT"), ("country", "TEXT"), ("tz", "TEXT"),
                     ("family", "TEXT"), ("nick2", "TEXT"),
                     ("filled", "INTEGER NOT NULL DEFAULT 0"), ("filled_ts", "INTEGER")],
    }
    for table, cols in wanted.items():
        try:
            async with _conn.execute(f"PRAGMA table_info({table})") as cur:
                have = {r[1] for r in await cur.fetchall()}
        except Exception:
            continue
        for name, ddl in cols:
            if name not in have:
                try:
                    await _conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                except Exception:
                    pass


async def close() -> None:
    if _conn:
        await _conn.close()


def conn() -> aiosqlite.Connection:
    if _conn is None:
        raise RuntimeError("DB не инициализирована: вызовите db.init()")
    return _conn


async def execute(sql: str, params: Iterable[Any] = ()) -> None:
    await conn().execute(sql, tuple(params))
    await conn().commit()


async def fetchone(sql: str, params: Iterable[Any] = ()) -> Optional[aiosqlite.Row]:
    async with conn().execute(sql, tuple(params)) as cur:
        return await cur.fetchone()


async def fetchall(sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
    async with conn().execute(sql, tuple(params)) as cur:
        return list(await cur.fetchall())


# --- Пользователи ---------------------------------------------------------
async def get_user(user_id: int) -> aiosqlite.Row:
    row = await fetchone("SELECT * FROM users WHERE user_id=?", (user_id,))
    if row is None:
        await execute(
            "INSERT OR IGNORE INTO users (user_id, balance, created_at) VALUES (?,?,?)",
            (user_id, START_BALANCE, int(time.time())),
        )
        row = await fetchone("SELECT * FROM users WHERE user_id=?", (user_id,))
    return row  # type: ignore[return-value]


async def touch_user(user_id: int, username: str | None, first_name: str | None) -> None:
    await get_user(user_id)
    await execute(
        "UPDATE users SET username=?, first_name=? WHERE user_id=?",
        (username, first_name, user_id),
    )
    # состав мог быть импортирован по @нику без id — связываем при первом сообщении
    if username:
        rows = await fetchall(
            "SELECT chat_id, rank FROM staff WHERE lower(username)=lower(?) "
            "AND (user_id IS NULL OR user_id=0)", (username,))
        for r in rows:
            await execute(
                "UPDATE staff SET user_id=? WHERE chat_id=? AND lower(username)=lower(?)",
                (user_id, r["chat_id"], username))
            await execute(
                "INSERT INTO ranks (chat_id,user_id,rank,granted_by,ts) VALUES (?,?,?,0,?) "
                "ON CONFLICT(chat_id,user_id) DO UPDATE SET rank=MAX(ranks.rank, excluded.rank)",
                (r["chat_id"], user_id, r["rank"], int(__import__("time").time())))


async def add_balance(user_id: int, amount: int, action: str = "", meta: str = "") -> int:
    await get_user(user_id)
    await execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    if action:
        await execute(
            "INSERT INTO log (user_id, action, amount, meta, ts) VALUES (?,?,?,?,?)",
            (user_id, action, amount, meta, int(time.time())),
        )
    row = await fetchone("SELECT balance FROM users WHERE user_id=?", (user_id,))
    return row["balance"] if row else 0


async def set_balance(user_id: int, amount: int) -> None:
    await get_user(user_id)
    await execute("UPDATE users SET balance=? WHERE user_id=?", (max(0, amount), user_id))


async def add_xp(user_id: int, amount: int) -> None:
    await execute("UPDATE users SET xp = xp + ?, messages = messages + 1 WHERE user_id=?",
                  (amount, user_id))


# --- Кулдауны -------------------------------------------------------------
async def cooldown_left(user_id: int, key: str, period: int) -> int:
    row = await fetchone("SELECT ts FROM cooldowns WHERE user_id=? AND key=?", (user_id, key))
    if not row:
        return 0
    left = int(row["ts"]) + period - int(time.time())
    return max(0, left)


async def set_cooldown(user_id: int, key: str) -> None:
    await execute(
        "INSERT INTO cooldowns (user_id, key, ts) VALUES (?,?,?) "
        "ON CONFLICT(user_id, key) DO UPDATE SET ts=excluded.ts",
        (user_id, key, int(time.time())),
    )


# --- Чаты и статистика ----------------------------------------------------
async def register_chat(chat_id: int, title: str | None) -> None:
    await execute(
        "INSERT INTO chats (chat_id, title, added_at) VALUES (?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title",
        (chat_id, title, int(time.time())),
    )


async def bump_chat_stat(chat_id: int, user_id: int, xp: int) -> None:
    await execute(
        "INSERT INTO chat_stats (chat_id, user_id, messages, xp, last_seen) VALUES (?,?,1,?,?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET "
        "messages = messages + 1, xp = xp + excluded.xp, last_seen = excluded.last_seen",
        (chat_id, user_id, xp, int(time.time())),
    )

# --- Настройки чата -------------------------------------------------------
async def get_setting(chat_id: int, key: str, default: str = "") -> str:
    row = await fetchone("SELECT value FROM settings WHERE chat_id=? AND key=?", (chat_id, key))
    return row["value"] if row else default


async def set_setting(chat_id: int, key: str, value: str) -> None:
    await execute(
        "INSERT INTO settings (chat_id, key, value) VALUES (?,?,?) "
        "ON CONFLICT(chat_id, key) DO UPDATE SET value=excluded.value",
        (chat_id, key, value))


# --- Граммы (вторая валюта) ----------------------------------------------
async def get_grams(user_id: int) -> int:
    await get_user(user_id)
    row = await fetchone("SELECT grams FROM users WHERE user_id=?", (user_id,))
    return int(row["grams"]) if row else 0


async def add_grams(user_id: int, amount: int, action: str = "",
                    meta: str = "") -> int:
    await get_user(user_id)
    await execute("UPDATE users SET grams = MAX(0, grams + ?) WHERE user_id=?",
                  (amount, user_id))
    if action:
        import time as _t
        await execute(
            "INSERT INTO log (user_id, action, amount, meta, ts) VALUES (?,?,?,?,?)",
            (user_id, action, amount, meta, int(_t.time())))
    row = await fetchone("SELECT grams FROM users WHERE user_id=?", (user_id,))
    return int(row["grams"]) if row else 0


# --- VIP & VIP+ -----------------------------------------------------------
async def get_vip_info(user_id: int) -> tuple[int, int, bool]:
    """Возвращает (level, until, is_active). Level: 1 = VIP, 2 = VIP+."""
    row = await fetchone("SELECT until, level FROM vip WHERE user_id=?", (user_id,))
    if not row:
        return 0, 0, False
    lvl = row["level"] or 1
    until = row["until"] or 0
    active = until > time.time()
    return lvl if active else 0, until, active


async def set_vip(user_id: int, until: int, level: int = 1) -> None:
    await execute(
        "INSERT INTO vip (user_id, until, level) VALUES (?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET until=excluded.until, level=excluded.level",
        (user_id, until, level))


async def remove_vip(user_id: int) -> None:
    await execute("DELETE FROM vip WHERE user_id=?", (user_id,))


async def get_vip_theme(user_id: int) -> str:
    row = await fetchone("SELECT color_theme FROM vip_settings WHERE user_id=?", (user_id,))
    return row["color_theme"] if row else "default"


async def set_vip_theme(user_id: int, theme: str) -> None:
    await execute(
        "INSERT INTO vip_settings (user_id, color_theme) VALUES (?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET color_theme=excluded.color_theme",
        (user_id, theme))


# --- Отношения (ОТН) -------------------------------------------------------
REL_LEVELS = {
    1: 0,
    2: 50,
    3: 150,
    4: 350,
    5: 700,
    6: 1500,
    7: 3000,
    8: 6000,
}


def calc_rel_level(xp: int) -> int:
    lvl = 1
    for l, req in sorted(REL_LEVELS.items()):
        if xp >= req:
            lvl = l
    return lvl


async def get_relationship(user_id: int) -> dict | None:
    """Возвращает запись отношений, где пользователь является участником."""
    return await fetchone(
        "SELECT * FROM relationships WHERE user1_id=? OR user2_id=?",
        (user_id, user_id))


async def get_rel_by_id(rel_id: int) -> dict | None:
    return await fetchone("SELECT * FROM relationships WHERE id=?", (rel_id,))


async def create_relationship(u1: int, u2: int) -> int:
    ts = int(time.time())
    await execute(
        "INSERT INTO relationships (user1_id, user2_id, created_at, xp, level) "
        "VALUES (?,?,?,0,1)", (u1, u2, ts))
    await execute("UPDATE users SET married_to=?, married_at=? WHERE user_id=?", (u2, ts, u1))
    await execute("UPDATE users SET married_to=?, married_at=? WHERE user_id=?", (u1, ts, u2))
    row = await fetchone("SELECT last_insert_rowid() id")
    return int(row["id"]) if row else 0


async def delete_relationship(rel_id: int) -> None:
    rel = await get_rel_by_id(rel_id)
    if rel:
        await execute("UPDATE users SET married_to=NULL, married_at=NULL WHERE user_id IN (?,?)",
                      (rel["user1_id"], rel["user2_id"]))
    await execute("DELETE FROM relationships WHERE id=?", (rel_id,))
    await execute("DELETE FROM relationship_cooldowns WHERE rel_id=?", (rel_id,))
    await execute("DELETE FROM relationship_property WHERE rel_id=?", (rel_id,))
    await execute("DELETE FROM relationship_children WHERE rel_id=?", (rel_id,))


async def add_rel_xp(rel_id: int, amount: int) -> tuple[int, int, bool]:
    """Добавляет XP и возвращает (new_xp, new_level, is_level_up)."""
    rel = await get_rel_by_id(rel_id)
    if not rel:
        return 0, 1, False
    old_lvl = rel["level"]
    new_xp = rel["xp"] + amount
    new_lvl = calc_rel_level(new_xp)
    await execute("UPDATE relationships SET xp=?, level=? WHERE id=?",
                  (new_xp, new_lvl, rel_id))
    return new_xp, new_lvl, (new_lvl > old_lvl)


async def set_rel_offended(rel_id: int, offended_by: int | None) -> None:
    await execute(
        "UPDATE relationships SET offended_by=?, soothe_points=0, soothe_last_ts=0 WHERE id=?",
        (offended_by, rel_id))


async def soothe_rel(rel_id: int, points: int) -> tuple[int, bool]:
    """Добавляет очки задабривания. Возвращает (всего_очков, снята_ли_обида)."""
    rel = await get_rel_by_id(rel_id)
    if not rel:
        return 0, False
    total = rel["soothe_points"] + points
    now = int(time.time())
    if total >= 100:
        await execute(
            "UPDATE relationships SET offended_by=NULL, soothe_points=0, soothe_last_ts=? WHERE id=?",
            (now, rel_id))
        return total, True
    await execute(
        "UPDATE relationships SET soothe_points=?, soothe_last_ts=? WHERE id=?",
        (total, now, rel_id))
    return total, False


async def get_rel_cooldown_left(rel_id: int, user_id: int, action_key: str, period: int) -> int:
    row = await fetchone(
        "SELECT last_ts FROM relationship_cooldowns WHERE rel_id=? AND user_id=? AND action_key=?",
        (rel_id, user_id, action_key))
    if not row:
        return 0
    left = int(row["last_ts"]) + period - int(time.time())
    return max(0, left)


async def set_rel_cooldown(rel_id: int, user_id: int, action_key: str) -> None:
    await execute(
        "INSERT INTO relationship_cooldowns (rel_id, user_id, action_key, last_ts) VALUES (?,?,?,?) "
        "ON CONFLICT(rel_id, user_id, action_key) DO UPDATE SET last_ts=excluded.last_ts",
        (rel_id, user_id, action_key, int(time.time())))


async def get_rel_properties(rel_id: int) -> list[dict]:
    return await fetchall("SELECT * FROM relationship_property WHERE rel_id=? ORDER BY price ASC", (rel_id,))


async def add_rel_property(rel_id: int, item_key: str, item_name: str, price: int) -> None:
    await execute(
        "INSERT INTO relationship_property (rel_id, item_key, item_name, price, bought_at) "
        "VALUES (?,?,?,?,?)", (rel_id, item_key, item_name, price, int(time.time())))


async def get_rel_children(rel_id: int) -> list[dict]:
    return await fetchall("SELECT * FROM relationship_children WHERE rel_id=? ORDER BY id ASC", (rel_id,))


async def add_rel_child(rel_id: int, name: str, gender: str) -> None:
    await execute(
        "INSERT INTO relationship_children (rel_id, name, gender, born_at, care_last_ts) "
        "VALUES (?,?,?,?,?)", (rel_id, name, gender, int(time.time()), int(time.time())))


async def get_all_relationships() -> list[dict]:
    return await fetchall("SELECT * FROM relationships ORDER BY level DESC, xp DESC, id ASC")


