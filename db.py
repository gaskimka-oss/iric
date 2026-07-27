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
    ts INTEGER, PRIMARY KEY (user_id, target_id, kind));

CREATE TABLE IF NOT EXISTS awards (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER,
    title TEXT, by_id INTEGER, ts INTEGER);

CREATE TABLE IF NOT EXISTS profiles (
    user_id INTEGER PRIMARY KEY, about TEXT, city TEXT, age TEXT,
    birthday TEXT, hobby TEXT, contact TEXT,
    real_name TEXT, country TEXT, tz TEXT, family TEXT, nick2 TEXT,
    filled INTEGER NOT NULL DEFAULT 0, filled_ts INTEGER);

CREATE TABLE IF NOT EXISTS first_seen (
    chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
    ts INTEGER NOT NULL, PRIMARY KEY (chat_id, user_id));

CREATE TABLE IF NOT EXISTS vip (
    user_id INTEGER PRIMARY KEY, until INTEGER, level INTEGER DEFAULT 1);

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
        "profiles": [("real_name", "TEXT"), ("country", "TEXT"), ("tz", "TEXT"),
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
