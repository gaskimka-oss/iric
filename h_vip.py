"""Модуль рангов VIP и VIP+.

Включает:
- Уровни: ⭐️ VIP (1) и 🌟 VIP+ (2)
- Бонусы к работе (до +100%) и отношениям (+25%/+50%)
- Меню выбора цвета / темы оформления сообщений («вип меню»)
- Карточки команд: «вип команды» и «вип+ команды»
- Покупка статусов за ириски: «купить вип», «купить вип+»
- Админские команды выдачи и снятия
"""
from __future__ import annotations

import html
import time

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import db
from core_ranks import require
from core_registry import Cmd
from core_resolve import human_period, parse_period, resolve_target
from utils import mention, mention_id, money

router = Router(name="vip")
S_VIP = 15

# Стоимость покупки за ириски на 30 дней
VIP_PRICE = 5000
VIPPLUS_PRICE = 10000

# Темы оформления для VIP пользователей
VIP_THEMES = {
    "default": ("⚪️ Классический", "Классический чистый стиль"),
    "purple": ("🟣 Неоновый фиолетовый", "Стильный фиолетовый акцент"),
    "blue": ("🔵 Лазурный сапфир", "Глубокий синий оттенок"),
    "green": ("🟢 Изумрудный", "Яркий зелёный стиль"),
    "gold": ("🟡 Золотой рассвет", "Роскошное золотое оформление"),
    "ruby": ("🔴 Рубиновый закат", "Пылкий красный стиль"),
    "sakura": ("🌸 Нежная сакура", "Розовый весенний акцент"),
}


def vip_badge_str(level: int) -> str:
    if level >= 2:
        return "🌟 VIP+"
    if level >= 1:
        return "⭐️ VIP"
    return "Отсутствует"


def vip_theme_keyboard(current_theme: str) -> InlineKeyboardMarkup:
    buttons = []
    for key, (name, _) in VIP_THEMES.items():
        check = " ✅" if key == current_theme else ""
        buttons.append([InlineKeyboardButton(text=f"{name}{check}", callback_data=f"vip_set_theme:{key}")])
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="vip_close")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def buy_vip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"⭐️ Купить VIP — {money(VIP_PRICE)}", callback_data="buy_vip_do:1"),
        ],
        [
            InlineKeyboardButton(text=f"🌟 Купить VIP+ — {money(VIPPLUS_PRICE)}", callback_data="buy_vip_do:2"),
        ],
        [
            InlineKeyboardButton(text="❌ Закрыть", callback_data="vip_close")
        ]
    ])


# ================== КОМАНДЫ VIP ==================

@router.message(Cmd("вип команды", "вип инфо", "vip команды", "вип", "vip", section=S_VIP,
                    usage="вип команды", desc="Команды и возможности ранга VIP"))
async def cmd_vip_info(message: Message, bot: Bot, **kw):
    me_id = message.from_user.id
    lvl, until, active = await db.get_vip_info(me_id)
    theme = await db.get_vip_theme(me_id)
    theme_name = VIP_THEMES.get(theme, VIP_THEMES["default"])[0]

    if active:
        left = int(until - time.time())
        status_line = f"🟢 <b>Ваш статус:</b> {vip_badge_str(lvl)} (ещё {human_period(left)})\n🎨 <b>Текущая тема:</b> {theme_name}"
    else:
        status_line = "⚪️ <b>Ваш статус:</b> Отсутствует"

    text = (
        f"⭐ <b>Команды и привилегии ранга VIP</b>\n\n"
        f"{status_line}\n\n"
        f"<b>Возможности VIP:</b>\n"
        f"• 🛠 <b>+50% к награде</b> на команде <code>работа</code> (дополнительные ириски)\n"
        f"• 💖 <b>+25% любви</b> к прокачке отношений в паре (ОТН)\n"
        f"• 🎨 Выбор стилей оформления доступен в ранге 🌟 VIP+ (<code>вип+ команды</code>)\n"
        f"• ▫️ Отметка ⭐️ VIP в карточке профиля (<code>кто я</code> / <code>кто ты</code>)\n\n"
        f"💡 <b>Команды для использования:</b>\n"
        f"• <code>вип+ команды</code> — возможности улучшенного ранга VIP+\n"
        f"• <code>купить вип</code> — приобрести VIP на 30 дней за ириски\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛍 Купить VIP", callback_data="buy_vip_menu")
        ]
    ])
    await message.reply(text, reply_markup=kb, disable_web_page_preview=True)


@router.message(Cmd("вип+ команды", "вип+ инфо", "вип плюс команды", "vip+ команды",
                    "вип+", "vip+", "вип плюс", section=S_VIP,
                    usage="вип+ команды", desc="Команды и возможности ранга VIP+"))
async def cmd_vipplus_info(message: Message, bot: Bot, **kw):
    me_id = message.from_user.id
    lvl, until, active = await db.get_vip_info(me_id)
    theme = await db.get_vip_theme(me_id)
    theme_name = VIP_THEMES.get(theme, VIP_THEMES["default"])[0]

    if active:
        left = int(until - time.time())
        status_line = f"🟢 <b>Ваш статус:</b> {vip_badge_str(lvl)} (ещё {human_period(left)})\n🎨 <b>Текущая тема:</b> {theme_name}"
    else:
        status_line = "⚪️ <b>Ваш статус:</b> Отсутствует"

    text = (
        f"🌟 <b>Команды и привилегии ранга VIP+</b>\n\n"
        f"{status_line}\n\n"
        f"<b>Возможности VIP+:</b>\n"
        f"• 🛠 <b>+100% к награде</b> на команде <code>работа</code> (удвоение всего заработка!)\n"
        f"• 💖 <b>+50% любви</b> к прокачке отношений в паре (ОТН) — максимальная скорость!\n"
        f"• 🎨 Доступ к команде <code>вип меню</code> — выбор эксклюзивных тем и эффектов\n"
        f"• 👑 Выделенный статус 🌟 VIP+ во всех карточках профилей (<code>кто я</code> / <code>кто ты</code>)\n\n"
        f"💡 <b>Команды для использования:</b>\n"
        f"• <code>вип меню</code> — открыть меню настройки цвета\n"
        f"• <code>вип команды</code> — возможности базового ранга VIP\n"
        f"• <code>купить вип+</code> — приобрести VIP+ на 30 дней за ириски\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎨 VIP Меню (Темы)", callback_data="vip_open_menu"),
            InlineKeyboardButton(text="🛍 Купить VIP+", callback_data="buy_vip_menu")
        ]
    ])
    await message.reply(text, reply_markup=kb, disable_web_page_preview=True)


# ================== ПОКУПКА VIP ==================

@router.message(Cmd("купить вип", "купить вип+", "купить vip", "купить vip+", "магазин вип",
                    section=S_VIP, usage="купить вип", desc="Купить VIP или VIP+ за ириски"))
async def cmd_buy_vip_dialog(message: Message, **kw):
    user = await db.get_user(message.from_user.id)
    text = (
        f"🛍 <b>Покупка статусов VIP и VIP+</b>\n\n"
        f"🍬 Ваш баланс: <b>{money(user['balance'])}</b>\n\n"
        f"⭐ <b>VIP на 30 дней:</b> <b>{money(VIP_PRICE)}</b>\n"
        f"• +50% к работе, +25% к ОТН\n\n"
        f"🌟 <b>VIP+ на 30 дней:</b> <b>{money(VIPPLUS_PRICE)}</b>\n"
        f"• +100% к работе (удвоение!), +50% к ОТН, эксклюзивные темы оформления, элитный статус\n\n"
        f"Выберите статус для покупки на 30 дней:"
    )
    await message.reply(text, reply_markup=buy_vip_keyboard(), disable_web_page_preview=True)


@router.callback_query(F.data == "buy_vip_menu")
async def cb_buy_vip_menu(call: CallbackQuery):
    user = await db.get_user(call.from_user.id)
    text = (
        f"🛍 <b>Покупка статусов VIP и VIP+</b>\n\n"
        f"🍬 Ваш баланс: <b>{money(user['balance'])}</b>\n\n"
        f"⭐ <b>VIP на 30 дней:</b> <b>{money(VIP_PRICE)}</b>\n"
        f"• +50% к работе, +25% к ОТН\n\n"
        f"🌟 <b>VIP+ на 30 дней:</b> <b>{money(VIPPLUS_PRICE)}</b>\n"
        f"• +100% к работе (удвоение!), +50% к ОТН, эксклюзивные темы оформления, элитный статус\n\n"
        f"Выберите статус для покупки на 30 дней:"
    )
    await call.message.edit_text(text, reply_markup=buy_vip_keyboard(), disable_web_page_preview=True)
    await call.answer()


@router.callback_query(F.data.startswith("buy_vip_do:"))
async def cb_buy_vip_do(call: CallbackQuery):
    target_lvl = int(call.data.split(":")[1])
    price = VIPPLUS_PRICE if target_lvl == 2 else VIP_PRICE
    lvl_name = "🌟 VIP+" if target_lvl == 2 else "⭐️ VIP"

    user = await db.get_user(call.from_user.id)
    if user["balance"] < price:
        return await call.answer(
            f"❌ Не хватает ирисок! Нужно: {price:,} 🪙, у вас: {user['balance']:,} 🪙.\n"
            f"Заработайте ириски командой «работа» в теме казино!",
            show_alert=True)

    await db.add_balance(call.from_user.id, -price, f"buy_vip_{target_lvl}")
    now = int(time.time())
    # Если уже был VIP, продлеваем
    _, old_until, old_act = await db.get_vip_info(call.from_user.id)
    base_ts = old_until if (old_act and old_until > now) else now
    new_until = base_ts + 30 * 86400

    await db.set_vip(call.from_user.id, new_until, target_lvl)

    extra_btn = [InlineKeyboardButton(text="🎨 Открыть VIP Меню", callback_data="vip_open_menu")] if target_lvl >= 2 else []
    kb = InlineKeyboardMarkup(inline_keyboard=[extra_btn]) if extra_btn else None

    await call.message.edit_text(
        f"🎉 <b>Поздравляем с приобретением {lvl_name}!</b> 🎉\n\n"
        f"Статус активирован на <b>30 дней</b> (до {time.strftime('%d.%m.%Y', time.localtime(new_until))})!\n\n"
        f"Вам доступны все бонусы ранга.",
        reply_markup=kb)
    await call.answer(f"✅ Статус {lvl_name} успешно активирован!", show_alert=True)


# ================== VIP МЕНЮ (ТЕМЫ) ==================

@router.message(Cmd("вип меню", "vip menu", "вип темы", section=S_VIP,
                    usage="вип меню", desc="Выбор цвета и темы оформления VIP+"))
async def cmd_vip_menu(message: Message, **kw):
    me_id = message.from_user.id
    lvl, until, active = await db.get_vip_info(me_id)
    if not active or lvl < 2:
        return await message.reply(
            "🔒 <b>VIP-меню и выбор тем оформления доступны только для пользователей с активным статусом 🌟 VIP+!</b>\n\n"
            "Приобрести статус за ириски: <code>купить вип+</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🛍 Купить VIP+", callback_data="buy_vip_menu")
            ]]))

    theme = await db.get_vip_theme(me_id)
    text = (
        f"🎨 <b>VIP Меню — Выбор темы оформления</b>\n\n"
        f"Ваш статус: <b>{vip_badge_str(lvl)}</b>\n"
        f"Выберите желаемый цветовой стиль сообщений и акцентов:"
    )
    await message.reply(text, reply_markup=vip_theme_keyboard(theme))


@router.callback_query(F.data == "vip_open_menu")
async def cb_vip_open_menu(call: CallbackQuery):
    lvl, until, active = await db.get_vip_info(call.from_user.id)
    if not active or lvl < 2:
        return await call.answer("🔒 Выбор тем доступен только владельцам статуса 🌟 VIP+!\nПриобретите статус: «купить вип+»", show_alert=True)

    theme = await db.get_vip_theme(call.from_user.id)
    text = (
        f"🎨 <b>VIP Меню — Выбор темы оформления</b>\n\n"
        f"Ваш статус: <b>{vip_badge_str(lvl)}</b>\n"
        f"Выберите желаемый цветовой стиль сообщений и акцентов:"
    )
    await call.message.edit_text(text, reply_markup=vip_theme_keyboard(theme))
    await call.answer()


@router.callback_query(F.data.startswith("vip_set_theme:"))
async def cb_vip_set_theme(call: CallbackQuery):
    theme_key = call.data.split(":")[1]
    lvl, until, active = await db.get_vip_info(call.from_user.id)
    if not active or lvl < 2:
        return await call.answer("🔒 Темы оформления доступны только для пользователей со статусом 🌟 VIP+!", show_alert=True)

    if theme_key not in VIP_THEMES:
        return await call.answer()

    await db.set_vip_theme(call.from_user.id, theme_key)
    theme_name = VIP_THEMES[theme_key][0]
    await call.message.edit_reply_markup(reply_markup=vip_theme_keyboard(theme_key))
    await call.answer(f"✅ Установлена тема: {theme_name}", show_alert=True)


@router.callback_query(F.data == "vip_close")
async def cb_vip_close(call: CallbackQuery):
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer()


# ---------- Административные команды управления VIP ----------

@router.message(Cmd("выдать вип", "дать вип", "выдать vip", "дать vip",
                    "выдать вип+", "дать вип+", "выдать vip+", "дать vip+",
                    "+вип", "+vip", "+вип+", "+vip+",
                    section=S_VIP, rank=6,
                    usage="выдать вип {ссылка} [срок] [1|2]", desc="Выдать VIP / VIP+"))
async def cmd_give_vip(message: Message, bot: Bot, args: str = "", **kw):
    import config
    from core_ranks import effective_rank
    have = await effective_rank(message, bot)
    is_admin = bool(message.from_user and (message.from_user.id == config.OWNER_ID or message.from_user.id in config.ADMINS))
    if have < 6 and not is_admin:
        return await message.reply("🔒 <b>Выдавать статус VIP могут только технические администраторы и создатели!</b>")

    uid, name, rest = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply(
            "Укажите пользователя: <code>выдать вип @user [срок]</code> или <code>выдать вип+ @user [срок]</code>")

    # Проверяем, была ли вызвана команда с плюсом (VIP+)
    msg_cmd = (message.text or "").split()[0].lower() if message.text else ""
    default_lvl = 2 if ("+" in msg_cmd or "vip+" in msg_cmd or "вип+" in msg_cmd) else 1

    level = default_lvl
    parts = rest.split()
    clean_parts = []
    for p in parts:
        p_low = p.lower()
        if p_low in ("1", "vip", "вип"):
            level = 1
        elif p_low in ("2", "vip+", "вип+", "плюс", "plus"):
            level = 2
        else:
            clean_parts.append(p)

    period_str = " ".join(clean_parts)
    secs, _ = parse_period(period_str)
    secs = secs or 30 * 86400

    until = int(time.time()) + secs
    await db.set_vip(uid, until, level)

    lvl_name = "🌟 VIP+" if level == 2 else "⭐️ VIP"
    await message.reply(
        f"💎 {mention_id(uid, name)} получил статус <b>{lvl_name}</b> на <b>{human_period(secs)}</b>!\n"
        f"До: {time.strftime('%d.%m.%Y %H:%M', time.localtime(until))}")


@router.message(Cmd("снять вип", "забрать вип", "снять vip", "забрать vip",
                    "снять вип+", "забрать вип+", "снять vip+", "забрать vip+",
                    "-вип", "-vip", "-вип+", "-vip+",
                    section=S_VIP, rank=6,
                    usage="снять вип {ссылка}", desc="Снять статус VIP / VIP+"))
async def cmd_remove_vip(message: Message, bot: Bot, args: str = "", **kw):
    import config
    from core_ranks import effective_rank
    have = await effective_rank(message, bot)
    is_admin = bool(message.from_user and (message.from_user.id == config.OWNER_ID or message.from_user.id in config.ADMINS))
    if have < 6 and not is_admin:
        return await message.reply("🔒 <b>Снимать статус VIP могут только технические администраторы и создатели!</b>")

    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя: <code>снять вип @user</code>")

    await db.remove_vip(uid)
    await message.reply(f"⚪️ Статус VIP снят с {mention_id(uid, name)}.")

