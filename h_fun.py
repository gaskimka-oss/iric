"""Разделы 13–16: бонусы/ириски/VIP, развлечения, дуэли, кубы."""
from __future__ import annotations

import asyncio
import html
import random
import time

from aiogram import Bot, F, Router
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

import db
from config import (CRIME_COOLDOWN, CRIME_FINE, CRIME_REWARD, CRIME_SUCCESS_CHANCE,
                    DAILY_BONUS, DAILY_COOLDOWN, MAX_BET, MIN_BET, TRANSFER_FEE,
                    WORK_COOLDOWN, WORK_REWARD)
from core_ranks import require
from core_registry import Cmd
from core_resolve import human_period, parse_period, resolve_target
from utils import hms, level_of, mention, mention_id, money, parse_amount

router = Router(name="fun")
S_BONUS, S_FUN, S_DUEL, S_CUBE = 13, 14, 15, 16


# ---------- 13. Бонусы, ириски, VIP ----------
@router.message(Cmd("бонус", "ежедневный бонус", "дейли", "daily", "bonus", section=S_BONUS,
                    usage="бонус", desc="Ежедневный бонус ирисок"))
async def cmd_bonus(message: Message, **kw):
    uid = message.from_user.id
    left = await db.cooldown_left(uid, "daily", DAILY_COOLDOWN)
    if left:
        return await message.reply(f"⏳ Бонус уже получен. Следующий через <b>{hms(left)}</b>.")
    amount = random.randint(*DAILY_BONUS)
    row = await db.fetchone("SELECT until FROM vip WHERE user_id=?", (uid,))
    if row and row["until"] > time.time():
        amount = int(amount * 2)
    bal = await db.add_balance(uid, amount, "daily")
    await db.set_cooldown(uid, "daily")
    await message.reply(f"🍬 Ежедневный бонус: <b>+{money(amount)}</b>\nБаланс: {money(bal)}")


@router.message(Cmd("баланс", "бал", "ириски", "кошелек", "кошелёк", "balance", section=S_BONUS,
                    usage="баланс", desc="Показать баланс ирисок"))
async def cmd_balance(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        uid, name = message.from_user.id, message.from_user.first_name
    u = await db.get_user(uid)
    vip = await db.fetchone("SELECT until FROM vip WHERE user_id=?", (uid,))
    vip_s = "\n💎 VIP активен" if vip and vip["until"] > time.time() else ""
    await message.reply(
        f"💰 <b>Баланс</b> {mention_id(uid, name)}\n"
        f"🍬 Ириски: {money(u['balance'])}\n"
        f"🏦 В банке: {money(u['bank'])}\n"
        f"📊 Всего: {money(u['balance'] + u['bank'])}{vip_s}")


@router.message(Cmd("работа", "работать", "пахать", "work", section=S_BONUS,
                    usage="работа", desc="Заработать ириски"))
async def cmd_work(message: Message, **kw):
    uid = message.from_user.id
    left = await db.cooldown_left(uid, "work", WORK_COOLDOWN)
    if left:
        return await message.reply(f"😮‍💨 Отдохни ещё <b>{hms(left)}</b>.")
    amount = random.randint(*WORK_REWARD)
    bal = await db.add_balance(uid, amount, "work")
    await db.set_cooldown(uid, "work")
    jobs = ["разгрузил вагон ирисок", "чинил сервер Ириса", "выгуливал корги",
            "продавал мемы", "варил кофе", "тестировал баги в проде"]
    await message.reply(f"🛠 Ты {random.choice(jobs)}: <b>+{money(amount)}</b>\nБаланс: {money(bal)}")


@router.message(Cmd("крайм", "преступление", "рискнуть", section=S_BONUS,
                    usage="крайм", desc="Рискованный заработок"))
async def cmd_crime(message: Message, **kw):
    uid = message.from_user.id
    left = await db.cooldown_left(uid, "crime", CRIME_COOLDOWN)
    if left:
        return await message.reply(f"🚔 Заляг на дно ещё <b>{hms(left)}</b>.")
    await db.set_cooldown(uid, "crime")
    if random.random() < CRIME_SUCCESS_CHANCE:
        amount = random.randint(*CRIME_REWARD)
        bal = await db.add_balance(uid, amount, "crime_ok")
        return await message.reply(f"🕵️ Успех! <b>+{money(amount)}</b>\nБаланс: {money(bal)}")
    u = await db.get_user(uid)
    fine = min(u["balance"], random.randint(*CRIME_FINE))
    bal = await db.add_balance(uid, -fine, "crime_fail")
    await message.reply(f"🚨 Провал! <b>−{money(fine)}</b>\nБаланс: {money(bal)}")


@router.message(Cmd("передать", "перевести", "перевод", "дать", "give", section=S_BONUS,
                    usage="передать {ссылка} {сумма}", desc="Передать ириски"))
async def cmd_give(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, rest = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите получателя: реплаем, @ником или id.")
    if uid == message.from_user.id:
        return await message.reply("Себе передать нельзя 🙂")
    u = await db.get_user(message.from_user.id)
    amount = parse_amount(rest, u["balance"])
    if not amount or amount <= 0:
        return await message.reply("Укажите сумму: <code>передать @user 1000</code>")
    fee = int(amount * TRANSFER_FEE)
    if amount + fee > u["balance"]:
        return await message.reply(f"Не хватает: нужно {money(amount + fee)} "
                                   f"(с комиссией {int(TRANSFER_FEE*100)}%).")
    await db.add_balance(message.from_user.id, -(amount + fee), "give_out", str(uid))
    await db.add_balance(uid, amount, "give_in", str(message.from_user.id))
    await message.reply(f"✅ {mention(message.from_user)} → {mention_id(uid, name)}: "
                        f"<b>{money(amount)}</b>\n<i>комиссия {money(fee)}</i>")


@router.message(Cmd("топ", "богачи", "топ ирисок", "top", section=S_BONUS,
                    usage="топ", desc="Топ по ирискам"))
async def cmd_top(message: Message, **kw):
    rows = await db.fetchall(
        "SELECT user_id, first_name, balance+bank AS total FROM users WHERE banned=0 "
        "ORDER BY total DESC LIMIT 10")
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [f"{medals[i]} {mention_id(r['user_id'], r['first_name'])} — {money(r['total'])}"
             for i, r in enumerate(rows)]
    await message.reply("🏆 <b>Топ по ирискам</b>\n\n" + ("\n".join(lines) or "пусто"))


@router.message(Cmd("вип", "vip", section=S_BONUS, usage="вип", desc="Статус VIP"))
async def cmd_vip(message: Message, **kw):
    row = await db.fetchone("SELECT until FROM vip WHERE user_id=?", (message.from_user.id,))
    if row and row["until"] > time.time():
        left = int(row["until"] - time.time())
        return await message.reply(f"💎 VIP активен ещё <b>{human_period(left)}</b>\n"
                                   f"Бонусы: удвоенный ежедневный бонус.")
    await message.reply("💎 VIP не активен.\nВыдаётся владельцем бота: <code>выдать вип @user 30 дней</code>")


@router.message(Cmd("выдать вип", "дать вип", section=S_BONUS, rank=5,
                    usage="выдать вип {ссылка} {период}", desc="Выдать VIP (владелец)"))
async def cmd_give_vip(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 5):
        return
    uid, name, rest = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя.")
    secs, _ = parse_period(rest)
    secs = secs or 30 * 86400
    await db.execute("INSERT INTO vip (user_id, until, level) VALUES (?,?,1) "
                     "ON CONFLICT(user_id) DO UPDATE SET until=excluded.until",
                     (uid, int(time.time()) + secs))
    await message.reply(f"💎 {mention_id(uid, name)} получил VIP на <b>{human_period(secs)}</b>")


# ---------- 14. Развлечения ----------
@router.message(Cmd("кто", section=S_FUN, usage="кто {вопрос}", desc="Случайный участник"))
async def cmd_who(message: Message, args: str = "", **kw):
    q = html.escape(args) if args else "самый крутой"
    if message.chat.type == "private":
        return await message.reply(f"🤔 Кто {q}? Конечно ты!")
    rows = await db.fetchall(
        "SELECT s.user_id, u.first_name FROM chat_stats s LEFT JOIN users u "
        "ON u.user_id=s.user_id WHERE s.chat_id=? ORDER BY RANDOM() LIMIT 1", (message.chat.id,))
    if not rows:
        return await message.reply("Пока не знаю участников — поговорите немного.")
    await message.reply(f"🤔 {q} — это {mention_id(rows[0]['user_id'], rows[0]['first_name'])}!")


@router.message(Cmd("шанс", "вероятность", section=S_FUN, usage="шанс {вопрос}",
                    desc="Вероятность события"))
async def cmd_chance(message: Message, args: str = "", **kw):
    if not args:
        return await message.reply("Формат: <code>шанс что я разбогатею</code>")
    await message.reply(f"📊 Вероятность «{html.escape(args)}» — <b>{random.randint(0,100)}%</b>")


@router.message(Cmd("выбери", "выбор", section=S_FUN, usage="выбери а, б, в",
                    desc="Выбрать из вариантов"))
async def cmd_choose(message: Message, args: str = "", **kw):
    opts = [o.strip() for o in (args or "").replace(" или ", ",").split(",") if o.strip()]
    if len(opts) < 2:
        return await message.reply("Формат: <code>выбери чай, кофе</code>")
    await message.reply(f"🎲 Я выбираю: <b>{html.escape(random.choice(opts))}</b>")


@router.message(Cmd("шар", "8ball", section=S_FUN, usage="шар {вопрос}",
                    desc="Магический шар"))
async def cmd_ball(message: Message, args: str = "", **kw):
    ans = ["Бесспорно", "Мне кажется — да", "Пока неясно", "Даже не думай",
           "Определённо нет", "Знаки говорят — да", "Весьма сомнительно", "Да", "Нет"]
    if not args:
        return await message.reply("Задайте вопрос: <code>шар мне повезёт?</code>")
    await message.reply(f"🎱 {random.choice(ans)}")


@router.message(Cmd("рандом", "случайное число", section=S_FUN, usage="рандом 1 100",
                    desc="Случайное число"))
async def cmd_random(message: Message, args: str = "", **kw):
    p = (args or "").split()
    a, b = (int(p[0]), int(p[1])) if len(p) >= 2 and p[0].lstrip('-').isdigit() \
        and p[1].lstrip('-').isdigit() else (1, 100)
    await message.reply(f"🎲 Случайное число от {a} до {b}: <b>{random.randint(min(a,b), max(a,b))}</b>")


@router.message(Cmd("монетка", "монета", section=S_FUN, usage="монетка",
                    desc="Подбросить монетку"))
async def cmd_coin(message: Message, args: str = "", **kw):
    await message.reply(f"🪙 Выпал <b>{random.choice(['орёл', 'решка'])}</b>")


@router.message(Cmd("правда", "действие", "правда или действие", section=S_FUN,
                    usage="правда", desc="Правда или действие"))
async def cmd_truth(message: Message, **kw):
    truths = ["Какой твой самый большой страх?", "О чём ты жалеешь?",
              "Самый неловкий момент в жизни?", "Кому последнему ты врал?"]
    acts = ["Отправь последнее фото из галереи", "Напиши статус «я люблю Ирис» на час",
            "Позвони другу и спой", "Смени ник на «Ириска» на сутки"]
    await message.reply(random.choice([f"❓ <b>Правда:</b> {random.choice(truths)}",
                                       f"🎬 <b>Действие:</b> {random.choice(acts)}"]))


@router.message(Cmd("анекдот", "шутка", section=S_FUN, usage="анекдот", desc="Случайный анекдот"))
async def cmd_joke(message: Message, **kw):
    jokes = [
        "— Как дела?\n— Как в сказке: чем дальше, тем страшнее.",
        "Программист ставит на тумбочку два стакана: с водой — если захочет пить, "
        "пустой — если не захочет.",
        "Лучший способ найти вещь — купить новую. Старая появится сразу.",
        "— Доктор, я живу в интернете!\n— Ясно. Перезагрузитесь.",
    ]
    await message.reply(f"😄 {random.choice(jokes)}")


@router.message(Cmd("погода", section=S_FUN, usage="погода {город}", desc="Шуточный прогноз"))
async def cmd_weather(message: Message, args: str = "", **kw):
    city = html.escape(args) if args else "у тебя дома"
    w = random.choice(["☀️ солнечно", "🌧 дождь", "❄️ снег", "⛅️ облачно", "🌪 ураган ирисок"])
    await message.reply(f"🌍 Погода в «{city}»: {w}, {random.randint(-20, 35)}°C")


# ---------- 15. Дуэли ----------
_duels: dict[str, dict] = {}


async def _bet_of(message: Message, raw: str) -> int | None:
    u = await db.get_user(message.from_user.id)
    bet = parse_amount(raw, u["balance"], MIN_BET)
    if not bet or bet < MIN_BET:
        await message.reply(f"Ставка от {money(MIN_BET)}.")
        return None
    if bet > MAX_BET:
        await message.reply(f"Максимум {money(MAX_BET)}.")
        return None
    if bet > u["balance"]:
        await message.reply(f"Недостаточно ирисок: {money(u['balance'])}.")
        return None
    return bet


@router.message(Cmd("дуэль", "битва", "duel", section=S_DUEL, usage="дуэль {ставка} (реплаем)",
                    desc="Вызвать на дуэль"))
async def cmd_duel(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, rest = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Ответьте реплаем на соперника: <code>дуэль 1000</code>")
    if uid == message.from_user.id:
        return await message.reply("Нужен живой соперник.")
    bet = await _bet_of(message, rest)
    if bet is None:
        return
    o = await db.get_user(uid)
    if o["balance"] < bet:
        return await message.reply(f"У соперника только {money(o['balance'])}.")
    key = f"{message.chat.id}:{message.from_user.id}:{uid}"
    _duels[key] = {"bet": bet, "from": message.from_user.id, "to": uid}
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⚔️ Принять", callback_data=f"duel:ok:{key}"),
        InlineKeyboardButton(text="🚫 Отказ", callback_data=f"duel:no:{key}")]])
    await message.reply(f"⚔️ {mention(message.from_user)} вызывает {mention_id(uid, name)} "
                        f"на дуэль за <b>{money(bet)}</b>!", reply_markup=kb)


@router.callback_query(F.data.startswith("duel:"))
async def cb_duel(call: CallbackQuery):
    _, action, key = call.data.split(":", 2)
    d = _duels.get(key)
    if not d:
        return await call.answer("Дуэль устарела", show_alert=True)
    if call.from_user.id != d["to"]:
        return await call.answer("Вызов не вам", show_alert=True)
    _duels.pop(key, None)
    if action == "no":
        await call.message.edit_text("🚫 Дуэль отклонена.")
        return await call.answer()
    a, b, bet = d["from"], d["to"], d["bet"]
    ua, ub = await db.get_user(a), await db.get_user(b)
    if ua["balance"] < bet or ub["balance"] < bet:
        return await call.message.edit_text("Недостаточно ирисок — дуэль отменена.")
    win, lose = (a, b) if random.random() < 0.5 else (b, a)
    await db.add_balance(lose, -bet, "duel_lose")
    await db.add_balance(win, bet, "duel_win")
    uw = await db.get_user(win)
    await call.message.edit_text(f"⚔️ Дуэль окончена!\n🏆 Победил "
                                 f"{mention_id(win, uw['first_name'])} — <b>+{money(bet)}</b>")
    await call.answer()


@router.message(Cmd("топ дуэлей", "топ дуэлянтов", section=S_DUEL, usage="топ дуэлей",
                    desc="Лучшие дуэлянты"))
async def cmd_duel_top(message: Message, **kw):
    rows = await db.fetchall(
        "SELECT user_id, COUNT(*) w, SUM(amount) s FROM log WHERE action='duel_win' "
        "GROUP BY user_id ORDER BY w DESC LIMIT 10")
    if not rows:
        return await message.reply("Дуэлей ещё не было.")
    lines = []
    for i, r in enumerate(rows):
        u = await db.get_user(r["user_id"])
        lines.append(f"{i+1}. {mention_id(r['user_id'], u['first_name'])} — "
                     f"{r['w']} побед ({money(r['s'] or 0)})")
    await message.reply("⚔️ <b>Топ дуэлянтов</b>\n" + "\n".join(lines))


# ---------- 16. Кубы ----------
@router.message(Cmd("куб", "кубик", "кости", "cube", "dice", section=S_CUBE, usage="куб {ставка}",
                    desc="Бросить кубик на ириски"))
async def cmd_cube(message: Message, args: str = "", **kw):
    if not args.strip():
        m = await message.answer_dice(emoji="🎲")
        return
    bet = await _bet_of(message, args)
    if bet is None:
        return
    await db.add_balance(message.from_user.id, -bet, "cube_bet")
    m1 = await message.answer_dice(emoji="🎲")
    await asyncio.sleep(4)
    m2 = await message.answer_dice(emoji="🎲")
    await asyncio.sleep(4)
    p, b = m1.dice.value, m2.dice.value
    if p > b:
        bal = await db.add_balance(message.from_user.id, bet * 2, "cube_win")
        await message.reply(f"🎲 {p} : {b} — <b>победа!</b> +{money(bet)}\nБаланс: {money(bal)}")
    elif p == b:
        bal = await db.add_balance(message.from_user.id, bet, "cube_draw")
        await message.reply(f"🎲 {p} : {b} — ничья.\nБаланс: {money(bal)}")
    else:
        u = await db.get_user(message.from_user.id)
        await message.reply(f"🎲 {p} : {b} — проигрыш −{money(bet)}\nБаланс: {money(u['balance'])}")


@router.message(Cmd("казино", "слоты", "казик", "slots", section=S_CUBE, usage="казино {ставка}",
                    desc="Игровые слоты"))
async def cmd_slots(message: Message, args: str = "", **kw):
    bet = await _bet_of(message, args)
    if bet is None:
        return
    await db.add_balance(message.from_user.id, -bet, "slots_bet")
    m = await message.answer_dice(emoji="🎰")
    await asyncio.sleep(3)
    v = m.dice.value
    mult = 10 if v == 64 else (5 if v in (1, 22, 43) else (2 if v in (4, 8, 12, 16, 32, 48) else 0))
    if mult:
        bal = await db.add_balance(message.from_user.id, bet * mult, "slots_win")
        await message.reply(f"🎰 Выигрыш x{mult}: <b>+{money(bet*(mult-1))}</b>\nБаланс: {money(bal)}")
    else:
        u = await db.get_user(message.from_user.id)
        await message.reply(f"🎰 Мимо. −{money(bet)}\nБаланс: {money(u['balance'])}")


@router.message(Cmd("рулетка", "roulette", section=S_CUBE, usage="рулетка красное {ставка}",
                    desc="Рулетка: цвет/чёт/число"))
async def cmd_roulette(message: Message, args: str = "", **kw):
    p = (args or "").split()
    if len(p) < 2:
        return await message.reply("Формат: <code>рулетка красное 1000</code>\n"
                                   "Ставки: красное/чёрное/чёт/нечет (x2), зеро или число (x14)")
    choice, bet = p[0].lower(), await _bet_of(message, p[1])
    if bet is None:
        return
    await db.add_balance(message.from_user.id, -bet, "roulette_bet")
    num = random.randint(0, 36)
    red = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    color = "зеро" if num == 0 else ("красное" if num in red else "чёрное")
    mult = 0
    if choice in {"красное", "красн", "red"} and color == "красное": mult = 2
    elif choice in {"чёрное", "черное", "black"} and color == "чёрное": mult = 2
    elif choice in {"чет", "чёт", "even"} and num and num % 2 == 0: mult = 2
    elif choice in {"нечет", "нечёт", "odd"} and num % 2 == 1: mult = 2
    elif choice in {"зеро", "zero"} and num == 0: mult = 14
    elif choice.isdigit() and int(choice) == num: mult = 14
    if mult:
        bal = await db.add_balance(message.from_user.id, bet * mult, "roulette_win")
        await message.reply(f"🎡 Выпало <b>{num} {color}</b> — x{mult}: +{money(bet*(mult-1))}\n"
                            f"Баланс: {money(bal)}")
    else:
        u = await db.get_user(message.from_user.id)
        await message.reply(f"🎡 Выпало <b>{num} {color}</b> — проигрыш −{money(bet)}\n"
                            f"Баланс: {money(u['balance'])}")


# ---------- Магазин и топ дня (работают и в группе, и в личке) ----------
@router.message(Cmd("магазин", "купить ириски", "shop", "донат", section=S_BONUS,
                    usage="магазин", desc="Купить ириски и VIP за Telegram Stars"))
async def cmd_shop(message: Message, **kw):
    from h_start import SHOP_TEXT, shop_kb
    await message.reply(SHOP_TEXT, reply_markup=shop_kb())


@router.message(Cmd("топ дня", "топдня", "актив дня", section=9, usage="топ дня",
                    desc="Самые активные за сегодня"))
async def cmd_topday(message: Message, **kw):
    import time as _t
    day = _t.strftime("%Y-%m-%d")
    if message.chat.type == "private":
        rows = await db.fetchall(
            "SELECT d.user_id, SUM(d.messages) m, u.first_name FROM daily_stats d "
            "LEFT JOIN users u ON u.user_id=d.user_id WHERE d.day=? "
            "GROUP BY d.user_id ORDER BY m DESC LIMIT 10", (day,))
    else:
        rows = await db.fetchall(
            "SELECT d.user_id, d.messages m, u.first_name FROM daily_stats d "
            "LEFT JOIN users u ON u.user_id=d.user_id WHERE d.day=? AND d.chat_id=? "
            "ORDER BY m DESC LIMIT 10", (day, message.chat.id))
    if not rows:
        return await message.reply("🏆 Сегодня ещё никто не активничал.")
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    await message.reply("🏆 <b>Топ дня</b>\n\n" + "\n".join(
        f"{medals[i]} {mention_id(r['user_id'], r['first_name'])} — {r['m']} сообщ."
        for i, r in enumerate(rows)))
