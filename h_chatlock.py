"""Открытие/закрытие чата: +чат, -чат и автоматическое расписание."""
from __future__ import annotations

import html
import re
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.types import (CallbackQuery, ChatPermissions, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

import db
from core_ranks import require
from core_registry import Cmd

router = Router(name="chatlock")
S = 6

OPEN_PERMS = ChatPermissions(
    can_send_messages=True, can_send_audios=True, can_send_documents=True,
    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
    can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
    can_add_web_page_previews=True, can_invite_users=True, can_change_info=False,
    can_pin_messages=False)

CLOSED_PERMS = ChatPermissions(
    can_send_messages=False, can_send_audios=False, can_send_documents=False,
    can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
    can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False,
    can_add_web_page_previews=False, can_invite_users=False, can_change_info=False,
    can_pin_messages=False)

TIME_RE = re.compile(r"\b([01]?\d|2[0-3])[:.\s]?([0-5]\d)?\b")


def parse_time(text: str) -> str | None:
    """'23', '23:30', '9.05' -> 'HH:MM'."""
    t = (text or "").strip()
    if not t:
        return None
    m = TIME_RE.search(t)
    if not m:
        return None
    h = int(m.group(1))
    mnt = int(m.group(2) or 0)
    return f"{h:02d}:{mnt:02d}"


async def set_state(bot: Bot, chat_id: int, opened: bool) -> str | None:
    """Меняет права чата. Возвращает текст ошибки или None."""
    try:
        await bot.set_chat_permissions(chat_id, OPEN_PERMS if opened else CLOSED_PERMS)
    except Exception as e:
        return str(e)
    await db.set_setting(chat_id, "chat_open", "1" if opened else "0")
    return None


def _kb_schedule(kind: str) -> InlineKeyboardMarkup:
    """Быстрый выбор часа для авто-открытия/закрытия."""
    hours = ["06:00", "07:00", "08:00", "09:00", "10:00", "12:00",
             "20:00", "21:00", "22:00", "23:00", "00:00", "01:00"]
    rows, buf = [], []
    for h in hours:
        buf.append(InlineKeyboardButton(text=h, callback_data=f"sch:{kind}:{h}"))
        if len(buf) == 4:
            rows.append(buf); buf = []
    if buf:
        rows.append(buf)
    rows.append([InlineKeyboardButton(text="🚫 Отключить авто",
                                      callback_data=f"sch:{kind}:off")])
    rows.append([InlineKeyboardButton(text="📋 Показать расписание",
                                      callback_data="sch:show:-")])
    from core_nav import with_home
    return with_home(InlineKeyboardMarkup(inline_keyboard=rows))


async def _schedule_text(chat_id: int) -> str:
    row = await db.fetchone("SELECT * FROM chat_schedule WHERE chat_id=?", (chat_id,))
    is_open = await db.get_setting(chat_id, "chat_open", "1") == "1"
    state = "🟢 открыт" if is_open else "🔴 закрыт"
    if not row or not row["enabled"]:
        return (f"🕒 <b>Расписание чата</b>\n\nСейчас: {state}\n"
                f"Автоматика: <b>выключена</b>\n\n"
                f"<code>+чат 08:00</code> — открывать каждый день в 8:00\n"
                f"<code>-чат 23:00</code> — закрывать каждый день в 23:00")
    tz = row["tz_offset"]
    return (f"🕒 <b>Расписание чата</b>\n\n"
            f"Сейчас: {state}\n"
            f"🔓 Открытие: <b>{row['open_at'] or '—'}</b>\n"
            f"🔒 Закрытие: <b>{row['close_at'] or '—'}</b>\n"
            f"🌍 Пояс: UTC+{tz}\n\n"
            f"Изменить: <code>+чат 09:00</code> · <code>-чат 22:30</code>\n"
            f"Выключить: <code>+чат авто выкл</code>")


# ---------------- +ЧАТ ----------------
@router.message(Cmd("+чат", "+ чат", "открыть чат", "чат открыть", section=S, rank=2,
                    usage="+чат [время]", desc="Открыть чат или задать авто-открытие"))
async def cmd_open(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 2):
        return
    a = (args or "").strip().lower()

    if a in {"авто выкл", "авто off", "выкл авто", "автовыкл"}:
        await db.execute("UPDATE chat_schedule SET open_at=NULL WHERE chat_id=?",
                         (message.chat.id,))
        await _refresh_enabled(message.chat.id)
        return await message.reply("🚫 Авто-открытие отключено.")

    if a in {"меню", "расписание", "время", "?"}:
        return await message.reply(await _schedule_text(message.chat.id),
                                   reply_markup=_kb_schedule("open"))

    t = parse_time(a)
    if t:
        await _save_schedule(message.chat.id, open_at=t)
        return await message.reply(
            f"⏰ Чат будет <b>автоматически открываться</b> в <b>{t}</b> каждый день.\n\n"
            + await _schedule_text(message.chat.id))

    err = await set_state(bot, message.chat.id, True)
    if err:
        return await message.reply(f"⚠️ Не удалось открыть чат: {html.escape(err)}\n"
                                   f"Нужны права «Управление группой».")
    await message.reply("🟢 <b>Чат открыт</b> — участники снова могут писать.\n"
                        "<i>Задать авто-открытие: </i><code>+чат 08:00</code>")


# ---------------- −ЧАТ ----------------
@router.message(Cmd("-чат", "- чат", "закрыть чат", "чат закрыть", section=S, rank=2,
                    usage="-чат [время]", desc="Закрыть чат или задать авто-закрытие"))
async def cmd_close(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 2):
        return
    a = (args or "").strip().lower()

    if a in {"авто выкл", "авто off", "выкл авто", "автовыкл"}:
        await db.execute("UPDATE chat_schedule SET close_at=NULL WHERE chat_id=?",
                         (message.chat.id,))
        await _refresh_enabled(message.chat.id)
        return await message.reply("🚫 Авто-закрытие отключено.")

    if a in {"меню", "расписание", "время", "?"}:
        return await message.reply(await _schedule_text(message.chat.id),
                                   reply_markup=_kb_schedule("close"))

    t = parse_time(a)
    if t:
        await _save_schedule(message.chat.id, close_at=t)
        return await message.reply(
            f"⏰ Чат будет <b>автоматически закрываться</b> в <b>{t}</b> каждый день.\n\n"
            + await _schedule_text(message.chat.id))

    err = await set_state(bot, message.chat.id, False)
    if err:
        return await message.reply(f"⚠️ Не удалось закрыть чат: {html.escape(err)}\n"
                                   f"Нужны права «Управление группой».")
    await message.reply("🔴 <b>Чат закрыт</b> — писать могут только администраторы.\n"
                        "<i>Задать авто-закрытие: </i><code>-чат 23:00</code>")


@router.message(Cmd("расписание чата", "расписание", "авточат", section=S, rank=2,
                    usage="расписание чата", desc="Показать расписание открытия/закрытия"))
async def cmd_schedule(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 2):
        return
    await message.reply(await _schedule_text(message.chat.id),
                        reply_markup=_kb_schedule("open"))


@router.message(Cmd("часовой пояс", "пояс", "таймзона", section=S, rank=4,
                    usage="часовой пояс {число}", desc="Часовой пояс для расписания"))
async def cmd_tz(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 4):
        return
    a = (args or "").strip().replace("utc", "").replace("+", "")
    if not a.lstrip("-").isdigit():
        row = await db.fetchone("SELECT tz_offset FROM chat_schedule WHERE chat_id=?",
                                (message.chat.id,))
        cur = row["tz_offset"] if row else 3
        return await message.reply(f"🌍 Часовой пояс: <b>UTC+{cur}</b>\n"
                                   f"Изменить: <code>часовой пояс 3</code> (Москва)")
    tz = max(-12, min(int(a), 14))
    await _save_schedule(message.chat.id, tz=tz)
    await message.reply(f"🌍 Часовой пояс установлен: <b>UTC+{tz}</b>")


# ---------------- служебное ----------------
async def _save_schedule(chat_id: int, open_at: str | None = None,
                         close_at: str | None = None, tz: int | None = None) -> None:
    row = await db.fetchone("SELECT * FROM chat_schedule WHERE chat_id=?", (chat_id,))
    if not row:
        await db.execute(
            "INSERT INTO chat_schedule (chat_id, open_at, close_at, tz_offset, enabled) "
            "VALUES (?,?,?,?,1)", (chat_id, open_at, close_at, tz if tz is not None else 3))
    else:
        sets, params = [], []
        if open_at is not None:
            sets.append("open_at=?"); params.append(open_at)
        if close_at is not None:
            sets.append("close_at=?"); params.append(close_at)
        if tz is not None:
            sets.append("tz_offset=?"); params.append(tz)
        if sets:
            params.append(chat_id)
            await db.execute(f"UPDATE chat_schedule SET {', '.join(sets)} WHERE chat_id=?",
                             params)
    await _refresh_enabled(chat_id)


async def _refresh_enabled(chat_id: int) -> None:
    row = await db.fetchone("SELECT open_at, close_at FROM chat_schedule WHERE chat_id=?",
                            (chat_id,))
    if row:
        on = 1 if (row["open_at"] or row["close_at"]) else 0
        await db.execute("UPDATE chat_schedule SET enabled=? WHERE chat_id=?", (on, chat_id))


@router.callback_query(F.data.startswith("sch:"))
async def cb_schedule(call: CallbackQuery, bot: Bot):
    from core_ranks import get_rank
    from config import ADMINS, OWNER_ID
    from core_registry import MAX_RANK
    uid = call.from_user.id
    have = MAX_RANK if (uid == OWNER_ID or uid in ADMINS) else \
        await get_rank(call.message.chat.id, uid)
    if have < 2:
        return await call.answer("Нужен ранг ⭐⭐ Старший модератор", show_alert=True)

    _, kind, val = call.data.split(":", 2)
    if kind == "show":
        await call.message.edit_text(await _schedule_text(call.message.chat.id),
                                     reply_markup=_kb_schedule("open"))
        return await call.answer()
    if val == "off":
        col = "open_at" if kind == "open" else "close_at"
        await db.execute(f"UPDATE chat_schedule SET {col}=NULL WHERE chat_id=?",
                         (call.message.chat.id,))
        await _refresh_enabled(call.message.chat.id)
        await call.message.edit_text(await _schedule_text(call.message.chat.id),
                                     reply_markup=_kb_schedule(kind))
        return await call.answer("Авто отключено")

    if kind == "open":
        await _save_schedule(call.message.chat.id, open_at=val)
    else:
        await _save_schedule(call.message.chat.id, close_at=val)
    await call.message.edit_text(await _schedule_text(call.message.chat.id),
                                 reply_markup=_kb_schedule(kind))
    await call.answer(f"✅ {'Открытие' if kind == 'open' else 'Закрытие'} в {val}")


# ---------------- фоновый воркер ----------------
async def schedule_worker(bot: Bot) -> None:
    """Раз в минуту проверяет расписания и открывает/закрывает чаты."""
    import asyncio
    while True:
        try:
            rows = await db.fetchall("SELECT * FROM chat_schedule WHERE enabled=1")
            for r in rows:
                tz = timezone(timedelta(hours=r["tz_offset"] or 0))
                now = datetime.now(tz)
                hhmm = now.strftime("%H:%M")
                today = now.strftime("%Y-%m-%d")

                if r["open_at"] == hhmm and r["last_open"] != today:
                    if not await set_state(bot, r["chat_id"], True):
                        await db.execute(
                            "UPDATE chat_schedule SET last_open=? WHERE chat_id=?",
                            (today, r["chat_id"]))
                        try:
                            await bot.send_message(
                                r["chat_id"],
                                f"🟢 <b>Чат открыт</b> по расписанию ({hhmm})\n"
                                f"Доброе утро! ☀️")
                        except Exception:
                            pass

                if r["close_at"] == hhmm and r["last_close"] != today:
                    if not await set_state(bot, r["chat_id"], False):
                        await db.execute(
                            "UPDATE chat_schedule SET last_close=? WHERE chat_id=?",
                            (today, r["chat_id"]))
                        try:
                            await bot.send_message(
                                r["chat_id"],
                                f"🔴 <b>Чат закрыт</b> по расписанию ({hhmm})\n"
                                f"Спокойной ночи! 🌙 Откроется в "
                                f"{r['open_at'] or 'ручном режиме'}.")
                        except Exception:
                            pass
        except Exception:
            pass
        await asyncio.sleep(30)
