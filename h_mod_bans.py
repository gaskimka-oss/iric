"""Разделы 2 и 5: баны, муты, предупреждения, списки, чистка чата.

Все наказания требуют причину (и срок для мута/бана), пишутся в журнал
punishments и защищают Лидера клана (7 ранг) от любого воздействия.
"""
from __future__ import annotations

import html
import re
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Router
from aiogram.types import ChatPermissions, Message

import db
from config import WARN_LIMIT, WARN_MUTE_HOURS
import core_modlog as modlog
from core_punish import (KIND_NAMES, check_reason, explain_error, guard_target,
                         lift_punish, log_punish, render_history, render_list,
                         strip_forever)
from core_ranks import effective_rank, get_rank, rank_label, require, set_rank
from core_registry import Cmd
from core_resolve import human_period, parse_period, resolve_target
from utils import mention_id

router = Router(name="mod_bans")
S_BAN, S_CLEAN = 2, 5

MUTE_OFF = ChatPermissions(can_send_messages=False, can_send_audios=False,
                           can_send_documents=False, can_send_photos=False,
                           can_send_videos=False, can_send_video_notes=False,
                           can_send_voice_notes=False, can_send_polls=False,
                           can_send_other_messages=False, can_add_web_page_previews=False)
MUTE_ON = ChatPermissions(can_send_messages=True, can_send_audios=True,
                          can_send_documents=True, can_send_photos=True,
                          can_send_videos=True, can_send_video_notes=True,
                          can_send_voice_notes=True, can_send_polls=True,
                          can_send_other_messages=True, can_add_web_page_previews=True)

# Лимит предупреждений на текущей должности. После достижения человек
# понижается на одну ступень, а счётчик для новой ступени начинается с нуля.
RANK_WARN_LIMITS = {1: 2, 2: 3, 3: 4, 4: 5, 5: 6}
WARN_IMMUNE_FROM = 6
USERNAME_RE = re.compile(r"@([A-Za-z0-9_]{4,32})")


async def _queue_unknown_target(message: Message, args: str, kind: str) -> bool:
    """Сохраняет мут/бан по нику до момента, когда станет известен user_id."""
    match = USERNAME_RE.search(args or "")
    if not match:
        return False
    username = match.group(1)
    rest = ((args or "")[:match.start()] + (args or "")[match.end():]).strip()
    seconds, reason = parse_period(rest)
    reason, forever = strip_forever(reason)
    if forever:
        seconds = 0
    reason = reason.strip() or "Без причины"
    import core_pending_punish as pending
    await pending.schedule(message.chat.id, username, kind, reason, seconds,
                           message.from_user.id if message.from_user else 0)
    action = "мут" if kind == "mute" else "бан"
    await message.reply(
        f"⏳ <b>{action.capitalize()} сохранён для @{html.escape(username)}</b>\n\n"
        "Telegram пока не передал его числовой ID. Наказание автоматически "
        "применится при его следующем сообщении, входе или событии участника.\n"
        f"⏱ Срок: <b>{human_period(seconds)}</b>\n"
        f"📝 Причина: {html.escape(reason)}\n\n"
        "Для немедленного применения можно указать числовой ID или ответить "
        "командой на сообщение пользователя.")
    return True


# ---------------- МУТ ----------------
@router.message(Cmd("мут", "замутить", "ro", "молчать", section=S_BAN, rank=1,
                    usage="мут {ссылка} {время} {причина}",
                    desc="Запретить писать (нужны срок и причина)"))
async def cmd_mute(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, rest = await resolve_target(message, args, bot)
    if not uid:
        if await _queue_unknown_target(message, args, "mute"):
            return
        return await message.reply("Укажите пользователя: реплаем, @ником или id.")
    err = await guard_target(message, bot, uid, "замутить")
    if err:
        return await message.reply(err)
    secs, reason = parse_period(rest)
    reason, forever = strip_forever(reason)
    if forever:
        secs = 0
    # Точная команда «мут @user» тоже работает: бессрочно, без причины.
    reason = reason.strip() or "Без причины"
    if not await check_reason(message, "mute", reason, secs or 1):
        return

    until = datetime.now(timezone.utc) + timedelta(seconds=secs or 366 * 86400)
    try:
        await bot.restrict_chat_member(message.chat.id, uid, MUTE_OFF, until_date=until)
    except Exception as e:
        return await message.reply(explain_error(e, "замутить"))
    pid = await log_punish(message.chat.id, uid, "mute", reason, secs,
                           message.from_user.id if message.from_user else 0)
    await db.execute(
        "INSERT INTO mutes (chat_id,user_id,reason,by_id,until,ts) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(chat_id,user_id) DO UPDATE SET reason=excluded.reason, until=excluded.until",
        (message.chat.id, uid, reason, message.from_user.id if message.from_user else 0,
         int(time.time()) + secs if secs else 0, int(time.time())))
    ctx = await modlog.build_context(message.chat.id, uid)
    await modlog.write(message.chat.id, pid, uid, name,
                       message.from_user.id, message.from_user.first_name,
                       "mute", reason, secs, "админ", ctx, bot=bot)
    sent = await message.reply(
        f"🔇 <b>Мут выдан</b>\n"
        f"👤 {mention_id(uid, name)}\n"
        f"⏱ Срок: <b>{human_period(secs)}</b>\n"
        f"📝 Причина: {html.escape(reason)}\n"
        f"👮 Модератор: {mention_id(message.from_user.id, message.from_user.first_name)}\n"
        f"<code>#{pid}</code>")
    modlog.schedule_autodelete(bot, sent)


@router.message(Cmd("размут", "размутить", "unmute", section=S_BAN, rank=1,
                    usage="размут {ссылка}", desc="Снять мут"))
async def cmd_unmute(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 1):
        return
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя.")
    try:
        await bot.restrict_chat_member(message.chat.id, uid, MUTE_ON)
    except Exception as e:
        return await message.reply(explain_error(e, "размутить"))
    await db.execute("DELETE FROM mutes WHERE chat_id=? AND user_id=?", (message.chat.id, uid))
    await lift_punish(message.chat.id, uid, "mute", message.from_user.id)
    await message.reply(f"🔊 {mention_id(uid, name)} снова может писать.")


@router.message(Cmd("мутлист", "мут лист", "список мутов", "муты", section=S_BAN, rank=1,
                    usage="мутлист", desc="Список замученных с причинами"))
async def cmd_mutelist(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 1):
        return
    await message.reply(await render_list(message.chat.id, "mute"),
                        disable_web_page_preview=True)


# ---------------- БАН ----------------
@router.message(Cmd("бан", "забанить", "ban", section=S_BAN, rank=2,
                    usage="бан {ссылка} [время] {причина}",
                    desc="Заблокировать; без срока — навсегда"))
async def cmd_ban(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, rest = await resolve_target(message, args, bot)
    if not uid:
        if await _queue_unknown_target(message, args, "ban"):
            return
        return await message.reply("Укажите пользователя: реплаем, @ником или id.")
    err = await guard_target(message, bot, uid, "забанить")
    if err:
        return await message.reply(err)
    secs, reason = parse_period(rest)
    reason, forever = strip_forever(reason)
    if forever:
        secs = 0
    # «бан @user» означает бессрочный бан с причиной по умолчанию.
    reason = reason.strip() or "Без причины"
    if not await check_reason(message, "ban", reason, secs or 1):
        return

    until = (datetime.now(timezone.utc) + timedelta(seconds=secs)) if secs else None
    try:
        await bot.ban_chat_member(message.chat.id, uid, until_date=until)
    except Exception as e:
        return await message.reply(explain_error(e, "забанить"))
    pid = await log_punish(message.chat.id, uid, "ban", reason, secs,
                           message.from_user.id if message.from_user else 0)
    await db.execute(
        "INSERT INTO bans (chat_id,user_id,reason,by_id,until,ts) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(chat_id,user_id) DO UPDATE SET reason=excluded.reason, until=excluded.until",
        (message.chat.id, uid, reason, message.from_user.id if message.from_user else 0,
         int(time.time()) + secs if secs else 0, int(time.time())))
    ctx = await modlog.build_context(message.chat.id, uid)
    await modlog.write(message.chat.id, pid, uid, name,
                       message.from_user.id, message.from_user.first_name,
                       "ban", reason, secs, "админ", ctx, bot=bot)
    sent = await message.reply(
        f"🔨 <b>Бан выдан</b>\n"
        f"👤 {mention_id(uid, name)}\n"
        f"⏱ Срок: <b>{human_period(secs)}</b>\n"
        f"📝 Причина: {html.escape(reason)}\n"
        f"👮 Модератор: {mention_id(message.from_user.id, message.from_user.first_name)}\n"
        f"<code>#{pid}</code>")
    modlog.schedule_autodelete(bot, sent)


@router.message(Cmd("разбан", "разбанить", "unban", section=S_BAN, rank=2,
                    usage="разбан {ссылка}", desc="Снять блокировку"))
async def cmd_unban(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 2):
        return
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя или id.")
    try:
        await bot.unban_chat_member(message.chat.id, uid, only_if_banned=True)
    except Exception as e:
        return await message.reply(explain_error(e, "разбанить"))
    await db.execute("DELETE FROM bans WHERE chat_id=? AND user_id=?", (message.chat.id, uid))
    await lift_punish(message.chat.id, uid, "ban", message.from_user.id)
    await message.reply(f"✅ {mention_id(uid, name)} разблокирован.")


@router.message(Cmd("банлист", "бан лист", "список банов", "баны", section=S_BAN, rank=1,
                    usage="банлист", desc="Список забаненных с причинами"))
async def cmd_banlist(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 1):
        return
    await message.reply(await render_list(message.chat.id, "ban"),
                        disable_web_page_preview=True)


@router.message(Cmd("кик", "кикнуть", "выгнать", "kick", section=S_BAN, rank=1,
                    usage="кик {ссылка} {причина}", desc="Исключить из чата"))
async def cmd_kick(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, rest = await resolve_target(message, args, bot)
    err = await guard_target(message, bot, uid, "кикнуть")
    if err:
        return await message.reply(err)
    if not await check_reason(message, "kick", rest):
        return
    try:
        await bot.ban_chat_member(message.chat.id, uid)
        await bot.unban_chat_member(message.chat.id, uid)
    except Exception as e:
        return await message.reply(explain_error(e, "кикнуть"))
    pid = await log_punish(message.chat.id, uid, "kick", rest, 0, message.from_user.id)
    ctx = await modlog.build_context(message.chat.id, uid)
    await modlog.write(message.chat.id, pid, uid, name,
                       message.from_user.id, message.from_user.first_name,
                       "kick", rest, 0, "админ", ctx, bot=bot)
    sent = await message.reply(f"👢 <b>Исключён</b>\n👤 {mention_id(uid, name)}\n"
                               f"📝 Причина: {html.escape(rest)}\n<code>#{pid}</code>")
    modlog.schedule_autodelete(bot, sent)


# ---------------- ПРЕДУПРЕЖДЕНИЯ ----------------
@router.message(Cmd("варн", "пред", "предупреждение", "warn", section=S_BAN, rank=1,
                    usage="варн {ссылка} {причина}", desc="Выдать предупреждение"))
async def cmd_warn(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, rest = await resolve_target(message, args, bot)
    err = await guard_target(message, bot, uid, "предупредить")
    if err:
        return await message.reply(err)
    if not await check_reason(message, "warn", rest):
        return

    target_rank = await get_rank(message.chat.id, uid)
    if target_rank >= WARN_IMMUNE_FROM:
        return await message.reply(
            f"🛡 <b>{rank_label(target_rank)}</b> имеет иммунитет к варнам.\n"
            "Техническим администраторам, заместителям и лидерам варны не выдаются.")

    await db.execute("INSERT INTO warns (chat_id,user_id,admin_id,reason,ts) VALUES (?,?,?,?,?)",
                     (message.chat.id, uid, message.from_user.id, rest, int(time.time())))
    pid = await log_punish(message.chat.id, uid, "warn", rest, 0, message.from_user.id)
    row = await db.fetchone("SELECT COUNT(*) c FROM warns WHERE chat_id=? AND user_id=?",
                            (message.chat.id, uid))

    # У персонала свой лимит для каждой ступени; у обычных игроков остаётся
    # настраиваемый общий лимит с автомутом.
    rank_limit = RANK_WARN_LIMITS.get(target_rank)
    limit = rank_limit or int(await db.get_setting(
        message.chat.id, "warn_limit", str(WARN_LIMIT)))
    text = (f"⚠️ <b>Предупреждение {row['c']}/{limit}</b>\n"
            f"👤 {mention_id(uid, name)}\n"
            f"🎖 Статус: <b>{rank_label(target_rank) if target_rank else 'Игрок'}</b>\n"
            f"📝 Причина: {html.escape(rest)}\n"
            f"👮 {mention_id(message.from_user.id, message.from_user.first_name)}\n"
            f"<code>#{pid}</code>")
    if row["c"] >= limit:
        if rank_limit:
            new_rank = target_rank - 1
            await set_rank(message.chat.id, uid, new_rank, message.from_user.id)
            await db.execute("DELETE FROM warns WHERE chat_id=? AND user_id=?",
                             (message.chat.id, uid))
            new_label = rank_label(new_rank) if new_rank else "Игрок"
            text += (f"\n\n⬇️ Лимит варнов для должности достигнут.\n"
                     f"Понижен: <b>{rank_label(target_rank)}</b> → <b>{new_label}</b>.\n"
                     "Счётчик варнов для новой ступени обнулён.")
        else:
            until = datetime.now(timezone.utc) + timedelta(hours=WARN_MUTE_HOURS)
            try:
                await bot.restrict_chat_member(message.chat.id, uid, MUTE_OFF, until_date=until)
                await log_punish(message.chat.id, uid, "mute",
                                 f"автомут: {limit} предупреждений", WARN_MUTE_HOURS * 3600, 0)
                text += f"\n\n🔇 Лимит достигнут — автомут на {WARN_MUTE_HOURS} ч."
            except Exception as e:
                if "administrator" in str(e).lower():
                    text += "\n\n<i>(автомут не применён: пользователь — админ Telegram)</i>"
                else:
                    text += "\n\n<i>(не хватило прав для автомута)</i>"
            await db.execute("DELETE FROM warns WHERE chat_id=? AND user_id=?",
                             (message.chat.id, uid))
    ctx = await modlog.build_context(message.chat.id, uid)
    await modlog.write(message.chat.id, pid, uid, name,
                       message.from_user.id, message.from_user.first_name,
                       "warn", rest, 0, "админ", ctx, bot=bot)
    sent = await message.reply(text)
    modlog.schedule_autodelete(bot, sent)


@router.message(Cmd("снять варн", "снять пред", "минус варн", "unwarn", section=S_BAN, rank=1,
                    usage="снять варн {ссылка}", desc="Снять одно предупреждение"))
async def cmd_unwarn(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 1):
        return
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя.")
    await db.execute("DELETE FROM warns WHERE id=(SELECT id FROM warns WHERE chat_id=? "
                     "AND user_id=? ORDER BY id DESC LIMIT 1)", (message.chat.id, uid))
    await db.execute("UPDATE punishments SET active=0, lifted_by=?, lifted_ts=? WHERE id="
                     "(SELECT id FROM punishments WHERE chat_id=? AND user_id=? AND kind='warn' "
                     "AND active=1 ORDER BY id DESC LIMIT 1)",
                     (message.from_user.id, int(time.time()), message.chat.id, uid))
    await message.reply(f"✅ Снято одно предупреждение с {mention_id(uid, name)}.")


@router.message(Cmd("варнлист", "варн лист", "список варнов", "все варны",
                    section=S_BAN, rank=1, usage="варнлист",
                    desc="Список всех предупреждений чата (модерация)"))
async def cmd_warnlist(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 1):
        return
    await message.reply(await render_list(message.chat.id, "warn"),
                        disable_web_page_preview=True)


@router.message(Cmd("преды", "варны", "мои варны", "мои преды", "предупреждения",
                    section=S_BAN, usage="преды",
                    desc="Посмотреть свои предупреждения"))
async def cmd_warns(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, _ = await resolve_target(message, args, bot)
    own = False
    if not uid and message.from_user:
        uid, name = message.from_user.id, message.from_user.first_name
        own = True

    rows = await db.fetchall(
        "SELECT reason, ts, admin_id FROM warns WHERE chat_id=? AND user_id=? "
        "ORDER BY id DESC", (message.chat.id, uid))
    target_rank = await get_rank(message.chat.id, uid)
    if target_rank >= WARN_IMMUNE_FROM:
        return await message.reply(
            f"🛡 {mention_id(uid, name)} — <b>{rank_label(target_rank)}</b>.\n"
            "Для этой должности действует иммунитет к варнам.")
    limit = RANK_WARN_LIMITS.get(target_rank) or int(await db.get_setting(
        message.chat.id, "warn_limit", str(WARN_LIMIT)))

    if not rows:
        return await message.reply(
            f"✅ {'У вас' if own else f'У {mention_id(uid, name)}'} "
            f"<b>нет предупреждений</b>.\nЛимит для текущего статуса: {limit}")

    left = limit - len(rows)
    head = (f"⚠️ <b>{'Ваши предупреждения' if own else 'Предупреждения'}</b>"
            f"{'' if own else ' ' + mention_id(uid, name)}\n"
            f"Всего: <b>{len(rows)}/{limit}</b>")
    if left > 0:
        head += f" · до наказания осталось: <b>{left}</b>"
    else:
        head += " · <b>лимит достигнут</b>"

    lines = [head, ""]
    for i, r in enumerate(rows, 1):
        who = ""
        if r["admin_id"]:
            a = await db.get_user(r["admin_id"])
            who = f" · 👮 {mention_id(r['admin_id'], a['first_name'])}"
        lines.append(
            f"{i}. {html.escape(r['reason'] or 'без причины')}\n"
            f"   🕒 {time.strftime('%d.%m.%Y %H:%M', time.localtime(r['ts']))}{who}")

    await message.reply("\n".join(lines)[:3800], disable_web_page_preview=True)


@router.message(Cmd("лимит варнов", "варнлимит", section=S_BAN, rank=3,
                    usage="лимит варнов {число}", desc="Настроить лимит предупреждений"))
async def cmd_warn_limit(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 3):
        return
    if not args.strip().isdigit():
        cur = await db.get_setting(message.chat.id, "warn_limit", str(WARN_LIMIT))
        return await message.reply(f"Текущий лимит: <b>{cur}</b>\n"
                                   f"Изменить: <code>лимит варнов 5</code>")
    await db.set_setting(message.chat.id, "warn_limit", args.strip())
    await message.reply(f"✅ Лимит предупреждений: <b>{args.strip()}</b>")


# ---------------- ИСТОРИЯ (для техадмина) ----------------
@router.message(Cmd("история", "история наказаний", "досье", "инфо о наказаниях",
                    section=S_BAN, rank=6, usage="история {ссылка}",
                    desc="Полная история наказаний (техадмин)"))
async def cmd_history(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 6):
        return
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя: реплаем, @ником или id.")
    await message.reply(await render_history(message.chat.id, uid, name),
                        disable_web_page_preview=True)


@router.message(Cmd("наказание", "инфо наказание", section=S_BAN, rank=6,
                    usage="наказание {номер}", desc="Детали наказания по номеру"))
async def cmd_punish_info(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 6):
        return
    a = (args or "").strip().lstrip("#")
    if not a.isdigit():
        return await message.reply("Формат: <code>наказание 42</code>")
    r = await db.fetchone("SELECT * FROM punishments WHERE id=?", (int(a),))
    if not r:
        return await message.reply("Наказание с таким номером не найдено.")
    u = await db.get_user(r["user_id"])
    by = await db.get_user(r["by_id"]) if r["by_id"] else None
    await message.reply(
        f"📋 <b>Наказание #{r['id']}</b>\n"
        f"Тип: <b>{KIND_NAMES.get(r['kind'], r['kind'])}</b>\n"
        f"👤 Кому: {mention_id(r['user_id'], u['first_name'])}\n"
        f"👮 Кем: {mention_id(r['by_id'], by['first_name']) if by else 'система'}\n"
        f"📝 Причина: {html.escape(r['reason'] or '—')}\n"
        f"⏱ Срок: {human_period(r['seconds']) if r['seconds'] else 'навсегда/разовое'}\n"
        f"🕒 Выдано: {time.strftime('%d.%m.%Y %H:%M', time.localtime(r['ts']))}\n"
        f"Статус: {'🟢 активно' if r['active'] else '⚪️ снято'}")


@router.message(Cmd("статистика модерации", "стата модерации", section=S_BAN, rank=4,
                    usage="статистика модерации", desc="Кто сколько наказаний выдал"))
async def cmd_mod_stats(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 4):
        return
    rows = await db.fetchall(
        "SELECT by_id, COUNT(*) c FROM punishments WHERE chat_id=? AND by_id<>0 "
        "GROUP BY by_id ORDER BY c DESC LIMIT 15", (message.chat.id,))
    if not rows:
        return await message.reply("Наказаний ещё не выдавали.")
    lines = []
    for i, r in enumerate(rows):
        u = await db.get_user(r["by_id"])
        det = await db.fetchall(
            "SELECT kind, COUNT(*) c FROM punishments WHERE chat_id=? AND by_id=? GROUP BY kind",
            (message.chat.id, r["by_id"]))
        d = " · ".join(f"{KIND_NAMES.get(x['kind'], x['kind'])}: {x['c']}" for x in det)
        lines.append(f"{i+1}. {mention_id(r['by_id'], u['first_name'])} — "
                     f"<b>{r['c']}</b>\n   <i>{d}</i>")
    await message.reply("📊 <b>Статистика модерации</b>\n\n" + "\n".join(lines))


@router.message(Cmd("причина обязательна", "требовать причину", section=S_BAN, rank=4,
                    usage="причина обязательна вкл|выкл",
                    desc="Требовать причину для наказаний"))
async def cmd_reason_req(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 4):
        return
    a = (args or "").strip().lower()
    if a in {"вкл", "on", "да"}:
        await db.set_setting(message.chat.id, "reason_required", "1")
        return await message.reply("✅ Причина для мута/бана/варна обязательна.")
    if a in {"выкл", "off", "нет"}:
        await db.set_setting(message.chat.id, "reason_required", "0")
        return await message.reply("⚠️ Причину теперь можно не указывать.")
    cur = await db.get_setting(message.chat.id, "reason_required", "1")
    await message.reply(f"Сейчас: <b>{'обязательна' if cur == '1' else 'необязательна'}</b>\n"
                        f"Изменить: <code>причина обязательна выкл</code>")


# ---------------- ЧИСТКА ----------------
@router.message(Cmd("удалить", "del", "уд", section=S_CLEAN, rank=1,
                    usage="удалить (реплаем)", desc="Удалить сообщение"))
async def cmd_del(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 1):
        return
    if not message.reply_to_message:
        return await message.reply("Используйте реплаем на сообщение.")
    try:
        await message.reply_to_message.delete()
        await message.delete()
    except Exception as e:
        await message.reply(f"⚠️ {html.escape(str(e))}")


@router.message(Cmd("чистка", "очистить", "purge", section=S_CLEAN, rank=2,
                    usage="чистка {число}", desc="Удалить N последних сообщений"))
async def cmd_purge(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 2):
        return
    n = int(args.strip()) if args.strip().isdigit() else 0
    if not n and not message.reply_to_message:
        return await message.reply("Укажите количество: <code>чистка 20</code> "
                                   "или ответьте на сообщение.")
    start = message.reply_to_message.message_id if message.reply_to_message \
        else message.message_id - n
    ids = list(range(start, message.message_id))
    deleted = 0
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        try:
            await bot.delete_messages(message.chat.id, chunk)
            deleted += len(chunk)
        except Exception:
            for mid in chunk:
                try:
                    await bot.delete_message(message.chat.id, mid)
                    deleted += 1
                except Exception:
                    pass
    try:
        await message.delete()
    except Exception:
        pass
    await message.answer(f"🧹 Удалено сообщений: <b>{deleted}</b>")


@router.message(Cmd("кик неактив", "чистка неактив", section=S_CLEAN, rank=4,
                    usage="кик неактив {период}", desc="Кик неактивных участников"))
async def cmd_kick_inactive(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 4):
        return
    secs, _ = parse_period(args)
    secs = secs or 30 * 86400
    border = int(time.time()) - secs
    rows = await db.fetchall(
        "SELECT user_id FROM chat_stats WHERE chat_id=? AND last_seen < ?",
        (message.chat.id, border))
    if not rows:
        return await message.reply("Неактивных не найдено.")
    kicked = 0
    for r in rows[:50]:
        if await get_rank(message.chat.id, r["user_id"]) > 0:
            continue
        try:
            await bot.ban_chat_member(message.chat.id, r["user_id"])
            await bot.unban_chat_member(message.chat.id, r["user_id"])
            kicked += 1
        except Exception:
            continue
    await message.reply(f"🧹 Исключено неактивных (более {human_period(secs)}): <b>{kicked}</b>")


@router.message(Cmd("кик удаленных", "кик удалённых", "чистка удаленных", section=S_CLEAN,
                    rank=4, usage="кик удалённых", desc="Кик удалённых аккаунтов"))
async def cmd_kick_deleted(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 4):
        return
    rows = await db.fetchall("SELECT user_id FROM chat_stats WHERE chat_id=?", (message.chat.id,))
    kicked = 0
    for r in rows[:100]:
        try:
            m = await bot.get_chat_member(message.chat.id, r["user_id"])
            u = m.user
            if not u.first_name and not u.username:
                await bot.ban_chat_member(message.chat.id, u.id)
                await bot.unban_chat_member(message.chat.id, u.id)
                kicked += 1
        except Exception:
            continue
    await message.reply(f"🧹 Удалённых аккаунтов исключено: <b>{kicked}</b>")
