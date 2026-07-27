"""Разделы 17–27, 30–31: кланы, кружки, отношения, браки, репутация,
награды, закладки, заметки, таймеры, каталог, биржа, репорты, розыгрыши."""
from __future__ import annotations

import html
import random
import time

from aiogram import Bot, F, Router
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

import db
from config import REP_COOLDOWN
from core_ranks import require
from core_registry import Cmd
from core_resolve import human_period, parse_period, resolve_target
from utils import hms, mention, mention_id, money, parse_amount

router = Router(name="modules")
(S_CLAN, S_CIRCLE, S_REL, S_MARRY, S_REP, S_AWARD, S_BOOK,
 S_NOTE, S_TIMER, S_CAT, S_MARKET, S_REPORT, S_GIVE) = (
    17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 30, 31)


# ================= 17. КЛАНЫ =================
@router.message(Cmd("создать клан", "клан создать", section=S_CLAN,
                    usage="создать клан {название}", desc="Создать клан"))
async def clan_create(message: Message, args: str = "", **kw):
    name = (args or "").strip()
    if not name:
        return await message.reply("Формат: <code>создать клан Драконы</code>")
    if await db.fetchone("SELECT 1 FROM clan_members WHERE user_id=?", (message.from_user.id,)):
        return await message.reply("Вы уже состоите в клане. Сначала <code>выйти из клана</code>.")
    if await db.fetchone("SELECT 1 FROM clans WHERE lower(name)=lower(?)", (name,)):
        return await message.reply("Клан с таким названием уже есть.")
    u = await db.get_user(message.from_user.id)
    if u["balance"] < 5000:
        return await message.reply(f"Создание клана стоит {money(5000)}. У вас {money(u['balance'])}.")
    await db.add_balance(message.from_user.id, -5000, "clan_create")
    await db.execute("INSERT INTO clans (name, owner_id, ts) VALUES (?,?,?)",
                     (name, message.from_user.id, int(time.time())))
    row = await db.fetchone("SELECT id FROM clans WHERE name=?", (name,))
    await db.execute("INSERT INTO clan_members (clan_id, user_id, ts) VALUES (?,?,?)",
                     (row["id"], message.from_user.id, int(time.time())))
    await message.reply(f"🏰 Клан <b>{html.escape(name)}</b> создан! Вы его глава.")


@router.message(Cmd("клан", "мой клан", section=S_CLAN, usage="клан", desc="Информация о клане"))
async def clan_info(message: Message, args: str = "", **kw):
    name = (args or "").strip()
    if name:
        clan = await db.fetchone("SELECT * FROM clans WHERE lower(name)=lower(?)", (name,))
    else:
        cm = await db.fetchone("SELECT clan_id FROM clan_members WHERE user_id=?",
                               (message.from_user.id,))
        clan = await db.fetchone("SELECT * FROM clans WHERE id=?", (cm["clan_id"],)) if cm else None
    if not clan:
        return await message.reply("Клан не найден. Создать: <code>создать клан Название</code>")
    members = await db.fetchall(
        "SELECT m.user_id, u.first_name FROM clan_members m LEFT JOIN users u "
        "ON u.user_id=m.user_id WHERE m.clan_id=?", (clan["id"],))
    owner = await db.get_user(clan["owner_id"])
    lst = "\n".join(f"  • {mention_id(m['user_id'], m['first_name'])}" for m in members[:20])
    await message.reply(
        f"🏰 <b>{html.escape(clan['name'])}</b>\n"
        f"👑 Глава: {mention_id(clan['owner_id'], owner['first_name'])}\n"
        f"💰 Казна: {money(clan['balance'])}\n"
        f"👥 Участников: {len(members)}\n{lst}")


@router.message(Cmd("вступить в клан", "клан вступить", section=S_CLAN,
                    usage="вступить в клан {название}", desc="Вступить в клан"))
async def clan_join(message: Message, args: str = "", **kw):
    name = (args or "").strip()
    clan = await db.fetchone("SELECT * FROM clans WHERE lower(name)=lower(?)", (name,))
    if not clan:
        return await message.reply("Клан не найден.")
    if await db.fetchone("SELECT 1 FROM clan_members WHERE user_id=?", (message.from_user.id,)):
        return await message.reply("Вы уже в клане.")
    await db.execute("INSERT INTO clan_members (clan_id, user_id, ts) VALUES (?,?,?)",
                     (clan["id"], message.from_user.id, int(time.time())))
    await message.reply(f"✅ Вы вступили в клан <b>{html.escape(clan['name'])}</b>")


@router.message(Cmd("выйти из клана", "покинуть клан", section=S_CLAN,
                    usage="выйти из клана", desc="Покинуть клан"))
async def clan_leave(message: Message, **kw):
    cm = await db.fetchone("SELECT clan_id FROM clan_members WHERE user_id=?",
                           (message.from_user.id,))
    if not cm:
        return await message.reply("Вы не состоите в клане.")
    clan = await db.fetchone("SELECT * FROM clans WHERE id=?", (cm["clan_id"],))
    await db.execute("DELETE FROM clan_members WHERE user_id=?", (message.from_user.id,))
    if clan and clan["owner_id"] == message.from_user.id:
        await db.execute("DELETE FROM clans WHERE id=?", (clan["id"],))
        await db.execute("DELETE FROM clan_members WHERE clan_id=?", (clan["id"],))
        return await message.reply("🏰 Вы были главой — клан расформирован.")
    await message.reply("👋 Вы покинули клан.")


@router.message(Cmd("топ кланов", "кланы", section=S_CLAN, usage="топ кланов",
                    desc="Рейтинг кланов"))
async def clan_top(message: Message, **kw):
    rows = await db.fetchall(
        "SELECT c.name, c.balance, COUNT(m.user_id) cnt FROM clans c "
        "LEFT JOIN clan_members m ON m.clan_id=c.id GROUP BY c.id "
        "ORDER BY cnt DESC, c.balance DESC LIMIT 10")
    if not rows:
        return await message.reply("Кланов пока нет.")
    lines = [f"{i+1}. <b>{html.escape(r['name'])}</b> — {r['cnt']} чел., {money(r['balance'])}"
             for i, r in enumerate(rows)]
    await message.reply("🏰 <b>Топ кланов</b>\n" + "\n".join(lines))


# ================= 18. КРУЖКИ =================
@router.message(Cmd("кружок", "круг", section=S_CIRCLE, usage="кружок",
                    desc="Случайный видеокружок-ответ"))
async def circle(message: Message, **kw):
    await message.reply("⭕️ Модуль кружков: пришлите видеокружок реплаем с командой "
                        "<code>сохранить кружок</code>, и бот будет присылать его случайно.")


@router.message(Cmd("сохранить кружок", section=S_CIRCLE, usage="сохранить кружок (реплаем)",
                    desc="Сохранить кружок"))
async def circle_save(message: Message, **kw):
    r = message.reply_to_message
    if not r or not r.video_note:
        return await message.reply("Ответьте командой на видеокружок.")
    await db.execute("INSERT INTO notes (chat_id,user_id,name,text,ts) VALUES (?,?,?,?,?)",
                     (message.chat.id, message.from_user.id, "__circle__",
                      r.video_note.file_id, int(time.time())))
    await message.reply("⭕️ Кружок сохранён.")


@router.message(Cmd("случайный кружок", section=S_CIRCLE, usage="случайный кружок",
                    desc="Прислать случайный кружок"))
async def circle_rand(message: Message, **kw):
    row = await db.fetchone("SELECT text FROM notes WHERE name='__circle__' "
                            "AND chat_id=? ORDER BY RANDOM() LIMIT 1", (message.chat.id,))
    if not row:
        return await message.reply("Кружков нет. Сохраните: <code>сохранить кружок</code>")
    await message.answer_video_note(row["text"])


# ================= 20. БРАКИ =================
@router.message(Cmd("брак", "жениться", "предложение", "marry", section=S_MARRY,
                    usage="брак {ссылка}", desc="Сделать предложение"))
async def marry(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Ответьте реплаем на избранника: <code>брак</code>")
    if uid == message.from_user.id:
        return await message.reply("Так нельзя 🙂")
    me = await db.get_user(message.from_user.id)
    other = await db.get_user(uid)
    if me["married_to"]:
        return await message.reply("Вы уже в браке. Сначала <code>развод</code>.")
    if other["married_to"]:
        return await message.reply("Избранник уже в браке 💔")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💍 Согласен(на)", callback_data=f"mr:ok:{message.from_user.id}:{uid}"),
        InlineKeyboardButton(text="💔 Отказ", callback_data=f"mr:no:{message.from_user.id}:{uid}")]])
    await message.reply(f"💍 {mention(message.from_user)} делает предложение "
                        f"{mention_id(uid, name)}!", reply_markup=kb)


@router.callback_query(F.data.startswith("mr:"))
async def cb_marry(call: CallbackQuery):
    _, act, a, b = call.data.split(":")
    a, b = int(a), int(b)
    if call.from_user.id != b:
        return await call.answer("Предложение не вам", show_alert=True)
    if act == "no":
        await call.message.edit_text("💔 Предложение отклонено.")
        return await call.answer()
    ts = int(time.time())
    await db.execute("UPDATE users SET married_to=?, married_at=? WHERE user_id=?", (b, ts, a))
    await db.execute("UPDATE users SET married_to=?, married_at=? WHERE user_id=?", (a, ts, b))
    ua, ub = await db.get_user(a), await db.get_user(b)
    await call.message.edit_text(f"🎉 {mention_id(a, ua['first_name'])} и "
                                 f"{mention_id(b, ub['first_name'])} теперь в браке! 💍")
    await call.answer()


@router.message(Cmd("развод", "развестись", "divorce", section=S_MARRY, usage="развод",
                    desc="Расторгнуть брак"))
async def divorce(message: Message, **kw):
    u = await db.get_user(message.from_user.id)
    if not u["married_to"]:
        return await message.reply("Вы не в браке.")
    p = await db.get_user(u["married_to"])
    await db.execute("UPDATE users SET married_to=NULL, married_at=NULL WHERE user_id IN (?,?)",
                     (message.from_user.id, u["married_to"]))
    await message.reply(f"💔 {mention(message.from_user)} развёлся(лась) с "
                        f"{mention_id(p['user_id'], p['first_name'])}.")


@router.message(Cmd("браки", "топ браков", "свадьбы", section=S_MARRY, usage="браки",
                    desc="Список браков чата"))
async def marry_list(message: Message, **kw):
    rows = await db.fetchall(
        "SELECT user_id, first_name, married_to, married_at FROM users "
        "WHERE married_to IS NOT NULL ORDER BY married_at LIMIT 40")
    seen, lines = set(), []
    for r in rows:
        if r["user_id"] in seen:
            continue
        seen.add(r["user_id"]); seen.add(r["married_to"])
        p = await db.get_user(r["married_to"])
        days = int((time.time() - (r["married_at"] or time.time())) // 86400)
        lines.append(f"💍 {mention_id(r['user_id'], r['first_name'])} + "
                     f"{mention_id(p['user_id'], p['first_name'])} — {days} дн.")
    await message.reply("💒 <b>Браки</b>\n" + ("\n".join(lines) or "Пока никто не женат."))


# ================= 21. РЕПУТАЦИЯ =================
@router.message(Cmd("реп", "+реп", "плюс", "спасибо", "репутация", section=S_REP,
                    usage="реп {ссылка}", desc="Повысить репутацию"))
async def rep_plus(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        u = await db.get_user(message.from_user.id)
        return await message.reply(f"⭐️ Ваша репутация: <b>{u['rep']}</b>\n"
                                   f"Повысить другому: реплай + <code>реп</code>")
    if uid == message.from_user.id:
        return await message.reply("Себе — нельзя 🙂")
    left = await db.cooldown_left(message.from_user.id, "rep", REP_COOLDOWN)
    if left:
        return await message.reply(f"⏳ Следующая репутация через <b>{hms(left)}</b>.")
    await db.get_user(uid)
    await db.execute("UPDATE users SET rep = rep + 1 WHERE user_id=?", (uid,))
    await db.set_cooldown(message.from_user.id, "rep")
    u = await db.get_user(uid)
    await message.reply(f"⭐️ {mention(message.from_user)} повысил репутацию "
                        f"{mention_id(uid, name)} → <b>{u['rep']}</b>")


@router.message(Cmd("-реп", "минус реп", "минусреп", section=S_REP, rank=1,
                    usage="-реп {ссылка}", desc="Понизить репутацию (модератор)"))
async def rep_minus(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 1):
        return
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя.")
    await db.get_user(uid)
    await db.execute("UPDATE users SET rep = rep - 1 WHERE user_id=?", (uid,))
    u = await db.get_user(uid)
    await message.reply(f"📉 Репутация {mention_id(uid, name)} → <b>{u['rep']}</b>")


@router.message(Cmd("топ репутации", "топ репы", section=S_REP, usage="топ репутации",
                    desc="Рейтинг по репутации"))
async def rep_top(message: Message, **kw):
    rows = await db.fetchall("SELECT user_id, first_name, rep FROM users "
                             "WHERE rep<>0 ORDER BY rep DESC LIMIT 10")
    lines = [f"{i+1}. {mention_id(r['user_id'], r['first_name'])} — ⭐️ {r['rep']}"
             for i, r in enumerate(rows)]
    await message.reply("⭐️ <b>Топ репутации</b>\n" + ("\n".join(lines) or "пусто"))


# ================= 22. НАГРАДЫ =================
@router.message(Cmd("наградить", "выдать награду", section=S_AWARD, rank=3,
                    usage="наградить {ссылка} {название}", desc="Выдать награду"))
async def award_give(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 3):
        return
    uid, name, rest = await resolve_target(message, args, bot)
    if not uid or not rest:
        return await message.reply("Формат: реплай + <code>наградить Лучший мемер</code>")
    await db.execute("INSERT INTO awards (chat_id,user_id,title,by_id,ts) VALUES (?,?,?,?,?)",
                     (message.chat.id, uid, rest, message.from_user.id, int(time.time())))
    await message.reply(f"🏅 {mention_id(uid, name)} получает награду: <b>{html.escape(rest)}</b>")


@router.message(Cmd("награды", "мои награды", section=S_AWARD, usage="награды",
                    desc="Список наград"))
async def award_list(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        uid, name = message.from_user.id, message.from_user.first_name
    rows = await db.fetchall("SELECT title, ts FROM awards WHERE user_id=? ORDER BY id DESC",
                             (uid,))
    if not rows:
        return await message.reply(f"У {mention_id(uid, name)} пока нет наград.")
    lines = [f"🏅 {html.escape(r['title'])} ({time.strftime('%d.%m.%y', time.localtime(r['ts']))})"
             for r in rows]
    await message.reply(f"🏆 <b>Награды</b> {mention_id(uid, name)}\n" + "\n".join(lines))


@router.message(Cmd("снять награду", section=S_AWARD, rank=3, usage="снять награду {ссылка}",
                    desc="Убрать последнюю награду"))
async def award_del(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 3):
        return
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя.")
    await db.execute("DELETE FROM awards WHERE id=(SELECT id FROM awards WHERE user_id=? "
                     "ORDER BY id DESC LIMIT 1)", (uid,))
    await message.reply(f"✅ Награда снята с {mention_id(uid, name)}.")


# ================= 23. ЗАКЛАДКИ =================
@router.message(Cmd("закладка", "сохранить", "заложить", section=S_BOOK,
                    usage="закладка {название} (реплаем)", desc="Сохранить сообщение"))
async def bm_add(message: Message, args: str = "", **kw):
    r = message.reply_to_message
    if not r:
        return await message.reply("Ответьте командой на сообщение, которое хотите сохранить.")
    name = (args or f"Закладка {int(time.time())}").strip()
    link = ""
    if str(message.chat.id).startswith("-100"):
        link = f"https://t.me/c/{str(message.chat.id)[4:]}/{r.message_id}"
    text = (r.text or r.caption or "медиа")[:200]
    await db.execute("INSERT INTO bookmarks (user_id,name,link,ts) VALUES (?,?,?,?)",
                     (message.from_user.id, name, link or text, int(time.time())))
    await message.reply(f"🔖 Сохранено: <b>{html.escape(name)}</b>\n"
                        f"Список: <code>закладки</code>")


@router.message(Cmd("закладки", "мои закладки", section=S_BOOK, usage="закладки",
                    desc="Список закладок"))
async def bm_list(message: Message, **kw):
    rows = await db.fetchall("SELECT id,name,link FROM bookmarks WHERE user_id=? "
                             "ORDER BY id DESC LIMIT 20", (message.from_user.id,))
    if not rows:
        return await message.reply("Закладок нет.")
    lines = []
    for r in rows:
        v = r["link"]
        v = f'<a href="{v}">открыть</a>' if v.startswith("http") else html.escape(v[:60])
        lines.append(f"#{r['id']} <b>{html.escape(r['name'])}</b> — {v}")
    await message.reply("🔖 <b>Ваши закладки</b>\n" + "\n".join(lines))


@router.message(Cmd("удалить закладку", section=S_BOOK, usage="удалить закладку {id}",
                    desc="Удалить закладку"))
async def bm_del(message: Message, args: str = "", **kw):
    if not args.strip().isdigit():
        return await message.reply("Формат: <code>удалить закладку 5</code>")
    await db.execute("DELETE FROM bookmarks WHERE id=? AND user_id=?",
                     (int(args.strip()), message.from_user.id))
    await message.reply("🗑 Закладка удалена.")


# ================= 24. ЗАМЕТКИ =================
@router.message(Cmd("заметка", "новая заметка", section=S_NOTE,
                    usage="заметка {название} {текст}", desc="Создать заметку"))
async def note_add(message: Message, args: str = "", **kw):
    parts = (args or "").split(maxsplit=1)
    if len(parts) < 2 and not message.reply_to_message:
        return await message.reply("Формат: <code>заметка правила Текст заметки</code>")
    name = parts[0] if parts else "заметка"
    text = parts[1] if len(parts) > 1 else (
        message.reply_to_message.text or message.reply_to_message.caption or "")
    await db.execute("INSERT INTO notes (chat_id,user_id,name,text,ts) VALUES (?,?,?,?,?)",
                     (message.chat.id, message.from_user.id, name, text, int(time.time())))
    await message.reply(f"🗒 Заметка <b>{html.escape(name)}</b> сохранена.\n"
                        f"Прочитать: <code>заметка {html.escape(name)}</code>")


@router.message(Cmd("заметки", "мои заметки", section=S_NOTE, usage="заметки",
                    desc="Список заметок"))
async def note_list(message: Message, **kw):
    rows = await db.fetchall("SELECT name FROM notes WHERE chat_id=? AND name<>'__circle__' "
                             "ORDER BY id DESC LIMIT 30", (message.chat.id,))
    if not rows:
        return await message.reply("Заметок нет.")
    await message.reply("🗒 <b>Заметки чата</b>\n" +
                        "\n".join(f"• {html.escape(r['name'])}" for r in rows))


@router.message(Cmd("удалить заметку", section=S_NOTE, usage="удалить заметку {название}",
                    desc="Удалить заметку"))
async def note_del(message: Message, args: str = "", **kw):
    if not args.strip():
        return await message.reply("Укажите название.")
    await db.execute("DELETE FROM notes WHERE chat_id=? AND lower(name)=lower(?)",
                     (message.chat.id, args.strip()))
    await message.reply("🗑 Заметка удалена.")


# ================= 25. ТАЙМЕРЫ =================
@router.message(Cmd("таймер", "напомни", "напоминание", section=S_TIMER,
                    usage="таймер {период} {текст}", desc="Поставить напоминание"))
async def timer_add(message: Message, args: str = "", **kw):
    secs, text = parse_period(args or "")
    if not secs:
        return await message.reply("Формат: <code>таймер 10 минут выключить плиту</code>")
    fire = int(time.time()) + secs
    await db.execute("INSERT INTO timers (chat_id,user_id,text,fire_at) VALUES (?,?,?,?)",
                     (message.chat.id, message.from_user.id, text or "напоминание", fire))
    await message.reply(f"⏰ Напомню через <b>{human_period(secs)}</b>: "
                        f"{html.escape(text or 'напоминание')}")


@router.message(Cmd("таймеры", "мои таймеры", section=S_TIMER, usage="таймеры",
                    desc="Список активных таймеров"))
async def timer_list(message: Message, **kw):
    rows = await db.fetchall("SELECT id,text,fire_at FROM timers WHERE user_id=? AND done=0 "
                             "ORDER BY fire_at", (message.from_user.id,))
    if not rows:
        return await message.reply("Активных таймеров нет.")
    lines = [f"#{r['id']} {html.escape(r['text'])} — через "
             f"{human_period(int(r['fire_at'] - time.time()))}" for r in rows]
    await message.reply("⏰ <b>Ваши таймеры</b>\n" + "\n".join(lines))


@router.message(Cmd("удалить таймер", "отменить таймер", section=S_TIMER,
                    usage="удалить таймер {id}", desc="Отменить таймер"))
async def timer_del(message: Message, args: str = "", **kw):
    if not args.strip().isdigit():
        return await message.reply("Формат: <code>удалить таймер 3</code>")
    await db.execute("UPDATE timers SET done=1 WHERE id=? AND user_id=?",
                     (int(args.strip()), message.from_user.id))
    await message.reply("✅ Таймер отменён.")


# ================= 26. КАТАЛОГ =================
@router.message(Cmd("каталог", "чаты каталог", section=S_CAT, usage="каталог",
                    desc="Каталог чатов бота"))
async def catalog(message: Message, **kw):
    rows = await db.fetchall("SELECT title, chat_id FROM chats ORDER BY added_at DESC LIMIT 20")
    if not rows:
        return await message.reply("Каталог пуст.")
    lines = [f"• {html.escape(r['title'] or 'чат')}" for r in rows]
    await message.reply("📚 <b>Каталог чатов</b>\n" + "\n".join(lines))


@router.message(Cmd("добавить в каталог", section=S_CAT, rank=4, usage="добавить в каталог",
                    desc="Добавить чат в каталог"))
async def catalog_add(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 4):
        return
    await db.register_chat(message.chat.id, message.chat.title)
    await message.reply("✅ Чат добавлен в каталог.")


# ================= 27. ИРИС-БИРЖА =================
@router.message(Cmd("биржа", "маркет", section=S_MARKET, usage="биржа",
                    desc="Активные заявки биржи"))
async def market(message: Message, **kw):
    rows = await db.fetchall("SELECT m.*, u.first_name FROM market m LEFT JOIN users u "
                             "ON u.user_id=m.user_id ORDER BY m.id DESC LIMIT 15")
    if not rows:
        return await message.reply("💱 <b>Ирис-биржа</b>\nЗаявок нет.\n"
                                   "Создать: <code>продать 1000 за 500</code>")
    lines = [f"#{r['id']} {mention_id(r['user_id'], r['first_name'])} — "
             f"{r['kind']} {money(r['amount'])} за {money(r['price'])}" for r in rows]
    await message.reply("💱 <b>Ирис-биржа</b>\n" + "\n".join(lines))


@router.message(Cmd("продать", section=S_MARKET, usage="продать {кол-во} за {цена}",
                    desc="Выставить заявку на бирже"))
async def market_sell(message: Message, args: str = "", **kw):
    m = (args or "").replace(" за ", " ").split()
    if len(m) < 2:
        return await message.reply("Формат: <code>продать 1000 за 500</code>")
    u = await db.get_user(message.from_user.id)
    amount = parse_amount(m[0], u["balance"])
    price = parse_amount(m[1], u["balance"])
    if not amount or not price:
        return await message.reply("Некорректные числа.")
    if amount > u["balance"]:
        return await message.reply("Недостаточно ирисок.")
    await db.add_balance(message.from_user.id, -amount, "market_lock")
    await db.execute("INSERT INTO market (user_id,kind,amount,price,ts) VALUES (?,?,?,?,?)",
                     (message.from_user.id, "продажа", amount, price, int(time.time())))
    await message.reply(f"💱 Заявка создана: {money(amount)} за {money(price)}")


@router.message(Cmd("купить", section=S_MARKET, usage="купить {id}", desc="Купить заявку"))
async def market_buy(message: Message, args: str = "", **kw):
    if not args.strip().isdigit():
        return await message.reply("Формат: <code>купить 3</code> (id из списка «биржа»)")
    row = await db.fetchone("SELECT * FROM market WHERE id=?", (int(args.strip()),))
    if not row:
        return await message.reply("Заявка не найдена.")
    if row["user_id"] == message.from_user.id:
        return await message.reply("Это ваша заявка.")
    u = await db.get_user(message.from_user.id)
    if u["balance"] < row["price"]:
        return await message.reply(f"Нужно {money(row['price'])}, у вас {money(u['balance'])}.")
    await db.add_balance(message.from_user.id, -row["price"], "market_buy")
    await db.add_balance(message.from_user.id, row["amount"], "market_get")
    await db.add_balance(row["user_id"], row["price"], "market_sold")
    await db.execute("DELETE FROM market WHERE id=?", (row["id"],))
    await message.reply(f"✅ Сделка совершена: получено {money(row['amount'])} "
                        f"за {money(row['price'])}")


# ================= 30. РЕПОРТЫ =================
@router.message(Cmd("репорт", "жалоба", "report", section=S_REPORT,
                    usage="репорт {причина} (реплаем)", desc="Пожаловаться модераторам"))
async def report(message: Message, bot: Bot, args: str = "", **kw):
    tgt = message.reply_to_message.from_user if message.reply_to_message else None
    await db.execute("INSERT INTO reports (chat_id,user_id,target_id,text,ts) VALUES (?,?,?,?,?)",
                     (message.chat.id, message.from_user.id, tgt.id if tgt else 0,
                      args or "без описания", int(time.time())))
    mods = await db.fetchall("SELECT r.user_id, u.first_name FROM ranks r "
                             "LEFT JOIN users u ON u.user_id=r.user_id "
                             "WHERE r.chat_id=? AND r.rank>=1", (message.chat.id,))
    tags = " ".join(mention_id(m["user_id"], m["first_name"]) for m in mods[:20])
    await message.reply(f"📣 <b>Жалоба отправлена</b>\n"
                        f"На: {mention_id(tgt.id, tgt.first_name) if tgt else '—'}\n"
                        f"Причина: {html.escape(args or 'без описания')}\n\n{tags}")


@router.message(Cmd("репорты", "жалобы", section=S_REPORT, rank=1, usage="репорты",
                    desc="Список жалоб"))
async def report_list(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 1):
        return
    rows = await db.fetchall("SELECT * FROM reports WHERE chat_id=? AND status='open' "
                             "ORDER BY id DESC LIMIT 15", (message.chat.id,))
    if not rows:
        return await message.reply("Открытых жалоб нет.")
    lines = [f"#{r['id']} на <code>{r['target_id']}</code>: {html.escape(r['text'][:60])}"
             for r in rows]
    await message.reply("📣 <b>Жалобы</b>\n" + "\n".join(lines))


@router.message(Cmd("закрыть репорт", section=S_REPORT, rank=1, usage="закрыть репорт {id}",
                    desc="Закрыть жалобу"))
async def report_close(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 1):
        return
    if not args.strip().isdigit():
        return await message.reply("Формат: <code>закрыть репорт 3</code>")
    await db.execute("UPDATE reports SET status='closed' WHERE id=?", (int(args.strip()),))
    await message.reply("✅ Жалоба закрыта.")


# ================= 31. РОЗЫГРЫШИ =================
@router.message(Cmd("розыгрыш", "конкурс", section=S_GIVE, rank=2,
                    usage="розыгрыш {период} {приз}", desc="Запустить розыгрыш"))
async def giveaway(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 2):
        return
    secs, prize = parse_period(args or "")
    secs = secs or 3600
    prize = prize or "приз"
    await db.execute("INSERT INTO giveaways (chat_id,prize,owner_id,until) VALUES (?,?,?,?)",
                     (message.chat.id, prize, message.from_user.id, int(time.time()) + secs))
    row = await db.fetchone("SELECT last_insert_rowid() id")
    gid = row["id"]
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎁 Участвовать", callback_data=f"ga:{gid}")]])
    await message.answer(f"🎁 <b>Розыгрыш!</b>\nПриз: <b>{html.escape(prize)}</b>\n"
                         f"Итоги через {human_period(secs)}\n\nУчастников: 0", reply_markup=kb)


@router.callback_query(F.data.startswith("ga:"))
async def cb_giveaway(call: CallbackQuery):
    gid = int(call.data.split(":")[1])
    g = await db.fetchone("SELECT * FROM giveaways WHERE id=?", (gid,))
    if not g or g["done"]:
        return await call.answer("Розыгрыш завершён", show_alert=True)
    await db.execute("INSERT OR IGNORE INTO giveaway_members (gid,user_id) VALUES (?,?)",
                     (gid, call.from_user.id))
    cnt = await db.fetchone("SELECT COUNT(*) c FROM giveaway_members WHERE gid=?", (gid,))
    try:
        await call.message.edit_text(
            f"🎁 <b>Розыгрыш!</b>\nПриз: <b>{html.escape(g['prize'])}</b>\n"
            f"Итоги: {time.strftime('%d.%m %H:%M', time.localtime(g['until']))}\n\n"
            f"Участников: {cnt['c']}", reply_markup=call.message.reply_markup)
    except Exception:
        pass
    await call.answer("✅ Вы участвуете!")


@router.message(Cmd("итоги розыгрыша", "завершить розыгрыш", section=S_GIVE, rank=2,
                    usage="итоги розыгрыша", desc="Подвести итоги"))
async def giveaway_end(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 2):
        return
    g = await db.fetchone("SELECT * FROM giveaways WHERE chat_id=? AND done=0 "
                          "ORDER BY id DESC LIMIT 1", (message.chat.id,))
    if not g:
        return await message.reply("Активных розыгрышей нет.")
    mem = await db.fetchall("SELECT user_id FROM giveaway_members WHERE gid=?", (g["id"],))
    await db.execute("UPDATE giveaways SET done=1 WHERE id=?", (g["id"],))
    if not mem:
        return await message.reply("🎁 Никто не участвовал.")
    w = random.choice(mem)["user_id"]
    u = await db.get_user(w)
    await message.answer(f"🎉 <b>Итоги розыгрыша</b>\nПриз: {html.escape(g['prize'])}\n"
                         f"Победитель: {mention_id(w, u['first_name'])}")
