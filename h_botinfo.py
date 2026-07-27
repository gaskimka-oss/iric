"""Команда «бот»: статус онлайн/офлайн, пинг, аптайм, нагрузка."""
from __future__ import annotations

import html
import platform
import time

from aiogram import Bot, Router
from aiogram.types import Message

import db
from core_registry import REGISTRY, Cmd

router = Router(name="botinfo")
S = 32

START_TS = time.time()


def uptime_str() -> str:
    d = int(time.time() - START_TS)
    days, rem = divmod(d, 86400)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    if days:
        return f"{days} д {h} ч {m} мин"
    if h:
        return f"{h} ч {m} мин"
    if m:
        return f"{m} мин {sec} сек"
    return f"{sec} сек"


def ping_grade(ms: float) -> tuple[str, str]:
    """Оценка качества связи."""
    if ms < 150:
        return "🟢", "отличный"
    if ms < 400:
        return "🟡", "хороший"
    if ms < 900:
        return "🟠", "средний"
    return "🔴", "медленный"


async def measure_ping(bot: Bot) -> float:
    """Пинг до Telegram API в миллисекундах."""
    t0 = time.perf_counter()
    try:
        await bot.get_me()
    except Exception:
        return -1.0
    return (time.perf_counter() - t0) * 1000


async def bot_status_text(bot: Bot) -> str:
    me = await bot.me()
    ms = await measure_ping(bot)
    icon, grade = ping_grade(ms) if ms >= 0 else ("🔴", "нет связи")

    users = await db.fetchone("SELECT COUNT(*) c FROM users")
    chats = await db.fetchone("SELECT COUNT(*) c FROM chats")
    msgs = await db.fetchone("SELECT COALESCE(SUM(messages),0) c FROM chat_stats")

    ping_line = f"{ms:.0f} мс ({grade})" if ms >= 0 else "нет связи"
    return (
        f"🤖 <b>{html.escape(me.first_name)}</b>\n"
        f"@{me.username}\n\n"
        f"🟢 <b>Статус: онлайн</b>\n"
        f"{icon} Пинг: <b>{ping_line}</b>\n"
        f"⏱ Аптайм: <b>{uptime_str()}</b>\n\n"
        f"⚙️ Команд: <b>{len(REGISTRY)}</b>\n"
        f"👥 Пользователей: <b>{users['c']}</b>\n"
        f"💬 Чатов: <b>{chats['c']}</b>\n"
        f"✉️ Сообщений обработано: <b>{msgs['c']}</b>\n\n"
        f"🐍 Python {platform.python_version()}\n"
        f"📖 Все команды — <code>команды</code>")


@router.message(Cmd("бот", "статус", "бот статус", "status", section=S,
                    usage="бот", desc="Статус бота: онлайн, пинг, аптайм"))
async def cmd_bot(message: Message, bot: Bot, **kw):
    await message.reply(await bot_status_text(bot), disable_web_page_preview=True)


@router.message(Cmd("пинг", "ping", "задержка", section=S, usage="пинг",
                    desc="Проверить скорость отклика бота"))
async def cmd_ping(message: Message, bot: Bot, **kw):
    t0 = time.perf_counter()
    m = await message.reply("🏓 Измеряю…")
    reply_ms = (time.perf_counter() - t0) * 1000
    api_ms = await measure_ping(bot)
    icon, grade = ping_grade(api_ms) if api_ms >= 0 else ("🔴", "нет связи")
    try:
        await m.edit_text(
            f"🏓 <b>Понг!</b>\n\n"
            f"{icon} API Telegram: <b>{api_ms:.0f} мс</b> ({grade})\n"
            f"💬 Ответ в чат: <b>{reply_ms:.0f} мс</b>\n"
            f"⏱ Аптайм: <b>{uptime_str()}</b>")
    except Exception:
        pass


@router.message(Cmd("аптайм", "uptime", "время работы", section=S, usage="аптайм",
                    desc="Сколько бот работает без перезапуска"))
async def cmd_uptime(message: Message, **kw):
    await message.reply(
        f"⏱ Бот работает без перезапуска: <b>{uptime_str()}</b>\n"
        f"🕒 Запущен: {time.strftime('%d.%m.%Y %H:%M', time.localtime(START_TS))}")
