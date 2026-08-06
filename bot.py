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
import core_backup as backup
import core_docs as docs
import core_health as health
import core_nav as nav
import core_seed as seed
import core_keyboard as kbd
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
import core_clan_sync as clan_sync

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
log = logging.getLogger("irisbot")


async def keyboard_middleware(handler, event, data: dict):
    """Нажатие кнопки нижнего меню = обычная команда.

    Кнопка присылает текст вида «🍬 Баланс» — подменяем его на «баланс»,
    дальше сообщение идёт по обычному пути и его ловит нужный хэндлер.
    """
    text = getattr(event, "text", None)
    if text:
        cmd = kbd.resolve(text)
        if cmd:
            try:
                copy = event.model_copy(update={"text": cmd})
                bot = data.get("bot") or getattr(event, "bot", None)
                if bot is not None:
                    try:
                        copy = copy.as_(bot)
                    except Exception:
                        pass
                event = copy
            except Exception:
                pass
    return await handler(event, data)


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
        # Если мут/бан был задан по ещё неизвестному @username, применяем его
        # сразу, как только Telegram прислал событие с настоящим user_id.
        if user and not user.is_bot:
            try:
                import core_pending_punish as _pending
                await _pending.apply_for_user(data.get("bot"), chat.id, user)
            except Exception:
                pass
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


# Владелец бота. Дублируется здесь специально: если на хостинге почему-то
# остался старый config.py, бот всё равно поднимется, а не уйдёт в цикл
# падений с «OWNER_ID не задан».
FALLBACK_OWNER = 8412527198          # @Simba253


def _selfheal_config() -> None:
    """Чиним неполный config.py, чтобы бот не падал при частичной заливке."""
    if not getattr(config, "OWNER_ID", 0):
        config.OWNER_ID = FALLBACK_OWNER
        log.warning("OWNER_ID пуст — подставил владельца из кода: %s",
                    config.OWNER_ID)
    if not getattr(config, "DEFAULT_OWNER", 0):
        config.DEFAULT_OWNER = config.OWNER_ID or FALLBACK_OWNER
    admins = set(getattr(config, "ADMINS", []) or [])
    admins.add(config.OWNER_ID)
    config.ADMINS = sorted(admins - {0})
    if not getattr(config, "STORAGE_INFO", None):
        try:
            import core_storage as _st
            config.STORAGE_INFO = _st.INFO
            config.DATA_DIR = _st.DATA_DIR
            config.DB_PATH = _st.DB_FILE
            log.warning("config.py устарел — путь к базе взят из storage")
        except Exception:
            config.STORAGE_INFO = {"dir": str(getattr(config, "DB_PATH", "?")),
                                   "boots": 0, "db_existed": False,
                                   "persistent": False}


async def main() -> None:
    _selfheal_config()
    config.validate()

    info = config.STORAGE_INFO
    log.info("Хранилище: %s (запуск №%d, база на месте: %s)",
             info.get("dir"), info.get("boots", 0),
             "да" if info.get("db_existed") else "нет")

    bot = Bot(token=config.BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    # если база пустая (хостинг стёр диск) — тянем последнюю копию из Telegram
    try:
        if await backup.restore_if_needed(bot):
            log.info("✅ Настройки восстановлены из резервной копии")
    except Exception as e:
        log.warning("Восстановление пропущено: %s", e)

    await db.init()
    try:
        await seed.apply()
    except Exception as e:
        log.warning("seed: %s", e)

    dp = Dispatcher()
    dp.message.middleware(keyboard_middleware)
    dp.message.middleware(user_middleware)
    dp.callback_query.middleware(user_middleware)

    # порядок важен: passive — последним, он ловит любой текст
    # ДК применяется ко всем командным роутерам
    for r in (helpmenu.router, mod_ranks.router, mod_bans.router, chatset.router,
              dk.router, chatlock.router, fun.router, modules.router, rp.router,
              userinfo.router):
        r.message.middleware(access_middleware)

    dp.include_router(nav.router)
    dp.include_router(adminpanel.router)
    # До passive: отслеживает выходы/кики и связывает две группы клана.
    dp.include_router(clan_sync.router)
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
    asyncio.create_task(backup.worker(bot))
    await health.start()          # порт для healthcheck хостинга

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
        try:
            await asyncio.wait_for(backup.save(bot, "🔻 копия перед остановкой"), 25)
        except Exception as e:
            log.warning("копия перед остановкой не сделана: %s", e)
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        print(str(e) or "Остановлено.")
