"""Модуль «Турник»: турниры с описанием, видео, кнопками участия и автосозывом.

Как это работает:
  • Админ пишет «+турик» — бот проводит пошаговое создание: название,
    дата и время начала, описание/правила, видео (можно пропустить).
  • Анонс с кнопками «✅ Участвую» / «❌ Не участвую» появляется в чате,
    а также дублируется в связанные группы клана (админскую и клановую —
    «важные шишки»), если они назначены командами связки.
  • Любой игрок пишет «турик» — видит актуальную карточку турнира
    (описание, видео, состав) и отмечается кнопками.
  • Состав (кто идёт / кто нет) обновляется живьём во всех копиях анонса.
  • За 30 минут до старта бот напоминает участникам, а в момент старта
    автоматически созывает всех отметившихся «Участвую» — тегает их и
    зовёт заходить в игру.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.filters import Filter
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

import db
import core_members as members
from core_ranks import require
from core_registry import Cmd

router = Router(name="tournament")
log = logging.getLogger("irisbot.tournament")

S = 34                     # номер раздела в справке
ADMIN_RANK = 3             # минимальный ранг для управления турнирами
BATCH = 25                 # упоминаний в одном сообщении созыва
REMIND_BEFORE = 30 * 60    # за сколько секунд до старта напоминать
WIZARD_TTL = 600           # сессия мастера создания, сек
MAX_POSTS_SYNC = 30        # сколько копий анонса синхронизируем
NAMES_IN_CARD = 15         # имён каждой стороны в карточке
MAX_DESCR = 2500           # длина описания
WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tournaments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,          -- домашний чат турнира
    title       TEXT NOT NULL,
    descr       TEXT,
    start_ts    INTEGER NOT NULL,          -- unix-время начала
    tz_offset   INTEGER NOT NULL DEFAULT 3,
    video_id    TEXT,                       -- file_id видео из Telegram
    created_by  INTEGER,
    active      INTEGER NOT NULL DEFAULT 1, -- идёт сбор
    done        INTEGER NOT NULL DEFAULT 0, -- созыв выполнен
    reminded    INTEGER NOT NULL DEFAULT 0, -- 30-минутное напоминание отправлено
    ts          INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS tournament_members (
    tour_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    status  TEXT NOT NULL,                  -- 'yes' | 'no'
    ts      INTEGER NOT NULL,
    PRIMARY KEY (tour_id, user_id)
);
CREATE TABLE IF NOT EXISTS tournament_posts (
    tour_id    INTEGER NOT NULL,
    chat_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    PRIMARY KEY (tour_id, chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_tour_posts ON tournament_posts(tour_id);
"""

_ready = False


async def _ensure() -> None:
    """Создаёт таблицы модуля при первом обращении."""
    global _ready
    if _ready:
        return
    for stmt in _SCHEMA.split(";"):
        stmt = stmt.strip()
        if stmt:
            await db.execute(stmt)
    _ready = True


# --------------------------------------------------------------------------
# Время и даты
# --------------------------------------------------------------------------
_DATE_RE = re.compile(
    r"^(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\s+(\d{1,2})[:.](\d{2})$")


async def _chat_tz(chat_id: int) -> int:
    """Часовой пояс чата: берём из расписания (chat_schedule), по умолчанию МСК."""
    try:
        row = await db.fetchone(
            "SELECT tz_offset FROM chat_schedule WHERE chat_id=?", (chat_id,))
        if row and row["tz_offset"] is not None:
            return int(row["tz_offset"])
    except Exception:
        pass
    return 3


def parse_datetime(raw: str, tz_off: int) -> Optional[int]:
    """'25.08 19:30' или '25.08.2026 19:30' -> unix-timestamp (или None)."""
    m = _DATE_RE.match(raw.strip())
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    year = int(m.group(3)) if m.group(3) else None
    hour, minute = int(m.group(4)), int(m.group(5))
    if year is not None and year < 100:
        year += 2000
    tz = timezone(timedelta(hours=tz_off))
    now = datetime.now(tz)
    year = year or now.year
    try:
        dt = datetime(year, month, day, hour, minute, tzinfo=tz)
    except ValueError:
        return None
    # даты без года, которая уже прошла, относим к следующему году
    if m.group(3) is None and dt < now:
        try:
            dt = datetime(year + 1, month, day, hour, minute, tzinfo=tz)
        except ValueError:
            return None
    return int(dt.timestamp())


def human_dt(ts: int, tz_off: int) -> str:
    dt = datetime.fromtimestamp(ts, timezone(timedelta(hours=tz_off)))
    wd = WEEKDAYS[dt.weekday()]
    return f"{dt:%d.%m.%Y} ({wd}) {dt:%H:%M} UTC{tz_off:+d}"


def _left(ts: int) -> str:
    """'через 2 дн 5 ч' — сколько осталось до старта."""
    sec = ts - int(time.time())
    if sec <= 0:
        return "уже начался"
    days, sec = divmod(sec, 86400)
    hours, sec = divmod(sec, 3600)
    minutes = sec // 60
    parts = []
    if days:
        parts.append(f"{days} дн")
    if hours:
        parts.append(f"{hours} ч")
    if not days and minutes:
        parts.append(f"{minutes} мин")
    return "через " + " ".join(parts) if parts else "меньше минуты"


# --------------------------------------------------------------------------
# База модуля
# --------------------------------------------------------------------------
async def _active_tournament(chat_id: int):
    """Ближайший активный турнир, видимый в этом чате."""
    return await db.fetchone(
        "SELECT t.* FROM tournaments t WHERE t.active=1 AND (t.chat_id=? OR "
        "EXISTS (SELECT 1 FROM tournament_posts p "
        "        WHERE p.tour_id=t.id AND p.chat_id=?)) "
        "ORDER BY t.start_ts LIMIT 1", (chat_id, chat_id))


async def _votes(tour_id: int) -> tuple[list[dict], list[dict]]:
    rows = await db.fetchall(
        "SELECT m.user_id, m.status, COALESCE(u.first_name,'') name "
        "FROM tournament_members m LEFT JOIN users u ON u.user_id=m.user_id "
        "WHERE m.tour_id=? ORDER BY m.ts", (tour_id,))
    yes = [dict(r) for r in rows if r["status"] == "yes"]
    no = [dict(r) for r in rows if r["status"] == "no"]
    return yes, no


async def _cast_vote(tour_id: int, user_id: int, status: str) -> None:
    if status == "remove":
        await db.execute(
            "DELETE FROM tournament_members WHERE tour_id=? AND user_id=?",
            (tour_id, user_id))
    else:
        await db.execute(
            "INSERT INTO tournament_members(tour_id,user_id,status,ts) "
            "VALUES (?,?,?,?) ON CONFLICT(tour_id,user_id) DO UPDATE SET "
            "status=excluded.status, ts=excluded.ts",
            (tour_id, user_id, status, int(time.time())))


# --------------------------------------------------------------------------
# Карточка турнира
# --------------------------------------------------------------------------
def _names(people: list[dict], limit: int = NAMES_IN_CARD) -> str:
    if not people:
        return "пока никого"
    shown = ", ".join(html.escape(p["name"] or f"id{p['user_id']}")
                      for p in people[:limit])
    if len(people) > limit:
        shown += f" и ещё {len(people) - limit}"
    return shown


def card_text(t, yes: list[dict], no: list[dict]) -> str:
    title = html.escape(t["title"] or "Турнир")
    descr = html.escape((t["descr"] or "").strip())
    date_line = human_dt(int(t["start_ts"]), int(t["tz_offset"] or 3))
    head = (f"🏆 <b>ТУРНИР: {title}</b>\n"
            f"🗓 Старт: <b>{date_line}</b> ({_left(int(t['start_ts']))})\n\n")
    tail = (f"\n\n✅ <b>Участвуют ({len(yes)}):</b> {_names(yes)}\n"
            f"❌ <b>Не участвуют ({len(no)}):</b> {_names(no)}\n\n"
            f"👇 Отмечайтесь кнопками — состав виден всем.")
    room = 3900 - len(head) - len(tail)
    if len(descr) > room:
        descr = descr[:max(0, room)] + "…"
    return head + descr + tail


def _kb(tour_id: int, user_status: str = "") -> InlineKeyboardMarkup:
    """Кнопки участия; у отметившегося игрока его выбор подсвечен ☑️."""
    yes_label = "☑️ Участвую" if user_status == "yes" else "✅ Участвую"
    no_label = "☑️ Не участвую" if user_status == "no" else "❌ Не участвую"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=yes_label, callback_data=f"trn:y:{tour_id}"),
        InlineKeyboardButton(text=no_label, callback_data=f"trn:n:{tour_id}"),
    ]])


async def _target_chats(home_chat: int) -> list[int]:
    """Куда публикуем анонс: домашний чат + связанные группы клана."""
    ids = [home_chat]
    try:
        rows = await db.fetchall("SELECT chat_id FROM clan_groups")
        for r in rows:
            cid = int(r["chat_id"])
            if cid not in ids:
                ids.append(cid)
    except Exception:
        pass
    return ids


async def _post_card(bot: Bot, chat_id: int, t, *, register: bool = True
                     ) -> Optional[int]:
    """Шлёт видео (если есть) и карточку с кнопками в один чат."""
    yes, no = await _votes(int(t["id"]))
    if t["video_id"]:
        try:
            await bot.send_video(chat_id, t["video_id"],
                                 caption=f"🎬 Видео турнира «{html.escape(t['title'])}»")
        except Exception as e:
            log.warning("турник: видео в чат %s: %s", chat_id, e)
    try:
        m = await bot.send_message(
            chat_id, card_text(t, yes, no),
            reply_markup=_kb(int(t["id"])),
            disable_web_page_preview=True)
    except Exception as e:
        log.warning("турник: карточка в чат %s: %s", chat_id, e)
        return None
    if register:
        await db.execute(
            "INSERT OR IGNORE INTO tournament_posts(tour_id,chat_id,message_id) "
            "VALUES (?,?,?)", (int(t["id"]), chat_id, m.message_id))
    return m.message_id


async def _register_post(tour_id: int, chat_id: int, message_id: int) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO tournament_posts(tour_id,chat_id,message_id) "
        "VALUES (?,?,?)", (tour_id, chat_id, message_id))


async def _sync_posts(bot: Bot, tour_id: int, *, final: bool = False,
                      text_override: str = "") -> None:
    """Перерисовывает все копии анонса после голоса/статуса."""
    t = await db.fetchone("SELECT * FROM tournaments WHERE id=?", (tour_id,))
    if not t:
        return
    yes, no = await _votes(tour_id)
    text = text_override or card_text(t, yes, no)
    kb = None if final else _kb(tour_id)
    rows = await db.fetchall(
        "SELECT chat_id,message_id FROM tournament_posts WHERE tour_id=? LIMIT ?",
        (tour_id, MAX_POSTS_SYNC))
    dead: list[tuple[int, int]] = []
    for r in rows:
        try:
            await bot.edit_message_text(
                text, chat_id=int(r["chat_id"]), message_id=int(r["message_id"]),
                reply_markup=kb, disable_web_page_preview=True)
        except Exception as e:
            err = str(e).lower()
            if "not modified" in err:
                continue
            if "message to edit not found" in err or "chat not found" in err:
                dead.append((int(r["chat_id"]), int(r["message_id"])))
            log.warning("турник %s: правка %s/%s: %s", tour_id,
                        r["chat_id"], r["message_id"], e)
    for chat_id, mid in dead:
        await db.execute(
            "DELETE FROM tournament_posts WHERE tour_id=? AND chat_id=? AND message_id=?",
            (tour_id, chat_id, mid))


# --------------------------------------------------------------------------
# Созыв участников
# --------------------------------------------------------------------------
def _tags(people: list[dict]) -> str:
    return " ".join(members.summon_mention(p["user_id"], p.get("first_name"),
                                           p.get("username")) for p in people)


async def _tour_chat_posts(tour_id: int, home_chat: int) -> list[int]:
    rows = await db.fetchall(
        "SELECT DISTINCT chat_id FROM tournament_posts WHERE tour_id=?", (tour_id,))
    ids = [int(r["chat_id"]) for r in rows]
    if home_chat not in ids:
        ids.insert(0, home_chat)
    return ids


async def _summon(bot: Bot, t, *, reminder: bool) -> None:
    """Тегает отметившихся «Участвую» в каждом чате, где есть анонс.

    Состав проверяется через getChatMember: не тегаем тех, кто уже вышел
    из конкретного чата или попал в бан.
    """
    tour_id = int(t["id"])
    title = html.escape(t["title"] or "Турнир")
    date_line = human_dt(int(t["start_ts"]), int(t["tz_offset"] or 3))
    yes, no = await _votes(tour_id)
    if not yes:
        text = ("⏳ Через 30 минут ТУРНИР" if reminder else "🏆 ТУРНИР НАЧИНАЕТСЯ")
        for chat_id in await _tour_chat_posts(tour_id, int(t["chat_id"])):
            try:
                await bot.send_message(
                    chat_id,
                    f"{text} «{title}»\n🗓 {date_line}\n\nНа турнир пока никто не записался.")
            except Exception:
                pass
        return
    for chat_id in await _tour_chat_posts(tour_id, int(t["chat_id"])):
        people = await members.verified_members(bot, chat_id, yes)
        head = ("⏳ <b>Через 30 минут ТУРНИР!</b>\n"
                if reminder else "🏆 <b>ТУРНИР НАЧИНАЕТСЯ!</b>\n")
        what = (f"«{title}»\n🗓 {date_line}\nГотовьтесь, скоро в бой! Участников: "
                f"<b>{len(people)}</b>\n\n" if reminder else
                f"«{title}»\n🗓 {date_line}\n<b>Все заходим в игру!</b> "
                f"Участников: <b>{len(people)}</b>\n\n")
        try:
            await bot.send_message(chat_id, head + what,
                                   disable_web_page_preview=True)
        except Exception:
            continue
        for i in range(0, len(people), BATCH):
            try:
                await bot.send_message(chat_id, _tags(people[i:i + BATCH]),
                                       disable_web_page_preview=True)
            except Exception:
                pass
            await asyncio.sleep(0.6)


async def _finish(bot: Bot, t) -> None:
    """Турнир наступил: финальная правка анонсов + созыв участников."""
    tour_id = int(t["id"])
    await db.execute("UPDATE tournaments SET done=1, active=0 WHERE id=?", (tour_id,))
    yes, no = await _votes(tour_id)
    final_text = (
        f"🏆 <b>ТУРНИР «{html.escape(t['title'] or '')}» НАЧАЛСЯ!</b>\n"
        f"🗓 {human_dt(int(t['start_ts']), int(t['tz_offset'] or 3))}\n\n"
        f"✅ <b>Идут на турнир ({len(yes)}):</b> {_names(yes)}\n"
        f"❌ <b>Не идут ({len(no)}):</b> {_names(no)}\n\n"
        f"🎮 Участников призвали в игру — удачи всем!")
    await _sync_posts(bot, tour_id, final=True, text_override=final_text)
    await _summon(bot, t, reminder=False)


async def schedule_worker(bot: Bot) -> None:
    """Фоновая задача: напоминания и автосозыв по времени начала."""
    await _ensure()
    while True:
        try:
            await _tick(bot)
        except Exception as e:
            log.warning("турник worker: %s", e)
        await asyncio.sleep(20)


async def _tick(bot: Bot) -> None:
    now = int(time.time())
    rows = await db.fetchall(
        "SELECT * FROM tournaments WHERE active=1 AND reminded=0 "
        "AND start_ts>? AND start_ts<=?", (now, now + REMIND_BEFORE))
    for t in rows:
        await db.execute("UPDATE tournaments SET reminded=1 WHERE id=?",
                         (int(t["id"]),))
        try:
            await _summon(bot, t, reminder=True)
        except Exception as e:
            log.warning("турник %s: напоминание: %s", t["id"], e)
    rows = await db.fetchall(
        "SELECT * FROM tournaments WHERE active=1 AND done=0 AND start_ts<=?",
        (now,))
    for t in rows:
        try:
            await _finish(bot, t)
        except Exception as e:
            log.warning("турник %s: старт: %s", t["id"], e)


# --------------------------------------------------------------------------
# Команды
# --------------------------------------------------------------------------
@router.message(Cmd("турик", "турнир", section=S, usage="турик",
                    desc="Актуальный турнир: описание, видео и кнопки участия"))
async def cmd_tour(message: Message, bot: Bot, **kw):
    await _ensure()
    t = await _active_tournament(message.chat.id)
    if not t:
        return await message.reply(
            "🏆 Сейчас нет активных турниров.\n"
            "<i>Как появится — админы объявят, а вы увидите его по команде "
            "<code>турик</code>.</i>")
    await _post_card(bot, message.chat.id, t)


@router.message(Cmd("кто на турник", "состав на турник", "турик состав", section=S,
                    usage="кто на турник",
                    desc="Полный список: кто идёт на турнир, кто нет"))
async def cmd_tour_list(message: Message, bot: Bot, **kw):
    await _ensure()
    t = await _active_tournament(message.chat.id)
    if not t:
        return await message.reply("Активного турнира сейчас нет.")
    yes, no = await _votes(int(t["id"]))
    title = html.escape(t["title"] or "Турнир")

    def _listing(people: list[dict]) -> list[str]:
        rows = []
        for i, p in enumerate(people, 1):
            nm = p["name"] or f"id{p['user_id']}"
            rows.append(f"  {i}. {html.escape(nm)}")
        return rows

    lines = [f"🏆 <b>Состав на «{title}»</b>\n"]
    lines.append(f"✅ <b>Участвуют ({len(yes)}):</b>")
    lines += _listing(yes) or ["  пока никого"]
    lines.append(f"\n❌ <b>Не участвуют ({len(no)}):</b>")
    lines += _listing(no) or ["  пока никого"]
    lines.append(f"\n🗓 Старт: <b>{human_dt(int(t['start_ts']), int(t['tz_offset'] or 3))}</b>")
    await message.reply("\n".join(lines))


# --- Мастер создания ------------------------------------------------------
_wizard: dict[tuple[int, int], dict] = {}
_pending: dict[str, dict] = {}
_SKIP_WORDS = {"пропустить", "готово", "дальше", "нет", "без видео", "-"}
_CANCEL_WORDS = {"отмена", "отменить", "стоп", "cancel"}


def _wiz_key(message: Message) -> tuple[int, int]:
    return (message.chat.id, message.from_user.id if message.from_user else 0)


@router.message(Cmd("+турик", "создать турик", "новый турнир", "создать турнир",
                    section=S, rank=ADMIN_RANK, group_only=True,
                    usage="+турик",
                    desc="Создать турнир: название, дата, описание, правила, видео"))
async def cmd_create(message: Message, bot: Bot, **kw):
    await _ensure()
    if not await require(message, bot, ADMIN_RANK):
        return
    existing = await _active_tournament(message.chat.id)
    if existing:
        return await message.reply(
            f"🏆 В чате уже идёт сбор на «{html.escape(existing['title'])}» "
            f"({human_dt(int(existing['start_ts']), int(existing['tz_offset'] or 3))}).\n"
            f"Сначала завершите его: <code>-турик</code>")
    key = _wiz_key(message)
    _wizard[key] = {"step": "title", "t0": time.time(), "tz": await _chat_tz(message.chat.id)}
    # видео можно приложить сразу к команде — тогда шаг с видео пропустим
    if message.video and message.video.file_id:
        _wizard[key]["video_id"] = message.video.file_id
    await message.reply(
        "🏆 <b>Создание турника — шаг 1/4</b>\n\n"
        "Как назовём турнир? Напишите название одним сообщением.\n"
        "<i>В любой момент напишите «отмена», чтобы прервать.</i>")


async def _preview(message: Message, bot: Bot, w: dict) -> None:
    # ввод мастера закончен — дальше только кнопки подтверждения.
    _wizard.pop(_wiz_key(message), None)
    key = secrets.token_hex(4)
    _pending[key] = dict(w, owner=message.from_user.id if message.from_user else 0)
    date_line = human_dt(w["start_ts"], w["tz"])
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📢 Опубликовать", callback_data=f"trn:pub:{key}"),
        InlineKeyboardButton(text="🚫 Отмена", callback_data=f"trn:can:{key}"),
    ]])
    preview = (f"🏆 <b>Предпросмотр турника</b>\n\n"
               f"Название: <b>{html.escape(w['title'])}</b>\n"
               f"Старт: <b>{date_line}</b>\n"
               f"Видео: {'есть ✅' if w.get('video_id') else 'нет'}\n\n"
               f"{html.escape(w['descr'])[:1500]}")
    await message.reply(preview, reply_markup=kb, disable_web_page_preview=True)


async def _publish(bot: Bot, w: dict, by_id: int, home_chat: int) -> tuple[int, list[int]]:
    """Сохраняет турнир и рассылает анонс по целевым чатам."""
    await _ensure()
    now = int(time.time())
    await db.execute(
        "INSERT INTO tournaments(chat_id,title,descr,start_ts,tz_offset,video_id,"
        "created_by,active,done,reminded,ts) VALUES (?,?,?,?,?,?,?,1,0,0,?)",
        (home_chat, w["title"], w["descr"], w["start_ts"], w["tz"],
         w.get("video_id"), by_id, now))
    row = await db.fetchone("SELECT last_insert_rowid() id")
    tour_id = int(row["id"])
    t = await db.fetchone("SELECT * FROM tournaments WHERE id=?", (tour_id,))
    posted: list[int] = []
    for chat_id in await _target_chats(home_chat):
        if await _post_card(bot, chat_id, t) is not None:
            posted.append(chat_id)
    return tour_id, posted


class _WizardStep(Filter):
    async def __call__(self, message: Message) -> bool:
        w = _wizard.get(_wiz_key(message))
        if not w:
            return False
        if time.time() - w["t0"] > WIZARD_TTL:
            _wizard.pop(_wiz_key(message), None)
            return False
        return True


async def _wizard_input(message: Message, bot: Bot):
    key = _wiz_key(message)
    w = _wizard.get(key)
    if not w:
        return
    text = (message.text or message.caption or "").strip()
    if text.lower() in _CANCEL_WORDS:
        _wizard.pop(key, None)
        return await message.reply("🚫 Создание турника отменено.")
    if text and text[0] in "!./+-":
        return  # это команда — не перехватываем
    w["t0"] = time.time()
    step = w["step"]

    if step == "title":
        title = " ".join(text.split())[:80]
        if not title:
            return await message.reply("Пришлите название текстом (до 80 символов).")
        w["title"] = title
        w["step"] = "when"
        return await message.reply(
            "🗓 <b>Шаг 2/4 — дата и время начала</b>\n\n"
            "Напишите в формате <code>ДД.ММ ЧЧ:ММ</code> "
            "(год можно добавить: <code>25.08.2026 19:30</code>).\n"
            f"Часовой пояс чата: <b>UTC{w['tz']:+d}</b>")

    if step == "when":
        ts = parse_datetime(text, w["tz"])
        if ts is None:
            return await message.reply(
                "Не понял дату. Примеры: <code>25.08 19:30</code>, "
                "<code>30.08.2026 20:00</code>")
        if ts <= int(time.time()) + 60:
            return await message.reply("Дата уже в прошлом — дайте время в будущем.")
        w["start_ts"] = ts
        w["step"] = "descr"
        return await message.reply(
            "📝 <b>Шаг 3/4 — описание и правила</b>\n\n"
            f"Старт: <b>{human_dt(ts, w['tz'])}</b> ✅\n\n"
            "Теперь одним сообщением опишите турнир: что за игра/режим, "
            "формат (1х1, 2х2…), правила, призовые — всё, что важно игрокам.")

    if step == "descr":
        descr = text[:MAX_DESCR]
        if len(descr) < 10:
            return await message.reply(
                "Описание слишком короткое. Расскажите хотя бы парой предложений: "
                "режим, правила, призовые.")
        w["descr"] = descr
        if w.get("video_id"):
            return await _preview(message, bot, w)
        w["step"] = "video"
        return await message.reply(
            "🎬 <b>Шаг 4/4 — видео турнира</b>\n\n"
            "Пришлите видео (анонс, трейлер, правила в видеоформате) — "
            "или напишите <code>пропустить</code>.")

    if step == "video":
        if message.video and message.video.file_id:
            w["video_id"] = message.video.file_id
            return await _preview(message, bot, w)
        if text.lower() in _SKIP_WORDS:
            return await _preview(message, bot, w)
        return await message.reply(
            "Жду <b>видео</b> одним сообщением — или напишите <code>пропустить</code>.")


@router.message(Cmd("-турик", "удалить турик", "отменить турик", "отменить турнир",
                    section=S, rank=ADMIN_RANK, group_only=True,
                    usage="-турик",
                    desc="Отменить текущий турнир (созыва не будет)"))
async def cmd_cancel(message: Message, bot: Bot, **kw):
    await _ensure()
    if not await require(message, bot, ADMIN_RANK):
        return
    t = await _active_tournament(message.chat.id)
    if not t:
        return await message.reply("Активного турнира в этом чате нет.")
    tour_id = int(t["id"])
    await db.execute("UPDATE tournaments SET active=0, done=1 WHERE id=?", (tour_id,))
    yes, no = await _votes(tour_id)
    await _sync_posts(
        bot, tour_id, final=True,
        text_override=(f"🚫 <b>Турнир «{html.escape(t['title'])}» отменён.</b>\n\n"
                       f"Успели отметиться — участвовали: {len(yes)}, не шли: {len(no)}."))
    await message.reply(f"🚫 Турник «{html.escape(t['title'])}» отменён, "
                        f"анонсы обновлены.")


# Мастер создания регистрируем ПОСЛЕДНИМ из message-хэндлеров роутера:
# команды (турик / +турик / -турик) должны срабатывать раньше перехвата ввода.
router.message(_WizardStep())(_wizard_input)


# --------------------------------------------------------------------------
# Кнопки
# --------------------------------------------------------------------------
@router.callback_query(F.data.startswith("trn:"))
async def cb_tour(call: CallbackQuery, bot: Bot):
    await _ensure()
    parts = call.data.split(":", 2)
    if len(parts) < 3:
        return await call.answer()
    action, payload = parts[1], parts[2]

    if action == "can":
        _pending.pop(payload, None)
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return await call.answer("Отменено.", show_alert=False)

    if action == "pub":
        w = _pending.pop(payload, None)
        if not w:
            return await call.answer("Черновик устарел — создайте заново: +турик",
                                     show_alert=True)
        existing = await _active_tournament(call.message.chat.id)
        if existing:
            return await call.answer(
                f"Уже есть активный турник «{existing['title']}» — "
                f"сначала отмените его (-турик).", show_alert=True)
        tour_id, posted = await _publish(
            bot, w, w.get("owner", call.from_user.id if call.from_user else 0),
            call.message.chat.id)
        try:
            await call.message.edit_text(
                f"📢 <b>Турник опубликован!</b>\n\n"
                f"🏆 {html.escape(w['title'])}\n"
                f"🗓 {human_dt(w['start_ts'], w['tz'])}\n"
                f"📨 Анонс отправлен в чатов: <b>{len(posted)}</b>\n\n"
                f"Игроки смотрят его командой <code>турик</code> и отмечаются "
                f"кнопками. За 30 минут до начала бот напомнит, "
                f"а ровно в срок созовёт всех участников в игру.",
                reply_markup=None)
        except Exception:
            pass
        return await call.answer("Опубликовано 🏆")

    # --- голосование участвую / не участвую ---
    if not call.from_user:
        return await call.answer()
    try:
        tour_id = int(payload)
    except ValueError:
        return await call.answer()
    t = await db.fetchone("SELECT * FROM tournaments WHERE id=?", (tour_id,))
    if not t:
        return await call.answer("Турнир не найден.", show_alert=True)
    if not int(t["active"]) or int(t["done"]):
        return await call.answer("Этот турнир уже завершён 🏁", show_alert=True)

    want = "yes" if action == "y" else "no"
    cur = await db.fetchone(
        "SELECT status FROM tournament_members WHERE tour_id=? AND user_id=?",
        (tour_id, call.from_user.id))
    if cur and cur["status"] == want:
        # повторное нажатие той же кнопки снимает отметку
        await _cast_vote(tour_id, call.from_user.id, "remove")
        note = "Отметку снял — вы вне списков."
    else:
        await _cast_vote(tour_id, call.from_user.id, want)
        note = ("✅ Вы в составе на турник! Ждите созыва."
                if want == "yes" else "❌ Отметили, что вас не будет.")

    try:
        yes, no = await _votes(tour_id)
        my = await db.fetchone(
            "SELECT status FROM tournament_members WHERE tour_id=? AND user_id=?",
            (tour_id, call.from_user.id))
        await call.message.edit_text(
            card_text(t, yes, no),
            reply_markup=_kb(tour_id, my["status"] if my else ""),
            disable_web_page_preview=True)
    except Exception:
        pass
    asyncio.create_task(_sync_posts(bot, tour_id))
    return await call.answer(note, show_alert=True)


# --------------------------------------------------------------------------
# Служебное для тестов/интеграций
# --------------------------------------------------------------------------
async def shutdown() -> None:
    _wizard.clear()
    _pending.clear()
