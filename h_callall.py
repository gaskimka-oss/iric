"""Массовый созыв: «калл», «общий сбор» — тег всех с автоудалением."""
from __future__ import annotations

import asyncio
import html
import time

from aiogram import Bot, Router
from aiogram.types import Message

import db
from core_ranks import require
from core_registry import Cmd
from utils import mention_id

router = Router(name="callall")
S = 1

BATCH = 30          # упоминаний в одном сообщении
AUTODEL = 300       # 5 минут


async def _delete_later(bot: Bot, chat_id: int, ids: list[int], delay: int) -> None:
    await asyncio.sleep(delay)
    for mid in ids:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass


@router.message(Cmd("калл", "call", "общий сбор", "созыв всех",
                    section=S, rank=2, group_only=True,
                    usage="калл {причина}",
                    desc="Созвать всех участников (удалится через 5 мин)"))
async def cmd_call(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 2):
        return

    rows = await db.fetchall(
        "SELECT s.user_id, u.first_name FROM chat_stats s "
        "LEFT JOIN users u ON u.user_id = s.user_id "
        "WHERE s.chat_id=? ORDER BY s.last_seen DESC", (message.chat.id,))
    me = await bot.me()
    people = [(r["user_id"], r["first_name"]) for r in rows
              if r["user_id"] not in (me.id, message.from_user.id)]

    if not people:
        return await message.reply(
            "Пока не знаю участников этого чата.\n"
            "<i>Бот запоминает тех, кто писал после его добавления.</i>")

    reason = html.escape(args.strip()) if args.strip() else "общий сбор"
    sent_ids: list[int] = []

    head = await message.answer(
        f"📣 <b>ОБЩИЙ СБОР!</b>\n"
        f"Причина: {reason}\n"
        f"Созвал: {mention_id(message.from_user.id, message.from_user.first_name)}\n"
        f"Участников: <b>{len(people)}</b>\n\n"
        f"<i>Сообщения удалятся через 5 минут.</i>")
    sent_ids.append(head.message_id)

    for i in range(0, len(people), BATCH):
        chunk = people[i:i + BATCH]
        tags = " ".join(mention_id(uid, name) for uid, name in chunk)
        try:
            m = await message.answer(tags, disable_web_page_preview=True)
            sent_ids.append(m.message_id)
        except Exception:
            continue
        await asyncio.sleep(0.6)   # бережём лимиты Telegram

    try:
        sent_ids.append(message.message_id)
    except Exception:
        pass

    asyncio.create_task(_delete_later(bot, message.chat.id, sent_ids, AUTODEL))


@router.message(Cmd("калл модер", "сбор модерации", "созыв модеров", section=S, rank=1,
                    group_only=True, usage="калл модер {причина}",
                    desc="Созвать только модерацию (удалится через 5 мин)"))
async def cmd_call_mods(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 1):
        return
    rows = await db.fetchall(
        "SELECT r.user_id, u.first_name FROM ranks r "
        "LEFT JOIN users u ON u.user_id=r.user_id "
        "WHERE r.chat_id=? AND r.rank>=1 ORDER BY r.rank DESC", (message.chat.id,))
    if not rows:
        return await message.reply("В чате нет назначенных модераторов.")
    tags = " ".join(mention_id(r["user_id"], r["first_name"]) for r in rows[:50])
    m = await message.answer(
        f"📣 <b>Созыв модерации!</b>\n"
        f"Причина: {html.escape(args) if args else 'требуется внимание'}\n\n{tags}",
        disable_web_page_preview=True)
    asyncio.create_task(_delete_later(bot, message.chat.id,
                                      [m.message_id, message.message_id], AUTODEL))
