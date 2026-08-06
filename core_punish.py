"""Наказания: журнал, обязательная причина, защита лидера."""
from __future__ import annotations

import html
import time
from typing import Optional

from aiogram import Bot
from aiogram.types import Message

import db
from core_ranks import effective_rank, get_rank, rank_label
from core_registry import MAX_RANK, RANK_NAMES, stars
from core_resolve import human_period, parse_period
from utils import mention_id

KIND_NAMES = {"mute": "мут", "ban": "бан", "warn": "предупреждение", "kick": "кик"}
KIND_EMOJI = {"mute": "🔇", "ban": "🔨", "warn": "⚠️", "kick": "👢"}

# Срок обязателен только для мута. Бан без срока считается бессрочным.
NEEDS_TIME = {"mute"}

MIN_REASON_LEN = 3


def usage_hint(kind: str) -> str:
    """Подсказка, если модератор забыл причину."""
    name = KIND_NAMES.get(kind, kind)
    if kind in NEEDS_TIME:
        return (
            f"❗️ <b>Нельзя выдать {name} без причины.</b>\n\n"
            f"Правильный формат:\n"
            f"<code>{name} @юзер {{время}} {{причина}}</code>\n\n"
            f"Примеры:\n"
            f"<code>{name} @user 2 часа спам</code>\n"
            f"<code>{name} @user 7 дней нарушение п.3 правил</code>\n"
            f"<code>{name} 30 минут оскорбления</code> <i>(реплаем)</i>\n\n"
            f"Время: <code>минут</code> · <code>часов</code> · <code>дней</code> · "
            f"<code>недель</code>")
    return (
        f"❗️ <b>Нельзя выдать {name} без причины.</b>\n\n"
        f"Правильный формат:\n"
        f"<code>{name} @юзер {{причина}}</code>\n\n"
        f"Примеры:\n"
        f"<code>{name} @user спам ссылками</code>\n"
        f"<code>{name} нарушение п.5 правил</code> <i>(реплаем)</i>")


async def check_reason(message: Message, kind: str, reason: str,
                       seconds: int = 0) -> bool:
    """Проверяет, что причина указана. False -> уже отправлена подсказка."""
    if await db.get_setting(message.chat.id, "reason_required", "1") != "1":
        return True
    clean = (reason or "").strip()
    if len(clean) < MIN_REASON_LEN:
        await message.reply(usage_hint(kind))
        return False
    if kind in NEEDS_TIME and not seconds:
        need_time = await db.get_setting(message.chat.id, "time_required", "1") == "1"
        if need_time:
            await message.reply(
                f"❗️ <b>Укажите срок наказания.</b>\n\n"
                f"<code>{KIND_NAMES[kind]} @юзер 2 часа {html.escape(clean)}</code>\n"
                f"<code>{KIND_NAMES[kind]} @юзер 7 дней {html.escape(clean)}</code>\n\n"
                f"Для бессрочного: добавьте слово <code>навсегда</code>.")
            return False
    return True


def strip_forever(text: str) -> tuple[str, bool]:
    """Вырезает «навсегда» из причины."""
    low = (text or "").lower()
    for w in ("навсегда", "перманентно", "насовсем", "permanent", "forever"):
        if w in low:
            i = low.index(w)
            return (text[:i] + text[i + len(w):]).strip(" ,.-"), True
    return text, False


async def guard_target(message: Message, bot: Bot, uid: int,
                       action: str = "наказать") -> Optional[str]:
    """None — можно. Иначе текст отказа. Лидера (7) не тронуть никому."""
    if not uid:
        return "Укажите пользователя: реплаем, @ником или id."

    me = await bot.me()
    if uid == me.id:
        return "🤖 Себя я наказывать не стану."

    actor = message.from_user.id if message.from_user else 0
    if uid == actor:
        return "🙂 Себя наказывать не нужно."

    # админа Telegram бот ограничить не может — предупреждаем заранее
    if action in {"замутить", "забанить", "кикнуть"}:
        try:
            m = await bot.get_chat_member(message.chat.id, uid)
            if m.status in {"creator", "administrator"}:
                who = ("владелец чата" if m.status == "creator"
                       else "администратор чата")
                return (
                    f"⛔️ <b>Нельзя {action} — это {who} в Telegram</b>\n\n"
                    f"Telegram запрещает ботам ограничивать администраторов.\n\n"
                    f"<b>Что делать:</b>\n"
                    f"1️⃣ Снимите с него админку: <i>Управление группой → "
                    f"Администраторы</i>\n"
                    f"2️⃣ Повторите команду\n\n"
                    f"<i>Ранги бота выдаются отдельно: </i>"
                    f"<code>+модер 2 @user</code>")
        except Exception:
            pass

    target_rank = await get_rank(message.chat.id, uid)
    actor_rank = await effective_rank(message, bot)

    # Абсолютная защита лидера клана
    if target_rank >= MAX_RANK:
        return (f"👑 <b>{RANK_NAMES[MAX_RANK]}</b> неприкосновенен.\n"
                f"Его нельзя {action}, понизить или снять.")

    if target_rank >= actor_rank:
        return (f"⛔️ Нельзя {action} равного или старшего по рангу.\n"
                f"Цель: <b>{rank_label(target_rank) if target_rank else 'Участник'}</b>\n"
                f"Вы: <b>{rank_label(actor_rank) if actor_rank else 'Участник'}</b>")
    return None


async def log_punish(chat_id: int, uid: int, kind: str, reason: str,
                     seconds: int, by_id: int) -> int:
    await db.execute(
        "INSERT INTO punishments (chat_id,user_id,kind,reason,seconds,by_id,ts,active) "
        "VALUES (?,?,?,?,?,?,?,1)",
        (chat_id, uid, kind, reason or "", seconds, by_id, int(time.time())))
    row = await db.fetchone("SELECT last_insert_rowid() id")
    return row["id"] if row else 0


async def lift_punish(chat_id: int, uid: int, kind: str, by_id: int) -> None:
    await db.execute(
        "UPDATE punishments SET active=0, lifted_by=?, lifted_ts=? "
        "WHERE chat_id=? AND user_id=? AND kind=? AND active=1",
        (by_id, int(time.time()), chat_id, uid, kind))


async def render_list(chat_id: int, kind: str, limit: int = 25) -> str:
    """Мут-лист / бан-лист / варн-лист с причинами и авторами."""
    rows = await db.fetchall(
        "SELECT p.*, u.first_name FROM punishments p "
        "LEFT JOIN users u ON u.user_id = p.user_id "
        "WHERE p.chat_id=? AND p.kind=? AND p.active=1 ORDER BY p.id DESC LIMIT ?",
        (chat_id, kind, limit))
    title = {"mute": "🔇 Мут-лист", "ban": "🔨 Бан-лист",
             "warn": "⚠️ Список предупреждений"}.get(kind, kind)
    if not rows:
        return f"{title}\n\nСписок пуст."

    now = int(time.time())
    out = [f"<b>{title}</b> — активных: {len(rows)}\n"]
    for r in rows:
        who = mention_id(r["user_id"], r["first_name"])
        by = await db.get_user(r["by_id"]) if r["by_id"] else None
        byname = mention_id(r["by_id"], by["first_name"]) if by else "—"
        when = time.strftime("%d.%m %H:%M", time.localtime(r["ts"]))
        line = f"• {who}"
        if r["seconds"]:
            left = r["ts"] + r["seconds"] - now
            line += f" — до {time.strftime('%d.%m %H:%M', time.localtime(r['ts'] + r['seconds']))}"
            if left > 0:
                line += f" (ещё {human_period(left)})"
        elif r["kind"] in NEEDS_TIME:
            line += " — навсегда"
        line += f"\n   📝 {html.escape(r['reason'] or 'без причины')}"
        line += f"\n   👮 {byname} · {when} · <code>#{r['id']}</code>"
        out.append(line)
    return "\n".join(out)[:3900]


async def render_history(chat_id: int, uid: int, name: str | None,
                         limit: int = 20) -> str:
    """Полная история наказаний пользователя — для техадмина."""
    rows = await db.fetchall(
        "SELECT * FROM punishments WHERE chat_id=? AND user_id=? "
        "ORDER BY id DESC LIMIT ?", (chat_id, uid, limit))
    head = f"📋 <b>История наказаний</b> {mention_id(uid, name)}\n"
    if not rows:
        return head + "\nЧисто — наказаний не было."

    stats = await db.fetchall(
        "SELECT kind, COUNT(*) c FROM punishments WHERE chat_id=? AND user_id=? "
        "GROUP BY kind", (chat_id, uid))
    summary = " · ".join(f"{KIND_EMOJI.get(s['kind'],'')} {KIND_NAMES.get(s['kind'],s['kind'])}: "
                         f"{s['c']}" for s in stats)
    out = [head, summary, ""]
    for r in rows:
        by = await db.get_user(r["by_id"]) if r["by_id"] else None
        byname = mention_id(r["by_id"], by["first_name"]) if by else "—"
        when = time.strftime("%d.%m.%Y %H:%M", time.localtime(r["ts"]))
        status = "🟢 активно" if r["active"] else "⚪️ снято"
        dur = human_period(r["seconds"]) if r["seconds"] else (
            "навсегда" if r["kind"] in NEEDS_TIME else "—")
        out.append(
            f"{KIND_EMOJI.get(r['kind'],'•')} <b>{KIND_NAMES.get(r['kind'], r['kind'])}</b> "
            f"<code>#{r['id']}</code> · {status}\n"
            f"   📝 {html.escape(r['reason'] or 'без причины')}\n"
            f"   ⏱ {dur} · 👮 {byname}\n"
            f"   🕒 {when}")
    return "\n".join(out)[:3900]


# --- Расшифровка ошибок Telegram --------------------------------------
def explain_error(err: Exception, kind: str = "наказать") -> str:
    """Понятное сообщение вместо сырого текста Telegram API."""
    t = str(err).lower()

    if "user is an administrator" in t or "can't remove chat owner" in t:
        return (
            f"⛔️ <b>Нельзя {kind} администратора Telegram</b>\n\n"
            f"Этот человек — админ чата в самом Telegram, "
            f"а ботам запрещено их ограничивать.\n\n"
            f"<b>Что делать:</b>\n"
            f"1️⃣ Снимите с него админку в Telegram\n"
            f"   <i>Управление группой → Администраторы</i>\n"
            f"2️⃣ Потом повторите команду\n\n"
            f"<i>Ранг в боте выдаётся отдельно: </i><code>+модер 2 @user</code>")

    if "not enough rights" in t or "not enough permissions" in t:
        return ("⛔️ <b>У бота не хватает прав</b>\n\n"
                "Нужно право «Блокировка пользователей».\n"
                "Проверить: <code>проверка</code>")

    if "chat admin required" in t:
        return ("⛔️ <b>Бот не администратор чата</b>\n\n"
                "Выдайте боту права администратора.\n"
                "Проверить: <code>проверка</code>")

    if "user not found" in t:
        return "⚠️ Пользователь не найден. Возможно, он не состоит в чате."

    if "participant_id_invalid" in t or "peer_id_invalid" in t:
        return ("⚠️ Не удалось определить пользователя.\n"
                "Попробуйте ответить реплаем на его сообщение.")

    if "method is available for supergroup" in t:
        return ("⚠️ Команда работает только в супергруппах.\n"
                "<i>Обычную группу нужно перевести в супергруппу.</i>")

    if "user_admin_invalid" in t:
        return (f"⛔️ Нельзя {kind} этого пользователя — "
                f"у него административные права в Telegram.")

    import html as _h
    return (f"⚠️ Не удалось выполнить: {_h.escape(str(err))}\n"
            f"Проверьте права бота — <code>проверка</code>")
