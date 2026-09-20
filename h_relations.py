"""Модуль отношений и браков (ОТН): 1 в 1 как в Ирисе.

Включает:
- Создание отношений, брак, развод
- Прокачка отношений по уровням (1-8) с 15 уникальными действиями и таймерами
- VIP и VIP+ бонусы к очкам любви (+25% и +50%)
- Механика «Обида» и «Задобрить» (1-15 баллов каждые 5 мин до 100)
- Совместное имущество и покупка за ириски
- Дети (рождение, уход)
- Интерактивное Inline-меню («отн меню»)
"""
from __future__ import annotations

import html
import random
import time
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import db
from core_registry import Cmd
from core_resolve import human_period, resolve_target
from utils import mention, mention_id, parse_amount

router = Router(name="relations")
S_REL = 20

# --- Каталог действий прокачки отношений ---
# key: (название, эмодзи, xp, цена_ирисок, кд_секунд, мин_уровень, глагол)
REL_ACTIONS = {
    "комплимент": ("Сделать комплимент", "💬", 5, 3, 600, 1, "делает нежный комплимент для"),
    "анекдот": ("Рассказать анекдот", "😄", 10, 5, 900, 1, "рассказывает смешной анекдот для"),
    "еда": ("Поделиться едой", "🍟", 20, 10, 1200, 2, "делится вкусной едой с"),
    "мем": ("Кинуть мем", "🖼", 20, 10, 1200, 2, "присылает отборный мем для"),
    "поговорить": ("Поговорить", "💭", 30, 15, 1200, 3, "мило беседует с"),
    "обнимать": ("Обнимать (подарок)", "🤗", 30, 15, 1200, 3, "крепко обнимает"),
    "шоколад": ("Подарить шоколадку", "🍫", 50, 25, 1800, 4, "дарит вкусную шоколадку для"),
    "погулять": ("Пригласить погулять", "🚶", 70, 35, 2700, 4, "идёт на романтическую прогулку с"),
    "завтрак": ("Сделать завтрак", "🍳", 100, 50, 3600, 5, "готовит потрясающий завтрак для"),
    "конфеты": ("Подарить конфеты", "🍬", 100, 50, 3600, 5, "дарит коробку сладких конфет"),
    "кино": ("Сходить в кино", "🎬", 200, 100, 7200, 6, "идёт на вечерний киносеанс с"),
    "душа": ("Поговорить по душам", "💞", 300, 150, 10800, 6, "говорит по душам под звёздами с"),
    "клуб": ("Пригласить в клуб", "🎶", 500, 238, 18000, 7, "зажигает в ночном клубе с"),
    "сюрприз": ("Устроить сюрприз", "🎊", 750, 356, 28800, 7, "устраивает грандиозный сюрприз для"),
    "подарок": ("Сделать большой подарок", "🎁", 3000, 1350, 86400, 8, "вручает роскошный подарок"),
}

# Синонимы действий
ACTION_ALIASES = {
    "сделать комплимент": "комплимент",
    "рассказать анекдот": "анекдот",
    "поделиться едой": "еда",
    "кинуть мем": "мем",
    "мемы": "мем",
    "поговорить": "поговорить",
    "обнимашки": "обнимать",
    "шоколадка": "шоколад",
    "подарить шоколадку": "шоколад",
    "гулять": "погулять",
    "пригласить погулять": "погулять",
    "сделать завтрак": "завтрак",
    "подарить конфеты": "конфеты",
    "сходить в кино": "кино",
    "по душам": "душа",
    "поговорить по душам": "душа",
    "пригласить в клуб": "клуб",
    "тусовка": "клуб",
    "устроить сюрприз": "сюрприз",
    "большой подарок": "подарок",
    "сделать подарок": "подарок",
}

# --- Каталог совместного имущества ---
PROPERTY_CATALOG = {
    "flat": ("Квартира-студия", "🏢", 5000, 1),
    "apartment": ("Элитные апартаменты", "🏙", 15000, 2),
    "house": ("Загородный коттедж", "🏡", 50000, 3),
    "villa": ("Вилла у океана", "🏰", 150000, 4),
    "sportcar": ("Спорткар Porsche", "🏎", 300000, 5),
    "yacht": ("Белоснежная яхта", "🛥", 600000, 6),
    "factory": ("Завод ирисок", "🏭", 1500000, 7),
    "island": ("Тропический остров", "🏝", 5000000, 8),
}


def progress_bar(current: int, total: int, length: int = 10) -> str:
    if total <= 0:
        return "░" * length
    filled = min(length, max(0, int((current / total) * length)))
    return "█" * filled + "░" * (length - filled)


def get_other_id(rel: dict, uid: int) -> int:
    return rel["user2_id"] if rel["user1_id"] == uid else rel["user1_id"]


async def format_rel_card(rel: dict, bot: Bot) -> str:
    u1 = await db.get_user(rel["user1_id"])
    u2 = await db.get_user(rel["user2_id"])
    name1 = u1["first_name"] or str(rel["user1_id"])
    name2 = u2["first_name"] or str(rel["user2_id"])

    days = max(1, int((time.time() - rel["created_at"]) // 86400))
    lvl = rel["level"]
    xp = rel["xp"]
    next_xp = db.REL_LEVELS.get(lvl + 1)

    if next_xp:
        prev_xp = db.REL_LEVELS.get(lvl, 0)
        curr_lvl_xp = xp - prev_xp
        need_lvl_xp = next_xp - prev_xp
        bar = progress_bar(curr_lvl_xp, need_lvl_xp, 10)
        xp_line = f"✨ Опыт: <b>{xp}</b> / <b>{next_xp}</b> любви\n[{bar}] {curr_lvl_xp}/{need_lvl_xp}"
    else:
        bar = "█" * 10
        xp_line = f"✨ Опыт: <b>{xp}</b> любви (Максимальный уровень!)\n[{bar}] MAX"

    status_line = "💍 <b>Счастливы вместе</b>"
    if rel["offended_by"]:
        offended_user = await db.get_user(rel["offended_by"])
        off_name = offended_user["first_name"] or str(rel["offended_by"])
        s_pts = rel["soothe_points"]
        s_bar = progress_bar(s_pts, 100, 8)
        status_line = (f"💔 <b>Обида!</b> {mention_id(rel['offended_by'], off_name)} обижен(а).\n"
                       f"🕊 Задобрить: [{s_bar}] <b>{s_pts}/100</b> очков")

    # Имущество
    props = await db.get_rel_properties(rel["id"])
    if props:
        prop_str = " · ".join(f"{p['item_name']}" for p in props)
    else:
        prop_str = "<i>Пока нет совместного имущества</i>"

    # Дети
    children = await db.get_rel_children(rel["id"])
    if children:
        c_list = ", ".join(f"{c['name']} ({c['gender']})" for c in children)
    else:
        c_list = "<i>Пока нет детей</i>"

    text = (
        f"💖 <b>Отношения пары</b> 💖\n\n"
        f"👩‍❤️‍👨 <b>{mention_id(rel['user1_id'], name1)}</b>  ➕  "
        f"<b>{mention_id(rel['user2_id'], name2)}</b>\n"
        f"▫️ Статус: {status_line}\n"
        f"▫️ Вместе: <b>{days} дн.</b> (с {time.strftime('%d.%m.%Y', time.localtime(rel['created_at']))})\n"
        f"▫️ Уровень любви: <b>Уровень {lvl}</b> 🏆\n"
        f"{xp_line}\n\n"
        f"🏠 <b>Совместное имущество:</b>\n{prop_str}\n\n"
        f"👶 <b>Дети пары:</b>\n{c_list}\n\n"
        f"💡 <i>Используйте <code>отн меню</code> для управления парой и прокачки!</i>"
    )
    return text


def rel_main_keyboard(rel_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📜 Доступные действия", callback_data=f"rel_ui:acts:{rel_id}"),
            InlineKeyboardButton(text="🏠 Имущество", callback_data=f"rel_ui:prop:{rel_id}"),
        ],
        [
            InlineKeyboardButton(text="👶 Дети", callback_data=f"rel_ui:kids:{rel_id}"),
            InlineKeyboardButton(text="🛍 Магазин пары", callback_data=f"rel_ui:shop:{rel_id}"),
        ],
        [
            InlineKeyboardButton(text="❌ Закрыть", callback_data="rel_ui:close"),
        ]
    ])


# ================== КОМАНДЫ ОТНОШЕНИЙ ==================

@router.message(Cmd("отн", "брак", "отношения", "пара", "love", section=S_REL,
                    usage="отн [@юзер]", desc="Отношения / сделать предложение"))
async def cmd_rel_main(message: Message, bot: Bot, args: str = "", **kw):
    me_id = message.from_user.id
    rel = await db.get_relationship(me_id)

    # Если есть аргументы или реплай — делаем предложение
    uid, name, _ = await resolve_target(message, args, bot)
    if uid:
        if uid == me_id:
            return await message.reply("Нельзя вступить в отношения с самим собой 🙂")
        if rel:
            return await message.reply("Вы уже состоите в отношениях! Сначала нужно расторгнуть текущие: <code>развод</code>.")
        target_rel = await db.get_relationship(uid)
        if target_rel:
            return await message.reply(f"💔 {mention_id(uid, name)} уже состоит в отношениях с другим пользователем.")

        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💍 Согласен(на)", callback_data=f"rel_prop:yes:{me_id}:{uid}"),
            InlineKeyboardButton(text="💔 Отказ", callback_data=f"rel_prop:no:{me_id}:{uid}")
        ]])
        return await message.reply(
            f"💍 {mention(message.from_user)} делает предложение {mention_id(uid, name)} "
            f"вступить в отношения!\n\nЧто ответит избранник?",
            reply_markup=kb)

    # Если нет аргументов и нет отношений:
    if not rel:
        return await message.reply(
            "❌ <b>У вас нет отношений.</b>\n\n"
            "Вступите в отношения, чтобы открыть возможности пары, совместную прокачку, "
            "имущество и семью!\n\n"
            "💡 <b>Как сделать предложение:</b>\n"
            "• Ответьте на сообщение избранника: <code>отн</code> или <code>брак</code>\n"
            "• Или напишите: <code>отн @username</code>",
            disable_web_page_preview=True)

    # Если отношения есть — выводим карточку
    card = await format_rel_card(rel, bot)
    await message.reply(card, reply_markup=rel_main_keyboard(rel["id"]), disable_web_page_preview=True)


@router.message(Cmd("отн меню", "меню отн", "меню пары", section=S_REL,
                    usage="отн меню", desc="Интерактивное меню отношений"))
async def cmd_rel_menu(message: Message, bot: Bot, **kw):
    me_id = message.from_user.id
    rel = await db.get_relationship(me_id)
    if not rel:
        return await message.reply(
            "❌ <b>У вас нет отношений.</b>\nВступите в отношения командой: <code>отн @юзер</code>")
    card = await format_rel_card(rel, bot)
    await message.reply(card, reply_markup=rel_main_keyboard(rel["id"]), disable_web_page_preview=True)


@router.callback_query(F.data.startswith("rel_prop:"))
async def cb_proposal(call: CallbackQuery, bot: Bot):
    _, act, from_id_s, to_id_s = call.data.split(":")
    from_id, to_id = int(from_id_s), int(to_id_s)

    if call.from_user.id != to_id:
        return await call.answer("Это предложение адресовано не вам! 🤫", show_alert=True)

    if act == "no":
        await call.message.edit_text("💔 Предложение отклонено. Сердце разбито...")
        return await call.answer()

    # Проверяем, не успел ли кто-то вступить в другие отношения
    if await db.get_relationship(from_id) or await db.get_relationship(to_id):
        await call.message.edit_text("⚠️ Один из участников уже находится в отношениях.")
        return await call.answer()

    rel_id = await db.create_relationship(from_id, to_id)
    u1 = await db.get_user(from_id)
    u2 = await db.get_user(to_id)
    n1 = u1["first_name"] or str(from_id)
    n2 = u2["first_name"] or str(to_id)

    await call.message.edit_text(
        f"🎉 <b>Горько!</b> 🎉\n\n"
        f"💍 <b>{mention_id(from_id, n1)}</b> и <b>{mention_id(to_id, n2)}</b> "
        f"теперь официально в отношениях!\n\n"
        f"Вам открыт <b>1-й уровень пары</b>! Используйте <code>отн меню</code>, "
        f"делайте комплименты и дарите подарки, чтобы развивать союз! ❤️",
        reply_markup=rel_main_keyboard(rel_id))
    await call.answer("Поздравляем с созданием союза! 💍", show_alert=True)


@router.message(Cmd("развод", "отн развод", "расторгнуть", "расстаться", section=S_REL,
                    usage="развод", desc="Расторгнуть отношения"))
async def cmd_divorce(message: Message, **kw):
    me_id = message.from_user.id
    rel = await db.get_relationship(me_id)
    if not rel:
        return await message.reply("Вы не состоите в отношениях.")

    other_id = get_other_id(rel, me_id)
    partner = await db.get_user(other_id)
    pname = partner["first_name"] or str(other_id)

    await db.delete_relationship(rel["id"])
    await message.reply(
        f"💔 <b>Отношения расторгнуты.</b>\n\n"
        f"{mention(message.from_user)} и {mention_id(other_id, pname)} больше не вместе. "
        f"Все совместные вещи и достижения аннулированы.")


# ================== ПРОКАЧКА ОТНОШЕНИЙ ==================

async def process_rel_action(message: Message, bot: Bot, action_key: str):
    me_id = message.from_user.id
    rel = await db.get_relationship(me_id)
    if not rel:
        return await message.reply(
            "❌ <b>У вас нет отношений.</b>\nВступите в отношения командой: <code>отн @юзер</code>")

    other_id = get_other_id(rel, me_id)
    partner = await db.get_user(other_id)
    pname = partner["first_name"] or str(other_id)

    # Проверка обиды
    if rel["offended_by"] == other_id:
        return await message.reply(
            f"💔 <b>Ваш партнер обижен на вас!</b>\n\n"
            f"{mention_id(other_id, pname)} обижается, поэтому романтические действия заблокированы.\n"
            f"Вам нужно задобрить свою вторую половинку: <code>отн задобрить</code> (раз в 5 мин)!")

    action_info = REL_ACTIONS.get(action_key)
    if not action_info:
        return

    name, emoji, xp, cost, cd, min_lvl, verb = action_info

    # Проверка уровня
    if rel["level"] < min_lvl:
        return await message.reply(
            f"🔒 <b>Действие недоступно</b>\n\n"
            f"{emoji} «{name}» открывается с <b>{min_lvl} уровня</b> отношений.\n"
            f"Ваш текущий уровень: <b>{rel['level']}</b>. Прокачивайте пару другими действиями!")

    # Проверка кулдауна
    left = await db.get_rel_cooldown_left(rel["id"], me_id, action_key, cd)
    if left > 0:
        return await message.reply(
            f"⏳ {emoji} <b>{name}</b> уже было недавно.\n"
            f"Подождите ещё <b>{human_period(left)}</b> перед повтором.")

    # Проверка баланса
    user = await db.get_user(me_id)
    if user["balance"] < cost:
        return await message.reply(
            f"🍬 Не хватает ирисок для действия «{name}»!\n"
            f"Требуется: <b>{cost} 🪙</b>, у вас: <b>{user['balance']} 🪙</b>.\n"
            f"Заработайте ириски командой <code>работа</code>!")

    # Списываем баланс и ставим кулдаун
    await db.add_balance(me_id, -cost, f"rel_{action_key}")
    await db.set_rel_cooldown(rel["id"], me_id, action_key)

    # Рассчитываем XP с учетом VIP бонусов
    vip_lvl, _, vip_active = await db.get_vip_info(me_id)
    bonus_xp = 0
    vip_badge = ""
    if vip_active:
        if vip_lvl >= 2:
            bonus_xp = int(xp * 0.50)  # +50% для VIP+
            vip_badge = " <i>(+50% VIP+ бонус)</i>"
        elif vip_lvl >= 1:
            bonus_xp = int(xp * 0.25)  # +25% для VIP
            vip_badge = " <i>(+25% VIP бонус)</i>"

    earned_xp = xp + bonus_xp
    new_xp, new_lvl, lvl_up = await db.add_rel_xp(rel["id"], earned_xp)

    reply_text = (
        f"{emoji} {mention(message.from_user)} {verb} {mention_id(other_id, pname)}!\n\n"
        f"💖 Получено: <b>+{earned_xp} любви</b>{vip_badge}\n"
        f"🍬 Потрачено: <b>{cost} 🪙</b>\n"
        f"✨ Всего любви: <b>{new_xp}</b> (Уровень {new_lvl})"
    )

    if lvl_up:
        reply_text += (
            f"\n\n🎊 <b>УРОВЕНЬ ОТНОШЕНИЙ ПОВЫШЕН ДО {new_lvl}!</b> 🎊\n"
            f"Вам открылись новые романтические действия и возможности в <code>отн меню</code>! 💖"
        )

    await message.reply(reply_text)


# Регистрация команд действий
@router.message(Cmd("комплимент", "отн комплимент", section=S_REL, usage="комплимент", desc="Сделать комплимент (+5 любви)"))
async def cmd_act_compliment(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "комплимент")

@router.message(Cmd("анекдот", "отн анекдот", section=S_REL, usage="анекдот", desc="Рассказать анекдот (+10 любви)"))
async def cmd_act_joke(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "анекдот")

@router.message(Cmd("еда", "отн еда", "поделиться едой", section=S_REL, usage="еда", desc="Поделиться едой (+20 любви)"))
async def cmd_act_food(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "еда")

@router.message(Cmd("мем", "отн мем", "кинуть мем", section=S_REL, usage="мем", desc="Кинуть мем (+20 любви)"))
async def cmd_act_meme(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "мем")

@router.message(Cmd("поговорить", "отн поговорить", section=S_REL, usage="поговорить", desc="Поговорить (+30 любви)"))
async def cmd_act_talk(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "поговорить")

@router.message(Cmd("шоколад", "отн шоколад", "подарить шоколадку", section=S_REL, usage="шоколад", desc="Подарить шоколадку (+50 любви)"))
async def cmd_act_choco(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "шоколад")

@router.message(Cmd("погулять", "отн погулять", "прогулка", section=S_REL, usage="погулять", desc="Пригласить погулять (+70 любви)"))
async def cmd_act_walk(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "погулять")

@router.message(Cmd("завтрак", "отн завтрак", "сделать завтрак", section=S_REL, usage="завтрак", desc="Сделать завтрак (+100 любви)"))
async def cmd_act_breakfast(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "завтрак")

@router.message(Cmd("конфеты", "отн конфеты", "подарить конфеты", section=S_REL, usage="конфеты", desc="Подарить конфеты (+100 любви)"))
async def cmd_act_sweets(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "конфеты")

@router.message(Cmd("кино", "отн кино", "сходить в кино", section=S_REL, usage="кино", desc="Сходить в кино (+200 любви)"))
async def cmd_act_cinema(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "кино")

@router.message(Cmd("душа", "отн душа", "по душам", section=S_REL, usage="душа", desc="Поговорить по душам (+300 любви)"))
async def cmd_act_soul(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "душа")

@router.message(Cmd("клуб", "отн клуб", "пригласить в клуб", section=S_REL, usage="клуб", desc="Пригласить в клуб (+500 любви)"))
async def cmd_act_club(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "клуб")

@router.message(Cmd("сюрприз", "отн сюрприз", "устроить сюрприз", section=S_REL, usage="сюрприз", desc="Устроить сюрприз (+750 любви)"))
async def cmd_act_surprise(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "сюрприз")

@router.message(Cmd("подарок", "отн подарок", "большой подарок", section=S_REL, usage="подарок", desc="Сделать большой подарок (+3000 любви)"))
async def cmd_act_gift(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "подарок")


# ================== ОБИДА И ЗАДОБРИТЬ ==================

@router.message(Cmd("отн обида", "обида", "обидеться", section=S_REL,
                    usage="отн обида", desc="Объявить обиду на партнера"))
async def cmd_offense(message: Message, bot: Bot, **kw):
    me_id = message.from_user.id
    rel = await db.get_relationship(me_id)
    if not rel:
        return await message.reply("❌ У вас нет отношений.")

    other_id = get_other_id(rel, me_id)
    partner = await db.get_user(other_id)
    pname = partner["first_name"] or str(other_id)

    if rel["offended_by"] == me_id:
        return await message.reply("Вы уже обижены на партнёра. Пусть он вас задобрит: <code>отн задобрить</code>!")

    await db.set_rel_offended(rel["id"], me_id)
    await message.reply(
        f"💔 <b>Обида объявлена!</b>\n\n"
        f"{mention(message.from_user)} обиделся(лась) на {mention_id(other_id, pname)}.\n"
        f"Все романтические действия и ласки приостановлены, пока партнер не наберет "
        f"<b>100 баллов</b> через команду <code>отн задобрить</code> (раз в 5 минут) "
        f"или пока вы не напишете <code>отн простить</code>!")


@router.message(Cmd("отн задобрить", "задобрить", section=S_REL,
                    usage="отн задобрить", desc="Задобрить обиженного партнера (раз в 5 мин)"))
async def cmd_soothe(message: Message, bot: Bot, **kw):
    me_id = message.from_user.id
    rel = await db.get_relationship(me_id)
    if not rel:
        return await message.reply("❌ У вас нет отношений.")

    other_id = get_other_id(rel, me_id)
    partner = await db.get_user(other_id)
    pname = partner["first_name"] or str(other_id)

    if not rel["offended_by"]:
        return await message.reply("🕊 На вас никто не обижен! Всё прекрасно.")

    if rel["offended_by"] == me_id:
        return await message.reply("Вы сами обижены на партнёра. Задабривать должен он 🙂")

    # Кулдаун 5 минут (300 секунд)
    now = int(time.time())
    last_soothe = rel["soothe_last_ts"] or 0
    passed = now - last_soothe
    if passed < 300:
        rem = 300 - passed
        return await message.reply(f"⏳ Задабривать можно раз в 5 минут! Подождите ещё <b>{human_period(rem)}</b>.")

    gained = random.randint(1, 15)
    total, cleared = await db.soothe_rel(rel["id"], gained)

    if cleared:
        # Бонус за примирение
        await db.add_rel_xp(rel["id"], 50)
        return await message.reply(
            f"🎉 <b>УРА! ВЫ ПОМИРИЛИСЬ!</b> 🎉\n\n"
            f"💖 {mention(message.from_user)} успешно задобрил(а) {mention_id(other_id, pname)}, "
            f"набрав 100/100 баллов!\n"
            f"✨ Обида снята, романтические действия снова доступны (+50 любви бонусом)!")

    bar = progress_bar(total, 100, 10)
    methods = [
        "принёс любимый кофе с круассаном",
        "сказал самые искренние и тёплые слова",
        "подарил милую открытку с извинениями",
        "сделал массаж плеч и налил горячий чай",
        "включил любимый плейлист",
        "признался во всех ошибках и обнял",
    ]
    method = random.choice(methods)

    await message.reply(
        f"🕊 {mention(message.from_user)} {method} для {mention_id(other_id, pname)}!\n\n"
        f"➕ Получено: <b>+{gained} баллов</b>\n"
        f"📊 Прогресс примирения: [{bar}] <b>{total}/100</b>\n"
        f"⏱ Следующая попытка через 5 минут.")


@router.message(Cmd("отн простить", "простить", section=S_REL,
                    usage="отн простить", desc="Простить партнера и снять обиду"))
async def cmd_forgive(message: Message, bot: Bot, **kw):
    me_id = message.from_user.id
    rel = await db.get_relationship(me_id)
    if not rel:
        return await message.reply("❌ У вас нет отношений.")

    other_id = get_other_id(rel, me_id)
    partner = await db.get_user(other_id)
    pname = partner["first_name"] or str(other_id)

    if rel["offended_by"] != me_id:
        return await message.reply("Вы не объявляли обиду.")

    await db.set_rel_offended(rel["id"], None)
    await message.reply(
        f"❤️ <b>Мир и любовь!</b>\n\n"
        f"{mention(message.from_user)} простил(а) {mention_id(other_id, pname)}! "
        f"Обида снята, романтические действия разблокированы.")


# ================== ИМУЩЕСТВО И ДЕТИ ==================

@router.message(Cmd("отн купить", "купить имущество", section=S_REL,
                    usage="отн купить {название}", desc="Купить совместное имущество"))
async def cmd_buy_property(message: Message, bot: Bot, args: str = "", **kw):
    me_id = message.from_user.id
    rel = await db.get_relationship(me_id)
    if not rel:
        return await message.reply("❌ У вас нет отношений.")

    target = (args or "").strip().lower()
    found_key = None
    for k, (name, _, _, _) in PROPERTY_CATALOG.items():
        if target == k or target in name.lower() or name.lower() in target:
            found_key = k
            break

    if not found_key:
        lines = [f"• <code>отн купить {k}</code> — {e} {n} (<b>{p:,} 🪙</b>, Ур. {l})"
                 for k, (n, e, p, l) in PROPERTY_CATALOG.items()]
        return await message.reply(
            "🛍 <b>Каталог совместного имущества:</b>\n\n" + "\n".join(lines))

    name, emoji, price, req_lvl = PROPERTY_CATALOG[found_key]
    if rel["level"] < req_lvl:
        return await message.reply(f"🔒 «{name}» доступно только с <b>{req_lvl} уровня</b> пары (у вас {rel['level']}).")

    props = await db.get_rel_properties(rel["id"])
    if any(p["item_key"] == found_key for p in props):
        return await message.reply(f"У вашей пары уже есть {emoji} <b>{name}</b>!")

    user = await db.get_user(me_id)
    if user["balance"] < price:
        return await message.reply(f"🍬 Не хватает ирисок: нужно <b>{price:,} 🪙</b>, у вас <b>{user['balance']:,} 🪙</b>.")

    await db.add_balance(me_id, -price, f"buy_{found_key}")
    await db.add_rel_property(rel["id"], found_key, f"{emoji} {name}", price)
    await db.add_rel_xp(rel["id"], price // 20)

    other_id = get_other_id(rel, me_id)
    partner = await db.get_user(other_id)
    pname = partner["first_name"] or str(other_id)

    await message.reply(
        f"🎉 <b>Поздравляем с покупкой!</b> 🎉\n\n"
        f"{mention(message.from_user)} приобрёл(а) {emoji} <b>{name}</b> в совместное владение "
        f"с {mention_id(other_id, pname)} за <b>{price:,} 🪙</b>!\n"
        f"💖 Получено <b>+{price // 20} любви</b> за крупное приобретение!")


@router.message(Cmd("отн ребенок", "завести ребенка", section=S_REL,
                    usage="отн ребенок {имя}", desc="Завести совместного ребенка"))
async def cmd_have_child(message: Message, bot: Bot, args: str = "", **kw):
    me_id = message.from_user.id
    rel = await db.get_relationship(me_id)
    if not rel:
        return await message.reply("❌ У вас нет отношений.")

    if rel["level"] < 3:
        return await message.reply("🔒 Завести ребёнка можно только с <b>3 уровня отношений</b>!")

    child_name = (args or "").strip()
    if not child_name:
        return await message.reply("Укажите имя ребенка: <code>отн ребенок Максим</code>")

    gender = random.choice(["👦 Мальчик", "👧 Девочка"])
    await db.add_rel_child(rel["id"], child_name[:32], gender)
    await db.add_rel_xp(rel["id"], 150)

    other_id = get_other_id(rel, me_id)
    partner = await db.get_user(other_id)
    pname = partner["first_name"] or str(other_id)

    await message.reply(
        f"🍼 <b>В семье пополнение!</b> 🍼\n\n"
        f"У {mention(message.from_user)} и {mention_id(other_id, pname)} родился {gender} "
        f"по имени <b>{html.escape(child_name)}</b>!\n"
        f"💖 +150 очков любви к отношениям!")


# ================== ОБРАБОТЧИКИ INLINE UI ==================

@router.callback_query(F.data.startswith("rel_ui:"))
async def cb_rel_ui(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    action = parts[1]

    if action == "close":
        try:
            await call.message.delete()
        except Exception:
            pass
        return await call.answer()

    rel_id = int(parts[2])
    rel = await db.get_rel_by_id(rel_id)
    if not rel:
        return await call.answer("Отношения не найдены.", show_alert=True)

    if call.from_user.id not in (rel["user1_id"], rel["user2_id"]):
        return await call.answer("Это меню чужой пары! 🔒", show_alert=True)

    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data=f"rel_ui:main:{rel_id}")]
    ])

    if action == "main":
        text = await format_rel_card(rel, bot)
        await call.message.edit_text(text, reply_markup=rel_main_keyboard(rel_id), disable_web_page_preview=True)
        return await call.answer()

    elif action == "acts":
        # Список доступных действий по уровням
        lines = [f"📜 <b>Доступные действия пары (Ваш Ур. {rel['level']}):</b>\n"]
        for k, (name, emoji, xp, cost, cd, lvl, _) in REL_ACTIONS.items():
            status = "✅" if rel["level"] >= lvl else f"🔒 (с {lvl} ур.)"
            left = await db.get_rel_cooldown_left(rel_id, call.from_user.id, k, cd)
            cd_s = f"⏳ {human_period(left)}" if left > 0 else "🟢 Готово"
            lines.append(f"{status} {emoji} <b>{name}</b> (+{xp} любви)\n   🍬 {cost} 🪙 · {human_period(cd)} · {cd_s}")

        await call.message.edit_text("\n".join(lines), reply_markup=back_kb)
        return await call.answer()

    elif action == "prop":
        props = await db.get_rel_properties(rel_id)
        if not props:
            text = ("🏠 <b>Совместное имущество пары</b>\n\n"
                    "У вас пока нет купленного имущества.\n"
                    "Загляните в 🛍 <b>Магазин пары</b>, чтобы приобрести недвижимость или транспорт!")
        else:
            lines = ["🏠 <b>Совместное имущество пары:</b>\n"]
            for p in props:
                d = time.strftime('%d.%m.%Y', time.localtime(p['bought_at']))
                lines.append(f"• {p['item_name']} — куплено {d} за {p['price']:,} 🪙")
            text = "\n".join(lines)
        await call.message.edit_text(text, reply_markup=back_kb)
        return await call.answer()

    elif action == "kids":
        kids = await db.get_rel_children(rel_id)
        if not kids:
            text = ("👶 <b>Дети пары</b>\n\n"
                    "У вашей пары пока нет детей.\n"
                    "С 3-го уровня отношений вы можете завести ребенка командой:\n"
                    "<code>отн ребенок [Имя]</code>")
        else:
            lines = ["👶 <b>Дети вашей семьи:</b>\n"]
            for k in kids:
                days = max(1, int((time.time() - k["born_at"]) // 86400))
                lines.append(f"• {k['gender']} <b>{k['name']}</b> — возраст: {days} дн.")
            text = "\n".join(lines)
        await call.message.edit_text(text, reply_markup=back_kb)
        return await call.answer()

    elif action == "shop":
        lines = ["🛍 <b>Магазин имущества для пар</b>\n"]
        for k, (n, e, p, l) in PROPERTY_CATALOG.items():
            avail = "✅ Доступно" if rel["level"] >= l else f"🔒 С {l} ур."
            lines.append(f"{e} <b>{n}</b> — <b>{p:,} 🪙</b> ({avail})\n   Купить: <code>отн купить {k}</code>")
        await call.message.edit_text("\n".join(lines), reply_markup=back_kb)
        return await call.answer()
