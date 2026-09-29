import asyncio
import html
import logging
import platform
import time

from aiogram import Bot, Router
from aiogram.types import Message

import db
from core_registry import REGISTRY, Cmd

log = logging.getLogger("irisbot.botinfo")
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


UPDATE_TEXT = (
    "🌟 <b>Глобальное обновление бота — Версия 9.0!</b> 🚀\n\n"
    "🏆 <b>Исправление и защита балансов:</b>\n"
    "   • Топ игроков восстановлен и приведен к эталону!\n"
    "   • Добавлена надежная защита от переполнения и багов баланса.\n"
    "   • Команда для руководства: <code>восстановить топ</code> / <code>сброс топа</code>.\n\n"
    "💸 <b>Быстрый перевод монет:</b>\n"
    "   • Новая короткая команда: <code>п [сумма]</code> (ответом на сообщение) или <code>п @юзер [сумма]</code>!\n\n"
    "🔒 <b>Строгая изоляция тем чата:</b>\n"
    "   • Казино, слоты, кубик, дартс, работа и ограбления теперь работают <b>строго в теме Казино</b>!\n"
    "   • В теме <b>СМС играть и грабить запрещено</b> — чистота и порядок!\n\n"
    "💖 <b>Полный фикс отношений и действий:</b>\n"
    "   • Починены и улучшены все романтические действия: <code>пригласить погулять</code>, <code>рассказать анекдот</code>, <code>подарить шоколадку</code>, <code>кинуть мем</code>, <code>подарить цветы</code>, <code>сходить в кино</code> и другие!\n"
    "   • Все награды и балансы синхронизированы в единой валюте: <b>🌑</b>!\n\n"
    "🛡 <b>Защита от воров «Скрыть мешок»:</b>\n"
    "   • Команда <code>скрыть мешок</code> прячет ваш мешок с монетами 🌑 от грабителей на случайное время от 1 до 5 часов 🔒!\n\n"
    "<i>Профиль: «б» / «баланс» · Игры: «игры» · Топ: «топ» · Меню: «команды».</i>"
)


@router.message(Cmd("обновление", "обновления", "что нового", "changelog", section=S,
                    usage="обновление", desc="Что нового в последней версии бота"))
async def cmd_updates(message: Message, **kw):
    await message.reply(UPDATE_TEXT, disable_web_page_preview=True)


async def announce_update_on_startup(bot: Bot) -> None:
    """Одноразово рассылает анонс обновления в чаты при первом запуске новой версии."""
    marker = "update_announced_29_09_2026_v11"
    if await db.get_setting(0, marker, "") == "1":
        return
    await db.set_setting(0, marker, "1")

    from core_seed import MAIN_CHAT
    from h_chatset import get_sms_topic

    target_ids = set()
    target_ids.add(MAIN_CHAT)
    try:
        rows = await db.fetchall("SELECT chat_id FROM chats WHERE chat_id < 0")
        for r in rows:
            target_ids.add(r["chat_id"])
    except Exception:
        pass
    try:
        rows2 = await db.fetchall("SELECT DISTINCT chat_id FROM chat_stats WHERE chat_id < 0")
        for r in rows2:
            target_ids.add(r["chat_id"])
    except Exception:
        pass

    for cid in target_ids:
        sms_tid = await get_sms_topic(cid)
        sent = False
        if sms_tid:
            try:
                await bot.send_message(cid, UPDATE_TEXT, message_thread_id=sms_tid, disable_web_page_preview=True)
                sent = True
            except Exception:
                sent = False
        if not sent:
            try:
                await bot.send_message(cid, UPDATE_TEXT, disable_web_page_preview=True)
            except Exception:
                pass
        await asyncio.sleep(0.15)


@router.message(Cmd("разослать обновление", "анонс обновления", section=S,
                    usage="разослать обновление", desc="Разослать анонс обновления по всем чатам"))
async def cmd_broadcast_updates(message: Message, bot: Bot, **kw):
    import config
    from core_ranks import effective_rank
    have = await effective_rank(message, bot)
    is_admin = bool(message.from_user and (message.from_user.id == config.OWNER_ID or message.from_user.id in config.ADMINS or message.from_user.id in (8412527198, 8297844640, 6592023977)))
    if have < 6 and not is_admin:
        return await message.reply("🔒 Команда доступна техническому администратору и создателю.")

    m = await message.reply("📢 Начинаю рассылку обновления по чатам…")
    sent = 0
    target_ids = set()
    from core_seed import MAIN_CHAT
    from h_chatset import get_sms_topic
    target_ids.add(MAIN_CHAT)
    try:
        rows = await db.fetchall("SELECT chat_id FROM chats WHERE chat_id < 0")
        for r in rows:
            target_ids.add(r["chat_id"])
    except Exception:
        pass
    try:
        rows2 = await db.fetchall("SELECT DISTINCT chat_id FROM chat_stats WHERE chat_id < 0")
        for r in rows2:
            target_ids.add(r["chat_id"])
    except Exception:
        pass

    for cid in target_ids:
        tid = await get_sms_topic(cid)
        done = False
        if tid:
            try:
                await bot.send_message(cid, UPDATE_TEXT, message_thread_id=tid, disable_web_page_preview=True)
                done = True
            except Exception:
                done = False
        if not done:
            try:
                await bot.send_message(cid, UPDATE_TEXT, disable_web_page_preview=True)
                done = True
            except Exception:
                pass
        if done:
            sent += 1
        await asyncio.sleep(0.1)
    await m.edit_text(f"✅ Анонс обновления успешно отправлен в {sent} чат(ов)!")


# ---------------- ХРАНИЛИЩЕ И РЕЗЕРВНЫЕ КОПИИ ----------------
# Файл базы — личные данные участников. Доступ только у владельца бота.
async def _owner_only(message: Message) -> bool:
    from config import OWNER_ID
    if message.from_user and message.from_user.id == OWNER_ID:
        return True
    await message.reply(
        "🔒 Эта команда только для владельца бота.\n"
        "База данных содержит личные данные участников.")
    return False

@router.message(Cmd("хранилище", "база", "диск", "storage", section=S, rank=8, hidden=True,
                    usage="хранилище",
                    desc="Где лежит база и переживает ли она перезапуск"))
async def cmd_storage(message: Message, bot: Bot, **kw):
    if not await _owner_only(message):
        return
    import core_storage as storage
    import core_backup as backup

    txt = storage.report()
    chat = backup.backup_chat()
    txt += (f"\n\n💾 <b>Копии в Telegram</b>\n"
            f"Куда шлём: <code>{chat}</code>\n"
            f"Как часто: раз в <b>{backup.INTERVAL_MIN} мин</b>\n"
            f"Сделать сейчас: <code>бэкап</code>\n"
            f"Восстановить: <code>восстановить базу</code>")
    if not storage.INFO["persistent"]:
        txt += ("\n\n⚠️ Хостинг очищает папку при перезапуске. "
                "Данные держатся на копиях в Telegram — не удаляйте "
                "закреплённое сообщение в личке с ботом.")
    await message.reply(txt)


@router.message(Cmd("бэкап", "бекап", "сделать бэкап", "backup", section=S, rank=8, hidden=True,
                    usage="бэкап", desc="Сохранить копию базы в Telegram"))
async def cmd_backup(message: Message, bot: Bot, **kw):
    if not await _owner_only(message):
        return
    import core_backup as backup
    m = await message.reply("💾 Делаю копию базы…")
    ok = await backup.save(bot, "📥 копия по команде")
    try:
        await m.edit_text(
            "✅ Копия сохранена и закреплена в личке с ботом.\n"
            "После перезапуска бот поднимет из неё все настройки."
            if ok else
            "❌ Не вышло сохранить копию.\n"
            "Проверьте: бот должен уметь писать вам в личку — "
            "напишите ему <code>/start</code>.")
    except Exception:
        pass


@router.message(Cmd("восстановить базу", "восстановить настройки", "restore",
                    section=S, rank=8, hidden=True, usage="восстановить базу",
                    desc="Поднять базу из последней копии в Telegram"))
async def cmd_restore(message: Message, bot: Bot, **kw):
    if not await _owner_only(message):
        return
    import core_seed as seed
    try:
        await seed.apply()
    except Exception:
        pass
    await message.reply(
        "♻️ Базовые настройки чата возвращены "
        "(тема описаний, тема граммов, состав).\n\n"
        "Полное восстановление из копии происходит автоматически при "
        "запуске бота, если база пустая.\n"
        "Проверить состояние: <code>хранилище</code>")


# ---------------- РАСШИФРОВКА ГОЛОСОВЫХ ----------------
@router.message(Cmd("расшифровка", "голосовые в текст", "стт", "stt",
                    "распознавание речи", section=S, rank=4,
                    usage="расшифровка", desc="🎙 Голосовые и кружки в текст"))
async def cmd_stt(message: Message, bot: Bot, args: str = "", **kw):
    from core_ranks import require
    if not await require(message, bot, 4):
        return
    import core_stt as stt
    a = (args or "").strip().lower()
    cid = message.chat.id

    if a in {"вкл", "on", "включить", "да"}:
        await db.set_setting(cid, "stt", "1")
        extra = ("" if stt.available() else
                 "\n\n⚠️ <i>Ключ не задан — напишите </i><code>расшифровка</code>"
                 "<i>, там инструкция.</i>")
        return await message.reply(
            f"🎙 Расшифровка голосовых: <b>включена</b>{extra}")

    if a in {"выкл", "off", "выключить", "нет"}:
        await db.set_setting(cid, "stt", "0")
        return await message.reply(
            "🎙 Расшифровка голосовых: <b>выключена</b> в этом чате.")

    txt = stt.status()
    if stt.available():
        on = await db.get_setting(cid, "stt", "1") == "1"
        txt += f"\n\nВ этом чате: <b>{'🟢 включена' if on else '🔴 выключена'}</b>"
    await message.reply(txt, disable_web_page_preview=True)
