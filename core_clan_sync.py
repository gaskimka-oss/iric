"""Связка админской и клановой групп: сквозной бан при выходе.

Telegram Bot API не умеет получать chat_id приватной группы по invite-ссылке,
поэтому владелец один раз назначает роли командами внутри самих групп.
"""
from __future__ import annotations

import html
import logging
import time

from aiogram import Bot, Router
from aiogram.types import ChatMemberUpdated, Message

import db
from config import OWNER_ID
from core_punish import log_punish
from core_ranks import effective_rank
from core_registry import MAX_RANK, Cmd
from utils import mention_id

router = Router(name="clan_sync")
log = logging.getLogger("irisbot.clan_sync")

LEAVE_REASON = "Лив с клана"
ROLE_NAMES = {"admin": "админская", "clan": "клановая"}
PRESENT = {"member", "administrator", "creator"}


def _status(member) -> str:
    value = str(getattr(member, "status", "")).lower()
    return value.rsplit(".", 1)[-1]


def _is_present(member) -> bool:
    status = _status(member)
    if status in PRESENT:
        return True
    if status == "restricted":
        return bool(getattr(member, "is_member", False))
    return False


async def _can_configure(message: Message, bot: Bot) -> bool:
    if message.from_user and message.from_user.id == OWNER_ID:
        return True
    return await effective_rank(message, bot) >= MAX_RANK


async def _set_role(message: Message, bot: Bot, role: str) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return await message.reply("Эту команду нужно выполнить внутри нужной группы.")
    if not await _can_configure(message, bot):
        return await message.reply("⛔️ Связывать группы может только лидер или владелец бота.")

    # Один чат не может одновременно быть обеими группами.
    other = "clan" if role == "admin" else "admin"
    await db.execute("DELETE FROM clan_groups WHERE role=? AND chat_id=?",
                     (other, message.chat.id))
    await db.execute(
        "INSERT INTO clan_groups(role,chat_id,title,updated_by,ts) VALUES (?,?,?,?,?) "
        "ON CONFLICT(role) DO UPDATE SET chat_id=excluded.chat_id, "
        "title=excluded.title, updated_by=excluded.updated_by, ts=excluded.ts",
        (role, message.chat.id, message.chat.title or "", message.from_user.id,
         int(time.time())))

    rows = await db.fetchall("SELECT role,chat_id,title FROM clan_groups ORDER BY role")
    lines = ["🔗 <b>Связка групп</b>"]
    by_role = {r["role"]: r for r in rows}
    for key in ("admin", "clan"):
        row = by_role.get(key)
        if row:
            lines.append(f"✅ {ROLE_NAMES[key].capitalize()}: "
                         f"<b>{html.escape(row['title'] or str(row['chat_id']))}</b> "
                         f"(<code>{row['chat_id']}</code>)")
        else:
            lines.append(f"❌ {ROLE_NAMES[key].capitalize()}: не назначена")
    if len(by_role) == 2:
        lines.append("\n🛡 Сквозной бан включён: выход, кик или бан в одной группе "
                     "приведёт к бану в обеих.")
    else:
        lines.append("\nОсталось назначить вторую группу.")
    await message.reply("\n".join(lines))


@router.message(Cmd("назначить админ группу", "это админ группа", section=6,
                    rank=8, group_only=True,
                    usage="назначить админ группу",
                    desc="Назначить текущий чат админской группой клана"))
async def set_admin_group(message: Message, bot: Bot, **kw):
    await _set_role(message, bot, "admin")


@router.message(Cmd("назначить клан группу", "это клан группа", section=6,
                    rank=8, group_only=True,
                    usage="назначить клан группу",
                    desc="Назначить текущий чат основной группой клана"))
async def set_clan_group(message: Message, bot: Bot, **kw):
    await _set_role(message, bot, "clan")


@router.message(Cmd("связка групп", "группы клана", section=6, rank=8,
                    group_only=True, usage="связка групп",
                    desc="Показать админскую и клановую группы"))
async def show_groups(message: Message, bot: Bot, **kw):
    if not await _can_configure(message, bot):
        return await message.reply("⛔️ Команда доступна лидеру.")
    rows = await db.fetchall("SELECT role,chat_id,title FROM clan_groups ORDER BY role")
    if not rows:
        return await message.reply(
            "Группы ещё не связаны.\n"
            "В админской: <code>назначить админ группу</code>\n"
            "В основной: <code>назначить клан группу</code>")
    lines = ["🔗 <b>Связанные группы</b>"]
    for row in rows:
        lines.append(f"• {ROLE_NAMES.get(row['role'], row['role']).capitalize()}: "
                     f"{html.escape(row['title'] or 'без названия')} "
                     f"(<code>{row['chat_id']}</code>)")
    await message.reply("\n".join(lines))


async def _cross_ban(bot: Bot, user_id: int, user_name: str, source_chat: int,
                     trigger: str) -> None:
    groups = await db.fetchall("SELECT role,chat_id,title FROM clan_groups")
    ids = {int(row["chat_id"]) for row in groups}
    if source_chat not in ids or len(ids) < 2:
        return

    successes: list[int] = []
    failures: list[tuple[int, str]] = []
    now = int(time.time())
    for chat_id in ids:
        try:
            await bot.ban_chat_member(chat_id, user_id)
            successes.append(chat_id)
            await db.execute(
                "INSERT INTO bans(chat_id,user_id,reason,by_id,until,ts) VALUES (?,?,?,?,0,?) "
                "ON CONFLICT(chat_id,user_id) DO UPDATE SET reason=excluded.reason, "
                "by_id=excluded.by_id, until=0, ts=excluded.ts",
                (chat_id, user_id, LEAVE_REASON, 0, now))
            active = await db.fetchone(
                "SELECT id FROM punishments WHERE chat_id=? AND user_id=? "
                "AND kind='ban' AND active=1", (chat_id, user_id))
            if not active:
                await log_punish(chat_id, user_id, "ban", LEAVE_REASON, 0, 0)
        except Exception as exc:
            failures.append((chat_id, str(exc)))

    # Сообщаем в исходную группу. Если писать туда нельзя — пробуем вторую.
    trigger_name = {"left": "вышел", "kicked": "был исключён/забанен"}.get(
        trigger, "покинул группу")
    text = (f"🔨 <b>Сквозной бан</b>\n"
            f"👤 {mention_id(user_id, user_name)}\n"
            f"Событие: пользователь {trigger_name}\n"
            f"📝 Причина: <b>{LEAVE_REASON}</b>\n"
            f"✅ Забанен в группах: <b>{len(successes)}/{len(ids)}</b>")
    if failures:
        text += "\n⚠️ Не удалось забанить в части групп. Проверьте, что бот имеет " \
                "право блокировать участников и цель не является Telegram-админом."
    for chat_id in (source_chat, *[x for x in ids if x != source_chat]):
        try:
            await bot.send_message(chat_id, text)
            break
        except Exception:
            continue
    for chat_id, error in failures:
        log.warning("cross-ban user=%s chat=%s: %s", user_id, chat_id, error[:180])


@router.chat_member()
async def on_member_changed(event: ChatMemberUpdated, bot: Bot):
    """Запоминает ID/username и ловит выход, кик или бан участника."""
    user = event.new_chat_member.user
    if not user or user.is_bot:
        return
    await db.touch_user(user.id, user.username, user.first_name)
    try:
        import core_pending_punish as pending
        await pending.apply_for_user(bot, event.chat.id, user)
    except Exception:
        pass

    was_here = _is_present(event.old_chat_member)
    is_here = _is_present(event.new_chat_member)
    if not was_here or is_here:
        return

    # Два события от одновременного бана в связанных группах могут прийти почти
    # вместе. Короткий замок не даёт повторно логировать одно действие.
    lock = await db.fetchone(
        "SELECT ts FROM clan_crossban_lock WHERE user_id=?", (user.id,))
    now = int(time.time())
    if lock and now - int(lock["ts"]) < 15:
        return
    await db.execute(
        "INSERT INTO clan_crossban_lock(user_id,ts) VALUES (?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET ts=excluded.ts", (user.id, now))
    await _cross_ban(bot, user.id, user.first_name or user.username or str(user.id),
                     event.chat.id, _status(event.new_chat_member))
