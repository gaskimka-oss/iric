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
# key: (название, эмодзи, xp, цена_монет, кд_секунд, мин_уровень, глагол)
REL_ACTIONS = {
    "комплимент": ("Сделать комплимент", "💬", 5, 3, 600, 1, "делает нежный комплимент для"),
    "анекдот": ("Рассказать анекдот", "😄", 10, 5, 900, 1, "рассказывает смешной анекдот для"),
    "еда": ("Поделиться едой", "🍟", 20, 10, 1200, 2, "делится вкусной едой с"),
    "мем": ("Кинуть мем", "🖼", 20, 10, 1200, 2, "присылает отборный мем для"),
    "поговорить": ("Поговорить", "💭", 30, 15, 1200, 3, "мило беседует с"),
    "обнимать": ("Обнимать", "🤗", 30, 15, 1200, 3, "крепко обнимает"),
    "шоколад": ("Подарить шоколадку", "🍫", 50, 25, 1800, 4, "дарит вкусную шоколадку для"),
    "погулять": ("Пригласить погулять", "🚶", 70, 35, 2700, 4, "идёт на прогулку с"),
    "завтрак": ("Сделать завтрак", "🍳", 100, 50, 3600, 5, "готовит потрясающий завтрак для"),
    "конфеты": ("Подарить конфеты", "🍬", 100, 50, 3600, 5, "дарит коробку сладких конфет для"),
    "цветы": ("Подарить цветы", "💐", 150, 75, 5400, 5, "дарит роскошный букет цветов для"),
    "кино": ("Сходить в кино", "🎬", 200, 100, 7200, 6, "идёт на киносеанс с"),
    "душа": ("Поговорить по душам", "💞", 300, 150, 10800, 6, "говорит по душам под звёздами с"),
    "клуб": ("Пригласить в клуб", "🎶", 500, 238, 18000, 7, "зажигает в ночном клубе с"),
    "сюрприз": ("Устроить сюрприз", "🎊", 750, 356, 28800, 7, "устраивает грандиозный сюрприз для"),
    "подарок": ("Сделать большой подарок", "🎁", 3000, 1350, 86400, 8, "вручает роскошный подарок для"),
}

# Синонимы действий
ACTION_ALIASES = {
    "сделать комплимент": "комплимент",
    "комплимент": "комплимент",
    "похвалить": "комплимент",
    "отн комплимент": "комплимент",
    "рассказать анекдот": "анекдот",
    "анекдот": "анекдот",
    "шутка": "анекдот",
    "пошутить": "анекдот",
    "отн анекдот": "анекдот",
    "поделиться едой": "еда",
    "еда": "еда",
    "покормить": "еда",
    "угостить": "еда",
    "отн еда": "еда",
    "кинуть мем": "мем",
    "мем": "мем",
    "мемы": "мем",
    "мемчик": "мем",
    "скинуть мем": "мем",
    "отн мем": "мем",
    "поговорить": "поговорить",
    "поболтать": "поговорить",
    "беседа": "поговорить",
    "отн поговорить": "поговорить",
    "обнимашки": "обнимать",
    "обнимать": "обнимать",
    "обнять": "обнимать",
    "крепко обнять": "обнимать",
    "отн обнять": "обнимать",
    "шоколадка": "шоколад",
    "шоколад": "шоколад",
    "подарить шоколадку": "шоколад",
    "подарить шоколад": "шоколад",
    "отн шоколад": "шоколад",
    "гулять": "погулять",
    "погулять": "погулять",
    "прогулка": "погулять",
    "пригласить погулять": "погулять",
    "пойдем гулять": "погулять",
    "пойти гулять": "погулять",
    "отн погулять": "погулять",
    "отн гулять": "погулять",
    "сделать завтрак": "завтрак",
    "завтрак": "завтрак",
    "приготовить завтрак": "завтрак",
    "отн завтрак": "завтрак",
    "подарить конфеты": "конфеты",
    "конфеты": "конфеты",
    "конфетка": "конфеты",
    "отн конфеты": "конфеты",
    "подарить цветы": "цветы",
    "цветы": "цветы",
    "букет": "цветы",
    "подарить букет": "цветы",
    "розы": "цветы",
    "отн цветы": "цветы",
    "сходить в кино": "кино",
    "кино": "кино",
    "в кино": "кино",
    "фильм": "кино",
    "посмотреть кино": "кино",
    "посмотреть фильм": "кино",
    "отн кино": "кино",
    "по душам": "душа",
    "душа": "душа",
    "поговорить по душам": "душа",
    "отн душа": "душа",
    "отн по душам": "душа",
    "пригласить в клуб": "клуб",
    "клуб": "клуб",
    "в клуб": "клуб",
    "тусовка": "клуб",
    "пати": "клуб",
    "отн клуб": "клуб",
    "устроить сюрприз": "сюрприз",
    "сюрприз": "сюрприз",
    "романтический сюрприз": "сюрприз",
    "отн сюрприз": "сюрприз",
    "большой подарок": "подарок",
    "сделать подарок": "подарок",
    "подарок": "подарок",
    "сделать большой подарок": "подарок",
    "вручить подарок": "подарок",
    "отн подарок": "подарок",
}

# --- Каталог совместного имущества ---
PROPERTY_CATALOG = {
    "flat": ("Квартира-студия", "🏢", 5000, 1),
    "apartment": ("Элитные апартаменты", "🏙", 15000, 2),
    "house": ("Загородный коттедж", "🏡", 50000, 3),
    "villa": ("Вилла у океана", "🏰", 150000, 4),
    "sportcar": ("Спорткар Porsche", "🏎", 300000, 5),
    "yacht": ("Белоснежная яхта", "🛥", 600000, 6),
    "factory": ("Завод сладостей", "🏭", 1500000, 7),
    "island": ("Тропический остров", "🏝", 5000000, 8),
}


def progress_bar(current: int, total: int, length: int = 10) -> str:
    if total <= 0:
        return "░" * length
    filled = min(length, max(0, int((current / total) * length)))
    return "█" * filled + "░" * (length - filled)


def get_other_id(rel: dict, uid: int) -> int:
    return rel["user2_id"] if rel["user1_id"] == uid else rel["user1_id"]


async def format_rel_card(rel: dict, bot: Bot, viewer_id: int | None = None) -> str:
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

    header_title = "💖 <b>Отношения пары</b> 💖"
    if viewer_id:
        user_rels = await db.get_user_relationships(viewer_id)
        if len(user_rels) > 1:
            rel_idx = next((i + 1 for i, r in enumerate(user_rels) if r["id"] == rel["id"]), 1)
            main_tag = " (Основа)" if rel_idx == 1 else ""
            header_title = f"💖 <b>Отношения пары [Пара #{rel_idx}{main_tag} из {len(user_rels)}]</b> 💖"

    text = (
        f"{header_title}\n\n"
        f"👩‍❤️‍👨 <b>{mention_id(rel['user1_id'], name1)}</b>  ➕  "
        f"<b>{mention_id(rel['user2_id'], name2)}</b>\n"
        f"▫️ Статус: {status_line}\n"
        f"▫️ Вместе: <b>{days} дн.</b> (с {time.strftime('%d.%m.%Y', time.localtime(rel['created_at']))})\n"
        f"▫️ Уровень любви: <b>Уровень {lvl}</b> 🏆\n"
        f"{xp_line}\n\n"
        f"🏠 <b>Совместное имущество:</b>\n{prop_str}\n\n"
        f"👶 <b>Дети пары:</b>\n{c_list}\n\n"
        f"💡 <i>Используйте <code>отн меню</code> / <code>мой отн 1</code> / <code>мой отн 2</code> для переключения между союзами!</i>"
    )
    return text


def rel_main_keyboard(rel_id: int, viewer_id: int | None = None, total_rels: int = 1, cur_idx: int = 1) -> InlineKeyboardMarkup:
    rows = []
    if viewer_id and total_rels > 1:
        prev_idx = total_rels if cur_idx <= 1 else cur_idx - 1
        next_idx = 1 if cur_idx >= total_rels else cur_idx + 1
        rows.append([
            InlineKeyboardButton(text="◀️ Пред. пара", callback_data=f"rel_nav:{viewer_id}:{prev_idx}"),
            InlineKeyboardButton(text=f"Пара {cur_idx}/{total_rels}", callback_data=f"rel_nav_list:{viewer_id}"),
            InlineKeyboardButton(text="След. пара ▶️", callback_data=f"rel_nav:{viewer_id}:{next_idx}"),
        ])

    rows.append([
        InlineKeyboardButton(text="📜 Доступные действия", callback_data=f"rel_ui:acts:{rel_id}"),
        InlineKeyboardButton(text="🏠 Имущество", callback_data=f"rel_ui:prop:{rel_id}"),
    ])
    rows.append([
        InlineKeyboardButton(text="👶 Дети", callback_data=f"rel_ui:kids:{rel_id}"),
        InlineKeyboardButton(text="🛍 Магазин пары", callback_data=f"rel_ui:shop:{rel_id}"),
    ])
    if viewer_id and total_rels > 1:
        rows.append([
            InlineKeyboardButton(text="📋 Список всех моих союзов", callback_data=f"rel_nav_list:{viewer_id}")
        ])
    rows.append([
        InlineKeyboardButton(text="❌ Закрыть", callback_data="rel_ui:close"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ================== КОМАНДЫ ОТНОШЕНИЙ ==================

@router.message(Cmd("отн", "мой отн", "мои отн", "наши отн", "брак", "мой брак", "наш брак",
                    "отношения", "мои отношения", "пара", "моя пара", "наша пара", "love",
                    section=S_REL, usage="отн [@юзер] / мой отн [номер]", desc="Отношения / карточка пары / переключение"))
async def cmd_rel_main(message: Message, bot: Bot, args: str = "", **kw):
    me_id = message.from_user.id
    raw_arg = (args or "").strip().lower()

    # Переключение между парами: "мой отн основа", "мой отн 1", "отн 2", и т.д.
    if raw_arg in ("основа", "основной") or raw_arg.isdigit():
        idx = 1 if raw_arg in ("основа", "основной") else int(raw_arg)
        rels = await db.get_user_relationships(me_id)
        if not rels:
            return await message.reply(
                "❌ <b>У вас нет отношений.</b>\nВступите в отношения командой: <code>отн @юзер</code>")
        if idx < 1 or idx > len(rels):
            return await message.reply(
                f"⚠️ У вас зарегистрировано <b>{len(rels)}</b> союзов. Укажите номер от 1 до {len(rels)}: <code>мой отн 1</code>")
        await db.set_active_rel_idx(me_id, idx)
        rel = rels[idx - 1]
        card = await format_rel_card(rel, bot, me_id)
        kb = rel_main_keyboard(rel["id"], me_id, len(rels), idx)
        tag = " (Основа)" if idx == 1 else ""
        return await message.reply(
            f"🔄 <b>Вы переключились на пару #{idx}{tag}!</b>\n\n" + card,
            reply_markup=kb, disable_web_page_preview=True)

    # Если указан пользователь (или реплай) — делаем предложение
    uid, name, _ = await resolve_target(message, args, bot)
    if uid:
        if uid == me_id:
            return await message.reply("Нельзя вступить в отношения с самим собой 🙂")
        if await db.are_in_relationship(me_id, uid):
            return await message.reply(f"💍 Вы уже состоите в отношениях с {mention_id(uid, name)}!")

        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💍 Согласен(на)", callback_data=f"rel_prop:yes:{me_id}:{uid}"),
            InlineKeyboardButton(text="💔 Отказ", callback_data=f"rel_prop:no:{me_id}:{uid}")
        ]])
        return await message.reply(
            f"💍 {mention(message.from_user)} делает предложение {mention_id(uid, name)} "
            f"вступить в отношения!\n\nЧто ответит избранник?",
            reply_markup=kb)

    # Если аргументов нет — выводим активную пару
    rels = await db.get_user_relationships(me_id)
    if not rels:
        return await message.reply(
            "❌ <b>У вас нет отношений.</b>\n\n"
            "Вступите в отношения, чтобы открыть возможности пары, совместную прокачку, "
            "имущество и семью!\n\n"
            "💡 <b>Как сделать предложение:</b>\n"
            "• Ответьте на сообщение избранника: <code>отн</code> или <code>брак</code>\n"
            "• Или напишите: <code>отн @username</code>",
            disable_web_page_preview=True)

    cur_idx = await db.get_active_rel_idx(me_id)
    if cur_idx > len(rels):
        cur_idx = 1
        await db.set_active_rel_idx(me_id, 1)

    rel = rels[cur_idx - 1]
    card = await format_rel_card(rel, bot, me_id)
    await message.reply(card, reply_markup=rel_main_keyboard(rel["id"], me_id, len(rels), cur_idx), disable_web_page_preview=True)


@router.message(Cmd("отн список", "список отн", "отношения список", "список отношений",
                    "пары", "все отн", "пары чата", section=S_REL,
                    usage="отн список", desc="Список пар и отношений"))
async def cmd_relations_list(message: Message, bot: Bot, **kw):
    rels = await db.get_all_relationships()
    if not rels:
        return await message.reply(
            "💔 <b>В базе пока нет зарегистрированных пар!</b>\n\n"
            "Чтобы создать пару, напишите: <code>отн @юзер</code> или ответьте на его сообщение командой <code>отн</code>.",
            disable_web_page_preview=True)

    lines = ["💍 <b>Список пар и отношений:</b>\n"]
    count = 0
    now = int(time.time())
    for idx, r in enumerate(rels, 1):
        u1 = await db.get_user(r["user1_id"])
        u2 = await db.get_user(r["user2_id"])
        n1 = u1["first_name"] or f"ID:{r['user1_id']}"
        n2 = u2["first_name"] or f"ID:{r['user2_id']}"
        days = max(1, (now - r["created_at"]) // 86400)

        m1 = mention_id(r["user1_id"], n1)
        m2 = mention_id(r["user2_id"], n2)

        if r["offended_by"]:
            status_icon = "💔 В обиде"
        else:
            status_icon = "💖 В согласии"

        lines.append(
            f"<b>{idx}.</b> 👩‍❤️‍👨 {m1} ➕ {m2}\n"
            f"   ▫️ Уровень: <b>🌟 {r['level']} ур.</b> ({r['xp']:,} ❤️)\n"
            f"   ▫️ Вместе: <b>{days} дн.</b> · {status_icon}\n"
        )
        count += 1
        if count >= 30:
            lines.append("<i>... и другие пары</i>\n")
            break

    lines.append(f"Всего союзов: <b>{len(rels)}</b>")
    lines.append("💡 <i>Чтобы посмотреть карточку своей пары — напишите <code>отн</code></i>")

    await message.reply("\n".join(lines), disable_web_page_preview=True)


@router.message(Cmd("отн меню", "меню отн", "меню пары", section=S_REL,
                    usage="отн меню", desc="Интерактивное меню отношений"))
async def cmd_rel_menu(message: Message, bot: Bot, **kw):
    me_id = message.from_user.id
    rels = await db.get_user_relationships(me_id)
    if not rels:
        return await message.reply(
            "❌ <b>У вас нет отношений.</b>\nВступите в отношения командой: <code>отн @юзер</code>")
    cur_idx = await db.get_active_rel_idx(me_id)
    if cur_idx > len(rels):
        cur_idx = 1
        await db.set_active_rel_idx(me_id, 1)
    rel = rels[cur_idx - 1]
    card = await format_rel_card(rel, bot, me_id)
    await message.reply(card, reply_markup=rel_main_keyboard(rel["id"], me_id, len(rels), cur_idx), disable_web_page_preview=True)


@router.callback_query(F.data.startswith("rel_nav:"))
async def cb_rel_nav(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    viewer_id = int(parts[1])
    target_idx = int(parts[2])

    if call.from_user.id != viewer_id:
        return await call.answer("Это меню принадлежит другому пользователю 🔒", show_alert=True)

    rels = await db.get_user_relationships(viewer_id)
    if not rels:
        return await call.answer("У вас нет отношений.", show_alert=True)

    if target_idx < 1 or target_idx > len(rels):
        target_idx = 1

    await db.set_active_rel_idx(viewer_id, target_idx)
    rel = rels[target_idx - 1]
    card = await format_rel_card(rel, bot, viewer_id)
    kb = rel_main_keyboard(rel["id"], viewer_id, len(rels), target_idx)
    try:
        await call.message.edit_text(card, reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        pass
    await call.answer(f"Пара #{target_idx}")


@router.callback_query(F.data.startswith("rel_nav_list:"))
async def cb_rel_nav_list(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    viewer_id = int(parts[1])

    if call.from_user.id != viewer_id:
        return await call.answer("Это меню принадлежит другому пользователю 🔒", show_alert=True)

    rels = await db.get_user_relationships(viewer_id)
    if not rels:
        return await call.answer("У вас нет отношений.", show_alert=True)

    cur_idx = await db.get_active_rel_idx(viewer_id)
    lines = ["💍 <b>Ваши союзы и отношения:</b>\n"]
    kb_rows = []

    for i, r in enumerate(rels, 1):
        other_id = get_other_id(r, viewer_id)
        other_user = await db.get_user(other_id)
        other_name = other_user["first_name"] or str(other_id)
        is_active = " 🌟 [АКТИВНА]" if i == cur_idx else ""
        is_main = " (Основа)" if i == 1 else ""
        lines.append(f"<b>{i}.</b> 👩‍❤️‍👨 {mention_id(other_id, other_name)}{is_main}{is_active} — Ур. {r['level']} ({r['xp']} ❤️)")
        kb_rows.append([InlineKeyboardButton(text=f"Пара #{i}: {other_name[:15]}{is_main}", callback_data=f"rel_nav:{viewer_id}:{i}")])

    kb_rows.append([InlineKeyboardButton(text="🔙 Назад к активной паре", callback_data=f"rel_nav:{viewer_id}:{cur_idx}")])

    try:
        await call.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), disable_web_page_preview=True)
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("rel_prop:"))
async def cb_proposal(call: CallbackQuery, bot: Bot):
    _, act, from_id_s, to_id_s = call.data.split(":")
    from_id, to_id = int(from_id_s), int(to_id_s)

    if call.from_user.id != to_id:
        return await call.answer("Это предложение адресовано не вам! 🤫", show_alert=True)

    if act == "no":
        await call.message.edit_text("💔 Предложение отклонено. Сердце разбито...")
        return await call.answer()

    if await db.are_in_relationship(from_id, to_id):
        await call.message.edit_text("⚠️ Вы уже находитесь в отношениях друг с другом.")
        return await call.answer()

    rel_id = await db.create_relationship(from_id, to_id)
    u1 = await db.get_user(from_id)
    u2 = await db.get_user(to_id)
    n1 = u1["first_name"] or str(from_id)
    n2 = u2["first_name"] or str(to_id)

    u2_rels = await db.get_user_relationships(to_id)

    await call.message.edit_text(
        f"🎉 <b>Горько!</b> 🎉\n\n"
        f"💍 <b>{mention_id(from_id, n1)}</b> и <b>{mention_id(to_id, n2)}</b> "
        f"теперь официально в отношениях!\n\n"
        f"Вам открыт <b>1-й уровень пары</b>! Используйте <code>отн меню</code>, "
        f"делайте комплименты (<code>сделать комплимент</code>) и дарите подарки, чтобы развивать союз! ❤️",
        reply_markup=rel_main_keyboard(rel_id, to_id, len(u2_rels), len(u2_rels)))
    await call.answer("Поздравляем с созданием союза! 💍", show_alert=True)


@router.message(Cmd("развод", "отн развод", "расторгнуть", "расстаться", section=S_REL,
                    usage="развод [номер/@юзер]", desc="Расторгнуть отношения"))
async def cmd_divorce(message: Message, bot: Bot, args: str = "", **kw):
    me_id = message.from_user.id
    rels = await db.get_user_relationships(me_id)
    if not rels:
        return await message.reply("Вы не состоите в отношениях.")

    target_rel = None
    target_arg = (args or "").strip()

    if target_arg.isdigit():
        t_idx = int(target_arg)
        if 1 <= t_idx <= len(rels):
            target_rel = rels[t_idx - 1]
    elif target_arg.lower() in ("основа", "основной"):
        target_rel = rels[0]
    else:
        uid, _, _ = await resolve_target(message, args, bot)
        if uid:
            for r in rels:
                if get_other_id(r, me_id) == uid:
                    target_rel = r
                    break

    if not target_rel:
        cur_idx = await db.get_active_rel_idx(me_id)
        if cur_idx <= len(rels):
            target_rel = rels[cur_idx - 1]
        else:
            target_rel = rels[0]

    other_id = get_other_id(target_rel, me_id)
    partner = await db.get_user(other_id)
    pname = partner["first_name"] or str(other_id)

    await db.delete_relationship(target_rel["id"])
    await db.set_active_rel_idx(me_id, 1)

    rem_rels = await db.get_user_relationships(me_id)
    rem_text = f"\n\nУ вас осталось ещё <b>{len(rem_rels)}</b> союзов." if rem_rels else "\n\nУ вас больше нет активных отношений."

    await message.reply(
        f"💔 <b>Отношения расторгнуты.</b>\n\n"
        f"{mention(message.from_user)} и {mention_id(other_id, pname)} больше не вместе. "
        f"Совместное имущество и достижения этой пары аннулированы.{rem_text}")


ACTION_DETAILS = {
    "комплимент": {
        "phrases": [
            "«Твоя улыбка способна осветить даже самый пасмурный день! ☀️»",
            "«Ты невероятно добрый, отзывчивый и светлый человек! ✨»",
            "«С тобой любое общение становится тёплым и уютным! ☕️»",
            "«Твоё чувство юмора — просто высший пилотаж! 😄»",
            "«Ты потрясающе выглядишь и заряжаешь всех уверенностью! 💫»",
            "«Рядом с тобой всегда легко, спокойно и радостно! 🌸»",
            "«Твоей мудрости, терпению и рассудительности можно только позавидовать! 🧠»",
            "«Ты делаешь этот чат и весь мир намного прекраснее! 🌺»",
            "«Твои глаза полны искренности, глубины и тепла! 👁️✨»",
            "«У тебя потрясающий вкус, грация и стиль! 👗👔»",
            "«Ты самый дорогой и замечательный человек на свете! 💖»",
            "«Твоя энергия и позитив вдохновляют меня каждый день! ⚡️»",
            "«Ты умеешь выслушать и поддержать в самый нужный момент! 💕»",
            "«Ты настоящий лучик солнца и счастье в моей жизни! 🌟»",
        ]
    },
    "анекдот": {
        "phrases": [
            "— Ты веришь в любовь с первого взгляда или мне пройти мимо ещё раз? 😉",
            "— Доктор, я кажется безнадёжно влюблён!\n— Это неизлечимо, рецепт: обниматься трижды в день! ❤️",
            "— Знаешь, почему звёзды падают? Чтобы уступить место твоей красоте! ✨",
            "— Что общего между тобой и чашкой горячего шоколада? Вы оба согреваете моё сердечко! ☕️",
            "— Дорогая, я подарю тебе луну с неба!\n— Лучше пиццу с сырными бортиками! 🍕",
            "— С тобой даже в очереди стоять романтично! 🥰",
            "— Если бы красота была преступлением, ты бы сидел(а) пожизненно! 🚨",
            "— Ты случайно не Wi-Fi? Просто я чувствую мощную связь между нами! 📶",
        ]
    },
    "еда": {
        "phrases": [
            "горячую хрустящую пиццу с тянущимся сыром 🍕",
            "роскошный сет свежих роллов «Филадельфия» 🍣",
            "ароматные свежеиспеченные круассаны и горячий капучино 🥐☕️",
            "спелую клубнику в нежном бельгийском шоколаде 🍓🍫",
            "домашнюю пасту карбонара с пармезаном 🍝",
            "нежнейшие чизкейки с лесными ягодами 🍰",
            "сочные фирменные бургеры с золотистой картошечкой фри 🍔🍟",
        ]
    },
    "мем": {
        "phrases": [
            "самый угарный мем с котиками про искреннюю любовь 🐱❤️",
            "отборный жизненный рофл из ленты, от которого сводит скулы от смеха 😂",
            "милый мемчик с капибарами в тёплой ванне 🛁🫧",
            "постироничный шедевр, понятный только им двоим 🎭",
            "мем про то, как сильно они скучают друг по другу 🥺",
            "смешную гифку с танцующими пингвинами 🐧🎶",
        ]
    },
    "поговорить": {
        "phrases": [
            "мило обсуждает планы на будущее и совместные мечты 💭",
            "делится самыми сокровенными мыслями и тайнами 🤫",
            "вспоминает самые смешные и яркие моменты знакомства ✨",
            "делится впечатлениями о прошедшем дне и дарит поддержку 🌟",
            "строит грандиозные планы на совместное путешествие ✈️",
        ]
    },
    "обнимать": {
        "phrases": [
            "крепко и нежно обнимает, согревая своим теплом 🤗",
            "укутывает в мягкие объятия под тёплым пледом 🧸",
            "прижимает к сердцу и шепчет самые нежные слова 💕",
            "дарит самые тёплые и искренние обнимашки на свете 🫂",
        ]
    },
    "шоколад": {
        "phrases": [
            "плитку элитного молочного шоколада 🍫",
            "коробочку нежнейших трюфелей ручной работы 🍬",
            "плитку тёмного шоколада с цельным фундуком 🌰",
            "белый шоколад с кусочками сублимированной малины 🍓",
            "горячий шоколад с пышным маршмеллоу ☕️",
        ]
    },
    "погулять": {
        "phrases": [
            "под звёздным небом по тихой ночной набережной 🌌",
            "по живописному осеннему парку, шурша золотыми листьями 🍂",
            "по уютным мощёным улочкам старого города с горячим кофе ☕️",
            "на крышу высотки с панорамным видом на огни ночного города 🌃",
            "по цветущей аллее сакуры в лучах заходящего солнца 🌸🌇",
        ]
    },
    "завтрак": {
        "phrases": [
            "пышные панкейки со свежей черникой и кленовым сиропом в постель 🥞🍓",
            "нежный омлет с хрустящими тостами, авокадо и свежим соком 🥑🍳",
            "ароматный свежесваренный кофе и теплые круассаны с шоколадом 🥐☕️",
            "хрустящие венские вафли с шариком сливочного мороженого 🧇🍨",
        ]
    },
    "конфеты": {
        "phrases": [
            "коробку изысканных конфет Ferrero Rocher и Raffaello 🍬✨",
            "набор авторских пралине с начинкой из лесных орехов 🌰",
            "огромный бокс сладких мармеладок всех вкусов 🍭",
            "французские макаруны всех цветов радуги 🍡",
        ]
    },
    "цветы": {
        "phrases": [
            "роскошный пышный букет из 101 алой розы 🌹",
            "нежнейшую композицию из свежих розовых пионов 🌸",
            "огромную охапку весенних ярких тюльпанов 🌷",
            "волшебную корзину белых гортензий и эустом 💐",
        ]
    },
    "кино": {
        "phrases": [
            "на романтическую комедию на самых уютных задних рядах 🎬🍿",
            "на захватывающий блокбастер в IMAX с огромным ведром попкорна 🥤",
            "на трогательную драму под открытым небом в автокинотеатре 🚗🎥",
            "на уютный ночной киномарафон любимых фильмов 🍿✨",
        ]
    },
    "душа": {
        "phrases": [
            "до самого рассвета обсуждает тайны вселенной и сокровенные чувства под звёздами 🌌💫",
            "делится самыми глубокими переживаниями в атмосфере абсолютного доверия 🕯💖",
            "раскрывает душу, чувствуя невероятное душевное единение и тепло 🌙✨",
        ]
    },
    "клуб": {
        "phrases": [
            "зажигает в VIP-ложе лучшего клуба города под любимые треки 🎶💃",
            "танцует до самого утра под неоновыми огнями и мощный бит 🕺🍸",
            "устраивает сумасшедшую вечеринку, где они — главные звёзды танцпола 🌟🔥",
        ]
    },
    "сюрприз": {
        "phrases": [
            "невероятный полет на воздушном шаре на рассвете 🎈🌅",
            "спонтанный уикенд в шикарном отеле с видом на горы 🏔🍾",
            "праздничный салют прямо под окнами любимого человека 🎆✨",
            "романтический ужин при свечах на приватной яхте 🕯⛵️",
        ]
    },
    "подарок": {
        "phrases": [
            "роскошную коробочку с эксклюзивным ювелирным украшением с бриллиантом 💎✨",
            "ключи от новенького спорткара, перевязанного огромным красным бантом 🏎🎀",
            "заветную путёвку на тропические острова в пятизвездочный отель 🏝✈️",
            "исполнение самой заветной мечты, от которой на глазах наворачиваются слёзы счастья 🎁🥹",
        ]
    }
}


# ================== ПРОКАЧКА ОТНОШЕНИЙ ==================

async def process_rel_action(message: Message, bot: Bot, action_key: str):
    me_id = message.from_user.id
    rels = await db.get_user_relationships(me_id)
    if not rels:
        return await message.reply(
            "❌ <b>У вас нет отношений.</b>\nВступите в отношения командой: <code>отн @юзер</code>")

    # Выбираем активную пару
    cur_idx = await db.get_active_rel_idx(me_id)
    if 1 <= cur_idx <= len(rels):
        rel = rels[cur_idx - 1]
    else:
        rel = rels[0]

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
            f"🌑 Не хватает монет для действия «{name}»!\n"
            f"Требуется: <b>{cost} 🌑</b>, у вас: <b>{user['balance']} 🌑</b>.\n"
            f"Заработайте монеты командой <code>работа</code>!")

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

    details = ACTION_DETAILS.get(action_key, {})
    phrases = details.get("phrases", [])
    custom_desc = random.choice(phrases) if phrases else ""

    if action_key == "анекдот":
        main_action_line = f"{emoji} {mention(message.from_user)} рассказывает смешной анекдот для {mention_id(other_id, pname)}:\n\n{custom_desc}"
    elif action_key == "комплимент":
        main_action_line = f"{emoji} {mention(message.from_user)} делает нежный комплимент {mention_id(other_id, pname)}:\n\n{custom_desc}"
    elif custom_desc:
        if action_key in ("еда", "шоколад", "конфеты", "цветы", "подарок"):
            main_action_line = f"{emoji} {mention(message.from_user)} дарит {custom_desc} для {mention_id(other_id, pname)}!"
        elif action_key == "погулять":
            main_action_line = f"{emoji} {mention(message.from_user)} идёт на прогулку {custom_desc} с {mention_id(other_id, pname)}!"
        elif action_key == "завтрак":
            main_action_line = f"{emoji} {mention(message.from_user)} готовит {custom_desc} для {mention_id(other_id, pname)}!"
        elif action_key == "кино":
            main_action_line = f"{emoji} {mention(message.from_user)} идёт {custom_desc} с {mention_id(other_id, pname)}!"
        elif action_key == "мем":
            main_action_line = f"{emoji} {mention(message.from_user)} присылает {custom_desc} для {mention_id(other_id, pname)}!"
        else:
            main_action_line = f"{emoji} {mention(message.from_user)} {custom_desc} с {mention_id(other_id, pname)}!"
    else:
        main_action_line = f"{emoji} {mention(message.from_user)} {verb} {mention_id(other_id, pname)}!"

    reply_text = (
        f"{main_action_line}\n\n"
        f"💖 Получено: <b>+{earned_xp} любви</b>{vip_badge}\n"
        f"🌑 Потрачено: <b>{cost} 🌑</b>\n"
        f"✨ Всего любви: <b>{new_xp}</b> (Уровень {new_lvl})"
    )

    if lvl_up:
        reply_text += (
            f"\n\n🎊 <b>УРОВЕНЬ ОТНОШЕНИЙ ПОВЫШЕН ДО {new_lvl}!</b> 🎊\n"
            f"Вам открылись новые романтические действия и возможности в <code>отн меню</code>! 💖"
        )

    await message.reply(reply_text)


COMPLIMENTS = ACTION_DETAILS["комплимент"]["phrases"]


# Регистрация команд действий
@router.message(Cmd("сделать комплимент", "комплимент", "похвалить", "отн комплимент", "сделать комплименты",
                    section=S_REL, usage="сделать комплимент",
                    desc="Сделать комплимент второй половинке (+5 любви)"))
async def cmd_act_compliment(message: Message, bot: Bot, args: str = "", **kw):
    me_id = message.from_user.id
    rels = await db.get_user_relationships(me_id)

    # Если пользователь явно указал другого пользователя (@юзер или ответ)
    uid, name, _ = await resolve_target(message, args, bot)
    if uid and uid != me_id:
        partner_rel = next((r for r in rels if get_other_id(r, me_id) == uid), None)
        if not partner_rel:
            # Обычный дружеский комплимент пользователю без отношений
            phrase = random.choice(COMPLIMENTS)
            return await message.reply(
                f"💬 {mention(message.from_user)} делает комплимент {mention_id(uid, name)}:\n\n"
                f"✨ {phrase} ✨")

    # Если отношений вообще нет
    if not rels:
        return await message.reply(
            "💬 <b>Сделать комплимент</b>\n\n"
            "У вас пока нет отношений. Чтобы радовать свою вторую половинку и прокачивать любовь, "
            "вступите в отношения: <code>отн @юзер</code>!\n\n"
            "💡 <i>Вы также можете сделать обычный комплимент любому участнику: <code>комплимент @юзер</code></i>",
            disable_web_page_preview=True)

    await process_rel_action(message, bot, "комплимент")


@router.message(Cmd("рассказать анекдот", "анекдот", "шутка", "пошутить", "травить анекдоты", "отн анекдот", "смешной анекдот",
                    section=S_REL, usage="рассказать анекдот", desc="Рассказать анекдот (+10 любви)"))
async def cmd_act_joke(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "анекдот")


@router.message(Cmd("поделиться едой", "еда", "покормить", "угостить", "вкусняшка", "отн еда", "поделиться вкусняшкой",
                    section=S_REL, usage="поделиться едой", desc="Поделиться едой (+20 любви)"))
async def cmd_act_food(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "еда")


@router.message(Cmd("кинуть мем", "мем", "мемы", "мемчик", "скинуть мем", "отправить мем", "отн мем",
                    section=S_REL, usage="кинуть мем", desc="Кинуть мем (+20 любви)"))
async def cmd_act_meme(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "мем")


@router.message(Cmd("поговорить", "мило поговорить", "беседа", "поболтать", "отн поговорить",
                    section=S_REL, usage="поговорить", desc="Поговорить (+30 любви)"))
async def cmd_act_talk(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "поговорить")


@router.message(Cmd("обнимать", "обнять", "обнимашки", "крепко обнять", "обнял", "обняла", "отн обнять", "отн обнимашки",
                    section=S_REL, usage="обнять", desc="Крепко обнять (+30 любви)"))
async def cmd_act_hug(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "обнимать")


@router.message(Cmd("подарить шоколадку", "шоколадка", "шоколад", "подарить шоколад", "вкусная шоколадка", "отн шоколад", "отн шоколадка",
                    section=S_REL, usage="подарить шоколадку", desc="Подарить шоколадку (+50 любви)"))
async def cmd_act_choco(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "шоколад")


@router.message(Cmd("пригласить погулять", "погулять", "гулять", "прогулка", "пойдем гулять", "пойти гулять", "отн погулять", "отн гулять",
                    section=S_REL, usage="пригласить погулять", desc="Пригласить погулять (+70 любви)"))
async def cmd_act_walk(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "погулять")


@router.message(Cmd("сделать завтрак", "завтрак", "приготовить завтрак", "завтрак в постель", "отн завтрак",
                    section=S_REL, usage="сделать завтрак", desc="Сделать завтрак (+100 любви)"))
async def cmd_act_breakfast(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "завтрак")


@router.message(Cmd("подарить конфеты", "конфеты", "конфетка", "коробка конфет", "сладости", "отн конфеты",
                    section=S_REL, usage="подарить конфеты", desc="Подарить конфеты (+100 любви)"))
async def cmd_act_sweets(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "конфеты")


@router.message(Cmd("подарить цветы", "цветы", "букет", "подарить букет", "розы", "отн цветы", "отн букет",
                    section=S_REL, usage="подарить цветы", desc="Подарить цветы (+150 любви)"))
async def cmd_act_flowers(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "цветы")


@router.message(Cmd("сходить в кино", "кино", "фильм", "в кино", "посмотреть кино", "посмотреть фильм", "отн кино",
                    section=S_REL, usage="сходить в кино", desc="Сходить в кино (+200 любви)"))
async def cmd_act_cinema(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "кино")


@router.message(Cmd("поговорить по душам", "по душам", "душа", "душевный разговор", "отн душа", "отн по душам",
                    section=S_REL, usage="поговорить по душам", desc="Поговорить по душам (+300 любви)"))
async def cmd_act_soul(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "душа")


@router.message(Cmd("пригласить в клуб", "клуб", "в клуб", "тусовка", "пати", "дискотека", "отн клуб",
                    section=S_REL, usage="пригласить в клуб", desc="Пригласить в клуб (+500 любви)"))
async def cmd_act_club(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "клуб")


@router.message(Cmd("устроить сюрприз", "сюрприз", "романтический сюрприз", "отн сюрприз",
                    section=S_REL, usage="устроить сюрприз", desc="Устроить сюрприз (+750 любви)"))
async def cmd_act_surprise(message: Message, bot: Bot, **kw):
    await process_rel_action(message, bot, "сюрприз")


@router.message(Cmd("сделать большой подарок", "сделать подарок", "большой подарок", "подарок", "вручить подарок", "отн подарок",
                    section=S_REL, usage="сделать подарок", desc="Сделать большой подарок (+3000 любви)"))
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
        lines = [f"• <code>отн купить {k}</code> — {e} {n} (<b>{p:,} 🌑</b>, Ур. {l})"
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
        return await message.reply(f"🌑 Не хватает монет: нужно <b>{price:,} 🌑</b>, у вас <b>{user['balance']:,} 🌑</b>.")

    await db.add_balance(me_id, -price, f"buy_{found_key}")
    await db.add_rel_property(rel["id"], found_key, f"{emoji} {name}", price)
    await db.add_rel_xp(rel["id"], price // 20)

    other_id = get_other_id(rel, me_id)
    partner = await db.get_user(other_id)
    pname = partner["first_name"] or str(other_id)

    await message.reply(
        f"🎉 <b>Поздравляем с покупкой!</b> 🎉\n\n"
        f"{mention(message.from_user)} приобрёл(а) {emoji} <b>{name}</b> в совместное владение "
        f"с {mention_id(other_id, pname)} за <b>{price:,} 🌑</b>!\n"
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
        user_rels = await db.get_user_relationships(call.from_user.id)
        cur_idx = next((i + 1 for i, r in enumerate(user_rels) if r["id"] == rel["id"]), 1)
        text = await format_rel_card(rel, bot, call.from_user.id)
        await call.message.edit_text(text, reply_markup=rel_main_keyboard(rel_id, call.from_user.id, len(user_rels), cur_idx), disable_web_page_preview=True)
        return await call.answer()

    elif action == "acts":
        # Список доступных действий по уровням
        lines = [f"📜 <b>Доступные действия пары (Ваш Ур. {rel['level']}):</b>\n"]
        for k, (name, emoji, xp, cost, cd, lvl, _) in REL_ACTIONS.items():
            status = "✅" if rel["level"] >= lvl else f"🔒 (с {lvl} ур.)"
            left = await db.get_rel_cooldown_left(rel_id, call.from_user.id, k, cd)
            cd_s = f"⏳ {human_period(left)}" if left > 0 else "🟢 Готово"
            lines.append(f"{status} {emoji} <b>{name}</b> (+{xp} любви)\n   🌑 {cost} 🌑 · {human_period(cd)} · {cd_s}")

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
                lines.append(f"• {p['item_name']} — куплено {d} за {p['price']:,} 🌑")
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
            lines.append(f"{e} <b>{n}</b> — <b>{p:,} 🌑</b> ({avail})\n   Купить: <code>отн купить {k}</code>")
        await call.message.edit_text("\n".join(lines), reply_markup=back_kb)
        return await call.answer()


# ================== ДРУЗЬЯ (ДРУЖЕСКИЕ ОТНОШЕНИЯ) ==================

@router.message(Cmd("друг", "дружить", "добавить в друзья", "предложить дружбу",
                    "+друг", "+друзья", "дружба",
                    section=S_REL, usage="друг @юзер",
                    desc="Предложить дружбу пользователю (можно дружить со многими)"))
async def cmd_friend_add(message: Message, bot: Bot, args: str = "", **kw):
    me_id = message.from_user.id
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply(
            "🤝 <b>Добавление в друзья</b>\n\n"
            "Формат: <code>друг @username</code> или ответьте на сообщение пользователя командой <code>друг</code>.\n\n"
            "💡 <i>В отличие от брака, дружить можно с любым количеством участников!</i>")

    if uid == me_id:
        return await message.reply("Нельзя предложить дружбу самому себе 🙂")

    if await db.are_friends(me_id, uid):
        return await message.reply(f"🤝 Вы и {mention_id(uid, name)} уже являетесь друзьями!")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🤝 Принять дружбу", callback_data=f"frnd_prop:yes:{me_id}:{uid}"),
        InlineKeyboardButton(text="🚫 Отклонить", callback_data=f"frnd_prop:no:{me_id}:{uid}")
    ]])

    await message.reply(
        f"🤝 {mention(message.from_user)} предлагает крепкую дружбу {mention_id(uid, name)}!\n\n"
        f"Что ответит будущий друг?",
        reply_markup=kb)


@router.callback_query(F.data.startswith("frnd_prop:"))
async def cb_friend_proposal(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    act, from_id_s, to_id_s = parts[1], parts[2], parts[3]
    from_id, to_id = int(from_id_s), int(to_id_s)

    if call.from_user.id != to_id:
        return await call.answer("Это предложение адресовано не вам! 🔒", show_alert=True)

    if act == "no":
        await call.message.edit_text("🚫 Предложение дружбы отклонено.")
        return await call.answer()

    await db.add_friend(from_id, to_id)
    u1 = await db.get_user(from_id)
    u2 = await db.get_user(to_id)
    n1 = u1["first_name"] or str(from_id)
    n2 = u2["first_name"] or str(to_id)

    await call.message.edit_text(
        f"🎉 <b>У вас новый друг!</b> 🎉\n\n"
        f"🤝 <b>{mention_id(from_id, n1)}</b> и <b>{mention_id(to_id, n2)}</b> теперь официально друзья!\n\n"
        f"Посмотреть всех друзей: <code>друзья</code>")
    await call.answer("Вы стали друзьями! 🤝", show_alert=True)


@router.message(Cmd("друзья", "список друзей", "мои друзья", "друзья список", "кто друзья",
                    section=S_REL, usage="друзья [@юзер]",
                    desc="Посмотреть список друзей"))
async def cmd_friends_list(message: Message, bot: Bot, args: str = "", **kw):
    target_uid, name, _ = await resolve_target(message, args, bot)
    if not target_uid:
        target_uid = message.from_user.id
        name = message.from_user.first_name

    friends = await db.get_friends(target_uid)
    if not friends:
        if target_uid == message.from_user.id:
            return await message.reply(
                "🤝 <b>У вас пока нет друзей.</b>\n\n"
                "Чтобы завести друзей, напишите: <code>друг @юзер</code> или ответьте на его сообщение командой <code>друг</code>!",
                disable_web_page_preview=True)
        else:
            return await message.reply(f"🤝 У {mention_id(target_uid, name)} пока нет друзей.")

    lines = [f"🤝 <b>Список друзей {mention_id(target_uid, name)}</b> (всего: <b>{len(friends)}</b>):\n"]
    now = int(time.time())
    for idx, f in enumerate(friends, 1):
        fid = f["friend_id"]
        fu = await db.get_user(fid)
        fname = fu["first_name"] or str(fid)
        days = max(1, (now - f["created_at"]) // 86400)
        lines.append(f"<b>{idx}.</b> 👤 {mention_id(fid, fname)} — дружат <b>{days} дн.</b>")
        if idx >= 30:
            lines.append("<i>... и другие друзья</i>")
            break

    lines.append("\n💡 <i>Добавить друга: <code>друг @юзер</code> · Удалить: <code>удалить из друзей @юзер</code></i>")
    await message.reply("\n".join(lines), disable_web_page_preview=True)


@router.message(Cmd("удалить из друзей", "разорвать дружбу", "удалить друга", "-друг", "-друзья",
                    section=S_REL, usage="удалить из друзей {ссылка}",
                    desc="Удалить пользователя из списка друзей"))
async def cmd_friend_remove(message: Message, bot: Bot, args: str = "", **kw):
    me_id = message.from_user.id
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите друга: <code>удалить из друзей @юзер</code>")

    if not await db.are_friends(me_id, uid):
        return await message.reply(f"Вы не состоите в друзьях с {mention_id(uid, name)}.")

    await db.remove_friend(me_id, uid)
    await message.reply(f"💔 Дружба между вами и {mention_id(uid, name)} прекращена.")

