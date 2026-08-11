"""Массовый созыв: только текущие участники, с автоудалением."""
from __future__ import annotations

import asyncio
import html

from aiogram import Bot, Router
from aiogram.types import Message

import db
import core_members as members
from core_ranks import require
from core_registry import Cmd
from utils import mention_id

router = Router(name="callall")
S = 1

BATCH = 25          # упоминаний в одном сообщении
AUTODEL = 300       # 5 минут


async def _delete_later(bot: Bot, chat_id: int, ids: list[int], delay: int) -> None:
    await asyncio.sleep(delay)
    for mid in ids:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass


def _tags(people: list[dict]) -> str:
    return " ".join(
        members.summon_mention(p["user_id"], p.get("first_name"),
                               p.get("username"))
        for p in people)


async def _verified_mods(message: Message, bot: Bot) -> list[dict]:
    rows = await db.fetchall(
        "SELECT r.user_id,u.first_name,u.username,r.rank,"
        "COALESCE(s.last_seen,0) last_seen FROM ranks r "
        "LEFT JOIN users u ON u.user_id=r.user_id "
        "LEFT JOIN chat_stats s ON s.chat_id=r.chat_id AND s.user_id=r.user_id "
        "WHERE r.chat_id=? AND r.rank>=1 ORDER BY r.rank DESC,last_seen DESC",
        (message.chat.id,))
    me = await bot.me()
    return await members.verified_members(
        bot, message.chat.id, rows, exclude=(me.id, message.from_user.id))


@router.message(Cmd("калл", "call", "общий сбор", "созыв всех",
                    section=S, rank=2, group_only=True,
                    usage="калл {причина}",
                    desc="Созвать текущих участников (удалится через 5 мин)"))
async def cmd_call(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 2):
        return

    rows = await members.known_chat_rows(message.chat.id)
    me = await bot.me()
    people = await members.verified_members(
        bot, message.chat.id, rows, exclude=(me.id, message.from_user.id))

    if not people:
        return await message.reply(
            "Не нашёл подтверждённых участников для созыва.\n"
            "<i>Бот запоминает людей по сообщениям и событиям входа; "
            "ушедшие и забаненные автоматически исключаются.</i>")

    reason = html.escape(args.strip()) if args.strip() else "общий сбор"
    sent_ids: list[int] = []

    head = await message.answer(
        f"📣 <b>ОБЩИЙ СБОР!</b>\n"
        f"Причина: {reason}\n"
        f"Созвал: {mention_id(message.from_user.id, message.from_user.first_name)}\n"
        f"Текущих участников: <b>{len(people)}</b>\n\n"
        f"<i>Ушедшие и забаненные не упоминаются. "
        f"Сообщения удалятся через 5 минут.</i>")
    sent_ids.append(head.message_id)

    for i in range(0, len(people), BATCH):
        chunk = people[i:i + BATCH]
        try:
            m = await message.answer(_tags(chunk), disable_web_page_preview=True)
            sent_ids.append(m.message_id)
        except Exception:
            continue
        await asyncio.sleep(0.6)   # бережём лимиты Telegram

    sent_ids.append(message.message_id)
    asyncio.create_task(_delete_later(bot, message.chat.id, sent_ids, AUTODEL))


@router.message(Cmd("калл модер", "сбор модерации", "созыв модеров", section=S, rank=1,
                    group_only=True, usage="калл модер {причина}",
                    desc="Созвать текущую модерацию (удалится через 5 мин)"))
async def cmd_call_mods(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 1):
        return
    people = await _verified_mods(message, bot)
    if not people:
        return await message.reply("В чате нет присутствующих модераторов.")
    m = await message.answer(
        f"📣 <b>Созыв модерации!</b>\n"
        f"Причина: {html.escape(args) if args else 'требуется внимание'}\n\n"
        f"{_tags(people[:50])}",
        disable_web_page_preview=True)
    asyncio.create_task(_delete_later(bot, message.chat.id,
                                      [m.message_id, message.message_id], AUTODEL))
