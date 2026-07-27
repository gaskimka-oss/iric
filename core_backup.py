"""Резервные копии базы прямо в Telegram.

Зачем: на хостинге без постоянного диска (Volume) папка приложения
очищается при каждом деплое — база и все настройки пропадают.
Решение, которому не нужен ни диск, ни внешний сервис:

  • раз в N минут бот делает копию базы, жмёт её и отправляет
    документом в личку владельцу, а сообщение закрепляет;
  • при старте, если базы нет или она пустая, бот берёт файл
    из закреплённого сообщения и восстанавливает всё как было.

Закреплённое сообщение живёт в Telegram вечно, поэтому данные
переживают любой перезапуск, пересборку и переезд хостинга.
"""
from __future__ import annotations

import asyncio
import gzip
import logging
import os
import shutil
import sqlite3
import time
from pathlib import Path

from aiogram import Bot
from aiogram.types import BufferedInputFile

import config

log = logging.getLogger("irisbot.backup")

ARCHIVE_NAME = "iris_backup.db.gz"
TAG = "#iris_backup"

# как часто снимать копию (минуты)
INTERVAL_MIN = int(os.getenv("BACKUP_INTERVAL_MIN", "20") or 20)


def backup_chat() -> int:
    """Куда уходит файл базы. Всегда только владелец бота — @Simba253.

    Жёстко зашито специально: база — это личные данные участников,
    и в чужие руки она попасть не должна. Ни переменная окружения,
    ни другой администратор адрес не поменяют.
    """
    return int(config.DEFAULT_OWNER)


# ---------------------------------------------------------------- снимок
def _snapshot() -> bytes | None:
    """Согласованная копия базы (учитывает WAL) в виде gzip-байтов."""
    src = Path(config.DB_PATH)
    if not src.exists() or src.stat().st_size == 0:
        return None
    tmp = src.with_suffix(".backup.tmp")
    try:
        con = sqlite3.connect(str(src))
        dst = sqlite3.connect(str(tmp))
        with dst:
            con.backup(dst)
        dst.close()
        con.close()
        return gzip.compress(tmp.read_bytes(), 6)
    except Exception as e:
        log.warning("снимок базы не удался: %s", e)
        return None
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass


def _rows(path: Path) -> int:
    """Сколько всего значимых записей в базе (0 — база пустая)."""
    try:
        con = sqlite3.connect(str(path))
        n = 0
        for t in ("settings", "users", "staff", "ranks", "profiles"):
            try:
                n += con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except Exception:
                pass
        con.close()
        return n
    except Exception:
        return 0


def db_is_empty() -> bool:
    p = Path(config.DB_PATH)
    if not p.exists() or p.stat().st_size == 0:
        return True
    return _rows(p) == 0


# ---------------------------------------------------------------- выгрузка
async def save(bot: Bot, note: str = "") -> bool:
    chat = backup_chat()
    if not chat:
        return False
    blob = await asyncio.to_thread(_snapshot)
    if not blob:
        return False
    stamp = time.strftime("%d.%m.%Y %H:%M")
    caption = (f"💾 <b>Резервная копия базы</b>\n"
               f"🕒 {stamp}\n"
               f"📦 {len(blob) / 1024:.0f} КБ\n\n"
               f"Это сообщение закреплено — из него бот восстановит "
               f"настройки после перезапуска. Не удаляйте его.\n{TAG}")
    try:
        msg = await bot.send_document(
            chat, BufferedInputFile(blob, filename=ARCHIVE_NAME),
            caption=caption + (f"\n{note}" if note else ""),
            disable_notification=True)
    except Exception as e:
        log.warning("не отправил копию: %s", e)
        return False
    # закрепляем свежую, старую открепляем
    try:
        await bot.unpin_all_chat_messages(chat)
    except Exception:
        pass
    try:
        await bot.pin_chat_message(chat, msg.message_id,
                                   disable_notification=True)
    except Exception as e:
        log.warning("не закрепил копию: %s", e)
    log.info("резервная копия сохранена (%d КБ)", len(blob) / 1024)
    return True


# ------------------------------------------------------------ восстановление
async def restore_if_needed(bot: Bot) -> bool:
    """Вызывать ДО db.init(). True — база восстановлена из Telegram."""
    if not db_is_empty():
        return False
    chat = backup_chat()
    if not chat:
        return False
    try:
        info = await bot.get_chat(chat)
    except Exception as e:
        log.info("восстановление: чат недоступен (%s)", e)
        return False
    msg = getattr(info, "pinned_message", None)
    doc = getattr(msg, "document", None) if msg else None
    if not doc or ARCHIVE_NAME not in (doc.file_name or ""):
        log.info("восстановление: закреплённой копии нет — начинаю с чистой базы")
        return False
    try:
        f = await bot.get_file(doc.file_id)
        buf = await bot.download_file(f.file_path)
        raw = gzip.decompress(buf.read())
        dst = Path(config.DB_PATH)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            shutil.copy2(dst, dst.with_suffix(".old"))
        dst.write_bytes(raw)
        for suf in ("-wal", "-shm"):
            s = Path(str(dst) + suf)
            if s.exists():
                s.unlink()
        log.info("база восстановлена из Telegram (%d КБ, записей: %d)",
                 len(raw) / 1024, _rows(dst))
        return True
    except Exception as e:
        log.warning("восстановление не удалось: %s", e)
        return False


# ---------------------------------------------------------------- фоновая
async def worker(bot: Bot) -> None:
    await asyncio.sleep(90)          # дать боту прогреться
    while True:
        try:
            await save(bot)
        except Exception as e:
            log.warning("worker: %s", e)
        await asyncio.sleep(max(5, INTERVAL_MIN) * 60)
