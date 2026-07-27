"""Точка входа. Запуск: python bot.py"""
from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (TelegramBadRequest, TelegramConflictError,
                                TelegramUnauthorizedError)
from aiogram.types import BotCommand, Message

import config
import db
import core_docs as docs
from core_access import access_middleware
import h_chatlock as chatlock
import h_chatset as chatset
import h_dk as dk
import h_fun as fun
import h_helpmenu as helpmenu
import h_mod_bans as mod_bans
import h_mod_ranks as mod_ranks
import h_modules as modules
import h_passive as passive
import h_rp as rp
import h_start as start
import h_userinfo as userinfo
import h_botinfo as botinfo
import h_callall as callall
import h_grams as grams
import h_automod as automod
import h_adminpanel as adminpanel

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
log = logging.getLogger("irisbot")


async def user_middleware(handler, event, data: dict):
    """Регистрация пользователя/чата, глобальный бан, «тихий режим» чата."""
    user = getattr(event, "from_user", None)
    if user and not user.is_bot and user.id != 777000:
        row = await db.get_user(user.id)
        if row["banned"]:
            return
        await db.touch_user(user.id, user.username, user.first_name)
    chat = getattr(event, "chat", None)
    if chat is not None and chat.type in {"group", "supergroup"}:
        await db.register_chat(chat.id, chat.title)
        if await db.get_setting(chat.id, "silent") == "1":
            txt = (getattr(event, "text", "") or "").lower().lstrip("!./ ")
            if not txt.startswith(("включить чат", "проверка", "команды")):
                return
    return await handler(event, data)


async def timers_worker(bot: Bot) -> None:
    """Фоновая задача: срабатывание напоминаний."""
    while True:
        try:
            now = int(time.time())
            rows = await db.fetchall(
                "SELECT * FROM timers WHERE done=0 AND fire_at<=?", (now,))
            for r in rows:
                try:
                    await bot.send_message(
                        r["chat_id"],
                        f'⏰ Напоминание для <a href="tg://user?id={r["user_id"]}">вас</a>: '
                        f'{r["text"]}')
                except Exception:
                    pass
                await db.execute("UPDATE timers SET done=1 WHERE id=?", (r["id"],))
        except Exception as e:
            log.warning("timers: %s", e)
        await asyncio.sleep(20)


async def set_commands(bot: Bot) -> None:
    cmds = [
        # Telegram допускает в меню только латиницу/цифры/подчёркивание,
        # но сами команды в чате понимаются и по-русски.
        BotCommand(command="help", description="📖 Все команды бота (меню)"),
        BotCommand(command="profile", description="📝 Моя анкета"),
        BotCommand(command="balance", description="🍬 Баланс ирисок"),
        BotCommand(command="bonus", description="🎁 Ежедневный бонус"),
        BotCommand(command="cube", description="🎲 Кубик на ириски"),
        BotCommand(command="slots", description="🎰 Казино"),
        BotCommand(command="duel", description="⚔️ Дуэль"),
        BotCommand(command="top", description="🏆 Топ по ирискам"),
        BotCommand(command="stats", description="📊 Статистика"),
        BotCommand(command="check", description="🩺 Права бота в чате"),
        BotCommand(command="find", description="🔎 Поиск команды"),
    ]
    try:
        await bot.set_my_commands(cmds)
    except TelegramBadRequest as e:
        log.warning("меню команд: %s", e)


async def main() -> None:
    config.validate()
    await db.init()

    bot = Bot(token=config.BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.middleware(user_middleware)
    dp.callback_query.middleware(user_middleware)

    # порядок важен: passive — последним, он ловит любой текст
    # ДК применяется ко всем командным роутерам
    for r in (helpmenu.router, mod_ranks.router, mod_bans.router, chatset.router,
              dk.router, chatlock.router, fun.router, modules.router, rp.router,
              userinfo.router):
        r.message.middleware(access_middleware)

    dp.include_router(adminpanel.router)
    dp.include_router(start.router)
    dp.include_router(helpmenu.router)
    dp.include_router(dk.router)
    dp.include_router(chatlock.router)
    dp.include_router(callall.router)
    dp.include_router(mod_ranks.router)
    dp.include_router(mod_bans.router)
    dp.include_router(automod.router)
    dp.include_router(chatset.router)
    dp.include_router(fun.router)
    dp.include_router(modules.router)
    dp.include_router(grams.router)
    dp.include_router(rp.router)
    dp.include_router(botinfo.router)
    dp.include_router(userinfo.router)
    dp.include_router(passive.router)

    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError:
        await db.close(); await bot.session.close()
        raise SystemExit("❌ Токен неверный или отозван.\n"
                         "Проверьте переменную BOT_TOKEN "
                         "(в .env или в настройках хостинга).")

    from core_registry import REGISTRY
    log.info("Запущен @%s | команд: %d | владелец: %s",
             me.username, len(REGISTRY), config.OWNER_ID)

    # публикация справки (в отдельном потоке, чтобы не блокировать loop)
    try:
        st = await asyncio.to_thread(docs.publish)
        log.info("Справка: %s", st.get("url"))
    except Exception as e:
        log.warning("Не удалось опубликовать справку: %s", e)

    await set_commands(bot)
    asyncio.create_task(timers_worker(bot))
    asyncio.create_task(chatlock.schedule_worker(bot))

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except TelegramConflictError:
        log.error("❌ Бот уже запущен где-то ещё (другой сервер или локально). "
                  "Остановите второй экземпляр — Telegram разрешает только один.")
    except asyncio.CancelledError:
        log.info("Получен сигнал остановки — завершаюсь.")
    finally:
        log.info("Закрываю соединения…")
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        print(str(e) or "Остановлено.")
