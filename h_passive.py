"""Пассивные обработчики: вход в группу, запрос прав, автовыдача ранга владельцу,
приветствие участников, триггеры, учёт активности.
Подключается ПОСЛЕДНИМ, чтобы не перехватывать команды."""
from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter
from aiogram.types import (ChatMemberUpdated, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

import db
from config import MSG_REWARD, MSG_REWARD_COOLDOWN, XP_PER_MESSAGE
from core_ranks import get_rank, set_rank
from core_registry import MAX_RANK, RANK_NAMES, stars
from utils import mention, mention_id, money

router = Router(name="passive")

# Права, которые бот просит при добавлении в группу.
# Telegram сам покажет чекбоксы при выдаче админки по этой ссылке.
NEEDED_RIGHTS = (
    "change_info+delete_messages+restrict_members+invite_users+pin_messages+manage_chat"
)

RIGHTS_TEXT = """👋 <b>Спасибо за добавление!</b>

Чтобы я работал полноценно, выдайте мне права администратора:

🔧 <b>Управление группой</b>
🗑 <b>Удаление сообщений</b>
🚫 <b>Блокировка пользователей</b>
📌 <b>Закрепление сообщений</b>
🔗 <b>Приглашение по ссылке</b>

Нажмите кнопку ниже — Telegram сразу предложит нужные галочки.
Либо вручную: <i>Управление группой → Администраторы → добавить меня</i>."""


def _rights_kb(bot_username: str, chat_id: int) -> InlineKeyboardMarkup:
    """Кнопка добавления бота админом с уже отмеченными правами."""
    url = (f"https://t.me/{bot_username}?startgroup&admin={NEEDED_RIGHTS}")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Выдать права администратора", url=url)],
        [InlineKeyboardButton(text="🩺 Проверить права", callback_data="chk:rights")],
    ])


async def _grant_owner(chat_id: int, bot: Bot) -> tuple[int, str] | None:
    """Выдаёт владельцу (creator) группы высший ранг при первом входе бота."""
    try:
        admins = await bot.get_chat_administrators(chat_id)
    except Exception:
        return None
    for m in admins:
        if m.status == "creator" and m.user and not m.user.is_bot:
            cur = await get_rank(chat_id, m.user.id)
            if cur < MAX_RANK:
                await set_rank(chat_id, m.user.id, MAX_RANK, 0)
            await db.touch_user(m.user.id, m.user.username, m.user.first_name)
            return m.user.id, m.user.first_name or "Владелец"
    return None


@router.my_chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_added(event: ChatMemberUpdated, bot: Bot):
    """Бота добавили в группу: просим права и выдаём владельцу высший ранг."""
    if event.chat.type not in {"group", "supergroup"}:
        return
    await db.register_chat(event.chat.id, event.chat.title)

    me = await bot.me()
    text = RIGHTS_TEXT

    # владельцу группы — 7 ранг сразу
    owner = await _grant_owner(event.chat.id, bot)
    if owner:
        uid, name = owner
        text += (f"\n\n👑 {mention_id(uid, name)} — владелец чата, "
                 f"выдан высший ранг:\n<b>{stars(MAX_RANK)} {RANK_NAMES[MAX_RANK]}</b>")
    else:
        # не смогли получить список админов (нет прав) — выдадим тому, кто добавил
        adder = event.from_user
        if adder and not adder.is_bot:
            if await get_rank(event.chat.id, adder.id) < MAX_RANK:
                await set_rank(event.chat.id, adder.id, MAX_RANK, 0)
            text += (f"\n\n👑 {mention(adder)} — выдан высший ранг:\n"
                     f"<b>{stars(MAX_RANK)} {RANK_NAMES[MAX_RANK]}</b>")

    text += "\n\n📖 <code>команды</code> — все возможности\n🔐 <code>ДК</code> — доступ команд"

    try:
        await bot.send_message(event.chat.id, text,
                               reply_markup=_rights_kb(me.username, event.chat.id),
                               disable_web_page_preview=True)
    except Exception:
        pass


@router.my_chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_MEMBER))
async def on_rights_changed(event: ChatMemberUpdated, bot: Bot):
    """Боту изменили права — подтверждаем, чего не хватает."""
    new = event.new_chat_member
    if getattr(new, "status", "") != "administrator":
        return
    missing = []
    if not getattr(new, "can_delete_messages", False):
        missing.append("🗑 Удаление сообщений")
    if not getattr(new, "can_restrict_members", False):
        missing.append("🚫 Блокировка пользователей")
    if not getattr(new, "can_pin_messages", False):
        missing.append("📌 Закрепление сообщений")
    if not getattr(new, "can_invite_users", False):
        missing.append("🔗 Приглашение по ссылке")
    if not getattr(new, "can_change_info", False):
        missing.append("🔧 Управление группой")

    # владельцу на всякий случай ещё раз выдаём ранг
    await _grant_owner(event.chat.id, bot)

    try:
        if missing:
            await bot.send_message(
                event.chat.id,
                "⚠️ Я администратор, но не хватает прав:\n" + "\n".join(f"• {m}" for m in missing)
                + "\n\nБез них часть команд работать не будет.")
        else:
            await bot.send_message(
                event.chat.id,
                "✅ Все права получены — я полностью готов к работе!\n"
                "📖 <code>команды</code> · 🔐 <code>ДК</code> · 🩺 <code>проверка</code>")
    except Exception:
        pass


@router.my_chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_removed(event: ChatMemberUpdated):
    await db.execute("DELETE FROM chats WHERE chat_id=?", (event.chat.id,))


@router.message(F.new_chat_members)
async def on_new_members(message: Message, bot: Bot):
    me = await bot.me()
    tmpl = await db.get_setting(message.chat.id, "greeting")
    for u in message.new_chat_members or []:
        if u.id == me.id or u.is_bot:
            continue
        await db.get_user(u.id)
        if tmpl:
            text = (tmpl.replace("%имя%", html.escape(u.first_name or ""))
                        .replace("%чат%", html.escape(message.chat.title or "")))
            await message.answer(text)
        else:
            bal = (await db.get_user(u.id))["balance"]
            await message.answer(f"👋 Добро пожаловать, {mention(u)}!\n"
                                 f"🍬 Стартовый баланс: <b>{money(bal)}</b> — /команды")

        import time as _t
        await db.execute(
            "INSERT OR IGNORE INTO first_seen (chat_id, user_id, ts) VALUES (?,?,?)",
            (message.chat.id, u.id, int(_t.time())))

        from h_userinfo import (TEMPLATE, get_form_topic, needs_form,
                                       topic_link)
        if await needs_form(message.chat.id, u.id):
            ft = await get_form_topic(message.chat.id)
            # Шаблон шлём ТОЛЬКО в тему описаний. В общий чат — короткую
            # ссылку, чтобы не засорять его простынёй из анкеты.
            try:
                if ft:
                    hello = await message.bot.send_message(
                        message.chat.id,
                        f"📝 {mention(u)}, добро пожаловать!\n\n"
                        f"Чтобы писать в чат, заполните описание:\n"
                        f"<code>{TEMPLATE}</code>",
                        message_thread_id=ft,
                        disable_web_page_preview=True)
                    import asyncio as _a
                    _a.create_task(_del_later(hello, 600))
                else:
                    hello = await message.answer(
                        f"📝 {mention(u)}, заполните описание, чтобы писать "
                        f"в чат.\n\n<code>{TEMPLATE}</code>",
                        disable_web_page_preview=True)
                    import asyncio as _a
                    _a.create_task(_del_later(hello, 300))
            except Exception:
                pass


async def _del_later(msg, delay: int = 60) -> None:
    """Убрать служебную подсказку через delay секунд."""
    import asyncio
    try:
        await asyncio.sleep(delay)
        await msg.delete()
    except Exception:
        pass


# ── Медиа от тех, кто без описания ──────────────────────────────────
MEDIA_BLOCK = (F.voice | F.video_note | F.sticker | F.animation | F.photo
               | F.video | F.audio | F.document)


@router.message(MEDIA_BLOCK)
async def media_gate(message: Message, bot: Bot):
    """Пока описание не заполнено — никаких кружочков, голосовых и медиа."""
    if message.chat.type == "private":
        return
    if not message.from_user or message.from_user.is_bot:
        return
    uid = message.from_user.id

    from h_userinfo import (get_form_topic, needs_form, topic_id,
                                   topic_link)
    if not await needs_form(message.chat.id, uid):
        # описание есть — но в теме анкет всё равно не сорим
        ft = await get_form_topic(message.chat.id)
        if ft and topic_id(message) == ft:
            try:
                await message.delete()
            except Exception:
                pass
        return

    from core_ranks import effective_rank
    if await effective_rank(message, bot) >= 1:
        return

    try:
        await message.delete()
    except Exception:
        pass

    if await db.cooldown_left(uid, "form_media", 90):
        return
    await db.set_cooldown(uid, "form_media")
    ft = await get_form_topic(message.chat.id)
    link = topic_link(message.chat.id, ft) if ft else ""
    try:
        warn = await message.bot.send_message(
            message.chat.id,
            f"🔇 {mention(message.from_user)}, голосовые, кружочки и медиа "
            f"будут доступны после описания.\n\n"
            + (f"✍️ Заполнить: {link}" if link else
               "✍️ Заполнить: команда <code>шаблон</code>"),
            message_thread_id=ft or None,
            disable_web_page_preview=True)
        import asyncio as _a
        _a.create_task(_del_later(warn, 60))
    except Exception:
        pass


@router.message(F.text | F.caption)
async def activity(message: Message, bot: Bot):
    """XP, монеты, триггеры и проверка обязательной анкеты."""
    if not message.from_user or message.from_user.is_bot:
        return
    uid = message.from_user.id
    text_raw = (message.text or message.caption or "").strip()

    # --- буфер для контекста в логах модерации ---
    try:
        import core_modlog as _ml
        await _ml.remember(message)
    except Exception:
        pass

    # --- автомодерация: оскорбления и мат ---
    try:
        from h_automod import handle as _automod
        if await _automod(message, bot):
            return
    except Exception:
        pass

    # --- присланная анкета: сохраняем в любом чате ----------------------
    from h_userinfo import (LINE_RE as _LR, parse_form as _pf,
                                   _save_form as _sf, _split_lines as _sl,
                                   looks_like_form as _lf)
    _lines = _sl(text_raw)
    if len(_lines) >= 2 and sum(1 for l in _lines if _LR.match(l.strip())) >= 2:
        if _pf(text_raw):
            await _sf(message, text_raw)
            return

    # --- обязательная анкета -------------------------------------------
    if message.chat.type != "private":
        from h_userinfo import (LINE_RE, TEMPLATE, _save_form,
                                       _split_lines, get_form_topic,
                                       looks_like_form, needs_form,
                                       topic_id, topic_link)
        if await needs_form(message.chat.id, uid):
            from core_ranks import effective_rank
            _rank = await effective_rank(message, bot)
            if _rank >= 1:
                # Админ без описания: писать ему можно везде, но в теме
                # анкет всё лишнее всё равно чистим — кроме самой анкеты.
                _ft = await get_form_topic(message.chat.id)
                if _ft and topic_id(message) == _ft:
                    _lines = _split_lines(text_raw)
                    if (sum(1 for l in _lines if LINE_RE.match(l.strip())) >= 2
                            or looks_like_form(text_raw)):
                        await _save_form(message, text_raw)
                        return
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    if not await db.cooldown_left(uid, "form_done_warn", 120):
                        await db.set_cooldown(uid, "form_done_warn")
                        try:
                            warn = await message.bot.send_message(
                                message.chat.id,
                                f"🧹 {mention(message.from_user)}, эта тема только "
                                f"для заполнения описаний.\n"
                                f"Общаться можно в других темах.",
                                message_thread_id=_ft)
                            import asyncio as _a
                            _a.create_task(_del_later(warn, 60))
                        except Exception:
                            pass
                    return
            if _rank < 1:
                form_topic = await get_form_topic(message.chat.id)
                here = topic_id(message)
                in_form_topic = (not form_topic) or (here == form_topic)

                # анкету принимаем только в назначенной теме
                lines = _split_lines(text_raw)
                hits = sum(1 for l in lines if LINE_RE.match(l.strip()))
                # в теме описаний принимаем и свободный рассказ о себе
                if in_form_topic and (hits >= 2 or looks_like_form(text_raw)):
                    await _save_form(message, text_raw)
                    return

                try:
                    await message.delete()
                except Exception:
                    pass

                if not await db.cooldown_left(uid, "form_warn", 60):
                    await db.set_cooldown(uid, "form_warn")
                    if in_form_topic:
                        note = (f"📝 {mention(message.from_user)}, чтобы писать в чате, "
                                f"сначала заполните описание.\n\n"
                                f"Скопируйте, заполните и отправьте сюда:\n\n"
                                f"<code>{TEMPLATE}</code>")
                        target_thread = here or None
                    else:
                        link = topic_link(message.chat.id, form_topic)
                        note = (f"📝 {mention(message.from_user)}, вам пока нельзя "
                                f"писать здесь.\n\n"
                                f"✍️ <b>Сначала заполните описание:</b>\n{link}")
                        target_thread = form_topic
                    try:
                        warn = await message.bot.send_message(
                            message.chat.id, note,
                            message_thread_id=target_thread,
                            disable_web_page_preview=True)
                        import asyncio as _a
                        _a.create_task(_del_later(warn, 90))
                    except Exception:
                        try:
                            await message.answer(note, disable_web_page_preview=True)
                        except Exception:
                            pass
                return
        else:
            # Описание уже есть. Тема описаний — только под анкеты:
            # всё лишнее удаляем у ВСЕХ, включая админов и лидера.
            form_topic = await get_form_topic(message.chat.id)
            if form_topic and topic_id(message) == form_topic:
                lines = _split_lines(text_raw)
                hits = sum(1 for l in lines if LINE_RE.match(l.strip()))
                resend = hits >= 2          # пытается заполнить повторно

                try:
                    await message.delete()
                except Exception:
                    pass

                if resend:
                    # повторная анкета: описание уже есть, второй раз не нужно
                    if not await db.cooldown_left(uid, "form_dup", 60):
                        await db.set_cooldown(uid, "form_dup")
                        note = (f"⚠️ {mention(message.from_user)}, у вас уже есть "
                                f"описание — заполнять второй раз не нужно.\n\n"
                                f"Посмотреть своё: <code>описание</code>\n"
                                f"Изменить: напишите админу.")
                    else:
                        note = ""
                else:
                    # обычная болтовня в теме анкет
                    if not await db.cooldown_left(uid, "form_done_warn", 120):
                        await db.set_cooldown(uid, "form_done_warn")
                        note = (f"🧹 {mention(message.from_user)}, эта тема только "
                                f"для заполнения описаний.\n"
                                f"Общаться можно в других темах.")
                    else:
                        note = ""

                if note:
                    try:
                        warn = await message.bot.send_message(
                            message.chat.id, note,
                            message_thread_id=form_topic,
                            disable_web_page_preview=True)
                        # подсказка сама исчезнет, чтобы не копилась
                        import asyncio as _a
                        _a.create_task(_del_later(warn, 60))
                    except Exception:
                        pass
                return
    await db.add_xp(uid, XP_PER_MESSAGE)
    if message.chat.type != "private":
        await db.bump_chat_stat(message.chat.id, uid, XP_PER_MESSAGE)
        import time as _t
        await db.execute(
            "INSERT INTO daily_stats (day, chat_id, user_id, messages) VALUES (?,?,?,1) "
            "ON CONFLICT(day, chat_id, user_id) DO UPDATE SET messages = messages + 1",
            (_t.strftime("%Y-%m-%d"), message.chat.id, uid))
        await db.execute(
            "INSERT OR IGNORE INTO first_seen (chat_id, user_id, ts) VALUES (?,?,?)",
            (message.chat.id, uid, int(_t.time())))
    if not await db.cooldown_left(uid, "msg_reward", MSG_REWARD_COOLDOWN):
        await db.add_balance(uid, MSG_REWARD)
        await db.set_cooldown(uid, "msg_reward")

    text = (message.text or message.caption or "").lower()
    if message.chat.type != "private" and text:
        rows = await db.fetchall("SELECT pattern, answer FROM triggers WHERE chat_id=?",
                                 (message.chat.id,))
        for r in rows:
            p = (r["pattern"] or "").lower()
            if p and (p == text or p in text):
                try:
                    await message.reply(r["answer"])
                except Exception:
                    pass
                break
