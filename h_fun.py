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
import core_members as members
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
                    usage="бонус", desc="Бонус ирисок (сокращенный КД)"))
async def cmd_bonus(message: Message, **kw):
    uid = message.from_user.id
    vip_lvl, _, vip_active = await db.get_vip_info(uid)
    if vip_active:
        cd = 1800 if vip_lvl >= 2 else 3600  # 30 мин для VIP+, 1 час для VIP
    else:
        cd = 7200  # 2 часа обычный кулдаун (вместо 24ч)

    left = await db.cooldown_left(uid, "daily", cd)
    if left:
        return await message.reply(f"⏳ Бонус уже получен. Следующий через <b>{hms(left)}</b>.")

    amount = random.randint(*DAILY_BONUS)
    vip_tag = ""
    if vip_active:
        if vip_lvl >= 2:
            amount = int(amount * 3)
            vip_tag = "\n🌟 <i>Бонус VIP+: x3 награда (КД 30 мин)!</i>"
        elif vip_lvl >= 1:
            amount = int(amount * 2)
            vip_tag = "\n⭐️ <i>Бонус VIP: x2 награда (КД 1 час)!</i>"

    bal = await db.add_balance(uid, amount, "daily")
    await db.set_cooldown(uid, "daily")
    await message.reply(f"🍬 Бонус получен: <b>+{money(amount)}</b>{vip_tag}\nБаланс: {money(bal)}")



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


CASINO_TOPIC_ID = 132681
CASINO_TOPIC_URL = "https://t.me/c/3934033202/132681"


@router.message(Cmd("работа", "работать", "пахать", "work", section=S_BONUS,
                    usage="работа", desc="Заработать ириски (только в теме Казино)"))
async def cmd_work(message: Message, **kw):
    uid = message.from_user.id

    # Ограничение по теме (топику) казино
    if message.chat.type != "private":
        thread_id = getattr(message, "message_thread_id", None)
        if thread_id and thread_id != CASINO_TOPIC_ID:
            try:
                await message.delete()
            except Exception:
                pass
            from h_userinfo import _autodel
            warn = await message.answer(
                f"⚠️ {mention(message.from_user)}, команду <code>работа</code> можно использовать только в теме:\n"
                f"🎰 <a href=\"{CASINO_TOPIC_URL}\">Казино / Работа</a>\n\n"
                f"👉 Перейдите в нужную тему, чтобы заработать ириски!",
                disable_web_page_preview=True)
            _autodel(warn, 60)
            return

    left = await db.cooldown_left(uid, "work", WORK_COOLDOWN)
    if left:
        return await message.reply(f"😮‍💨 Отдохни ещё <b>{hms(left)}</b>.")

    base_amount = random.randint(*WORK_REWARD)
    vip_lvl, _, vip_active = await db.get_vip_info(uid)
    bonus = 0
    vip_tag = ""
    if vip_active:
        if vip_lvl >= 2:
            bonus = base_amount  # +100% для VIP+
            vip_tag = "\n🌟 <i>Бонус VIP+: +100% к награде!</i>"
        elif vip_lvl >= 1:
            bonus = int(base_amount * 0.5)  # +50% для VIP
            vip_tag = "\n⭐️ <i>Бонус VIP: +50% к награде!</i>"

    amount = base_amount + bonus
    bal = await db.add_balance(uid, amount, "work")
    await db.set_cooldown(uid, "work")
    jobs = ["разгрузил вагон ирисок", "чинил сервер Ириса", "выгуливал корги",
            "продавал мемы", "варил кофе", "тестировал баги в проде",
            "собирал урожай на ферме", "помогал в казино"]
    await message.reply(
        f"🛠 Ты {random.choice(jobs)}: <b>+{money(amount)}</b>{vip_tag}\n"
        f"Баланс: {money(bal)}")


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


@router.message(Cmd("украсть", "ограбить", "вор", "кража", "rob", "steal", "грабеж", "грабёж",
                    section=S_BONUS, usage="украсть {ссылка} [сумма]",
                    desc="Попробовать украсть деньги у игрока"))
async def cmd_rob(message: Message, bot: Bot, args: str = "", **kw):
    robber_id = message.from_user.id
    uid, name, rest = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply(
            "🦹‍♂️ <b>Ограбление игрока</b>\n\n"
            "Формат: <code>украсть @юзер [сумма]</code>\n"
            "Пример: <code>украсть @Dima 500</code>\n\n"
            "💡 <i>Если ограбление удастся — вы заберёте ириски жертвы.\n"
            "Если провалится — вы заплатите штраф и компенсацию жертве!</i>")

    if uid == robber_id:
        return await message.reply("Себя ограбить нельзя 🙂")

    # Кулдаун на ограбления
    vip_lvl, _, vip_active = await db.get_vip_info(robber_id)
    cd = 600 if (vip_active and vip_lvl >= 2) else (1200 if (vip_active and vip_lvl >= 1) else 1800)
    left = await db.cooldown_left(robber_id, "rob_cd", cd)
    if left:
        return await message.reply(f"🚨 Полиция ещё ищет вас! Залягте на дно: <b>{hms(left)}</b>.")

    u_robber = await db.get_user(robber_id)
    u_victim = await db.get_user(uid)

    if u_robber["balance"] < 50:
        return await message.reply(f"У вас слишком мало ирисок ({money(u_robber['balance'])}). Нужно минимум 50 🪙 на случай штрафа.")

    if u_victim["balance"] < 50:
        return await message.reply(f"У {mention_id(uid, name)} в карманах пусто (меньше 50 🪙). Красть нечего!")

    # Расчёт суммы
    max_steal = min(u_victim["balance"], 50000)
    raw_amount = parse_amount(rest, u_victim["balance"])
    if raw_amount and raw_amount > 0:
        amount = min(raw_amount, max_steal)
    else:
        # По умолчанию случайная часть (15-30% от баланса жертвы, не более 10000)
        pct = random.uniform(0.15, 0.30)
        amount = max(50, min(int(u_victim["balance"] * pct), 10000))

    if amount > u_victim["balance"]:
        amount = u_victim["balance"]

    # Шанс успеха: базовый 45%, +10% VIP, +20% VIP+
    chance = 0.45
    if vip_active:
        if vip_lvl >= 2:
            chance += 0.20
        elif vip_lvl >= 1:
            chance += 0.10

    # Жертва с VIP имеет защиту
    v_vip_lvl, _, v_vip_act = await db.get_vip_info(uid)
    if v_vip_act:
        chance -= 0.10

    chance = max(0.20, min(0.80, chance))
    await db.set_cooldown(robber_id, "rob_cd")

    if random.random() < chance:
        # Успех
        await db.add_balance(uid, -amount, "robbed_by", str(robber_id))
        new_bal = await db.add_balance(robber_id, amount, "rob_win", str(uid))
        await message.reply(
            f"🦹‍♂️ <b>Успешное ограбление!</b>\n\n"
            f"{mention(message.from_user)} ловко вытащил из кармана {mention_id(uid, name)} <b>+{money(amount)}</b>! 💰\n\n"
            f"🎲 Вероятность успеха была: <b>{int(chance * 100)}%</b>\n"
            f"🍬 Ваш новый баланс: <b>{money(new_bal)}</b>")
    else:
        # Провал! Штраф от 50% до 100% от суммы попытки (но не более баланса вора)
        fine = max(50, min(u_robber["balance"], int(amount * random.uniform(0.5, 1.0))))
        new_bal = await db.add_balance(robber_id, -fine, "rob_fail", str(uid))
        await db.add_balance(uid, fine, "rob_comp", str(robber_id))
        await message.reply(
            f"🚨 <b>Ограбление провалилось!</b>\n\n"
            f"{mention(message.from_user)} попался с поличным при попытке ограбить {mention_id(uid, name)}!\n"
            f"👮‍♂️ Полиция конфисковала и передала жертве компенсацию: <b>−{money(fine)}</b> 💸\n\n"
            f"🍬 Ваш баланс: <b>{money(new_bal)}</b>")



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


# ---------- 14. Развлечения ----------
@router.message(Cmd("кто", section=S_FUN, usage="!кто {вопрос}",
                    desc="Случайный присутствующий участник (только с обращением)"))
async def cmd_who(message: Message, bot: Bot, args: str = "", **kw):
    """Отвечает только на явную команду; обычное «кто играть?» игнорируется."""
    q = html.escape(args) if args else "самый крутой"
    if message.chat.type == "private":
        return await message.reply(f"🤔 Кто {q}? Конечно ты!")

    rows = await members.known_chat_rows(message.chat.id, limit=100)
    me = await bot.me()
    people = await members.verified_members(
        bot, message.chat.id, rows, exclude=(me.id,))
    if not people:
        return await message.reply("Не нашёл присутствующих участников.")
    person = random.choice(people)
    who = members.summon_mention(
        person["user_id"], person.get("first_name"), person.get("username"))
    await message.reply(f"🤔 {q} — это {who}!")


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


# ---------- 16. Кубы и Казино (Рандом игры) ----------
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


@router.message(Cmd("слоты", "slots", section=S_CUBE, usage="слоты {ставка}",
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
        await message.reply(f"🎰 <b>Выигрыш x{mult}!</b> +{money(bet*(mult-1))}\nБаланс: {money(bal)}")
    else:
        u = await db.get_user(message.from_user.id)
        await message.reply(f"🎰 Мимо. −{money(bet)}\nБаланс: {money(u['balance'])}")


@router.message(Cmd("дартс", "darts", section=S_CUBE, usage="дартс {ставка}",
                    desc="Дартс на ириски"))
async def cmd_darts(message: Message, args: str = "", **kw):
    bet = await _bet_of(message, args)
    if bet is None:
        return
    await db.add_balance(message.from_user.id, -bet, "darts_bet")
    m = await message.answer_dice(emoji="🎯")
    await asyncio.sleep(3)
    v = m.dice.value
    mult = 5 if v == 6 else (2 if v in (4, 5) else (1 if v in (2, 3) else 0))
    if mult > 1:
        bal = await db.add_balance(message.from_user.id, bet * mult, "darts_win")
        tag = "🎯 <b>В ЯБЛОЧКО! x5!</b>" if v == 6 else f"🎯 <b>Точное попадание! x{mult}!</b>"
        await message.reply(f"{tag} +{money(bet*(mult-1))}\nБаланс: {money(bal)}")
    elif mult == 1:
        bal = await db.add_balance(message.from_user.id, bet, "darts_draw")
        await message.reply(f"🎯 Возврат ставки (x1).\nБаланс: {money(bal)}")
    else:
        u = await db.get_user(message.from_user.id)
        await message.reply(f"🎯 Мимо мишени! −{money(bet)}\nБаланс: {money(u['balance'])}")


@router.message(Cmd("боулинг", "кегли", "bowling", section=S_CUBE, usage="боулинг {ставка}",
                    desc="Боулинг на ириски"))
async def cmd_bowling(message: Message, args: str = "", **kw):
    bet = await _bet_of(message, args)
    if bet is None:
        return
    await db.add_balance(message.from_user.id, -bet, "bowling_bet")
    m = await message.answer_dice(emoji="🎳")
    await asyncio.sleep(3)
    v = m.dice.value
    mult = 4 if v == 6 else (2 if v in (4, 5) else 0)
    if mult:
        bal = await db.add_balance(message.from_user.id, bet * mult, "bowling_win")
        tag = "🎳 <b>СТРАЙК! x4!</b>" if v == 6 else f"🎳 <b>Отличный бросок! x{mult}!</b>"
        await message.reply(f"{tag} +{money(bet*(mult-1))}\nБаланс: {money(bal)}")
    else:
        u = await db.get_user(message.from_user.id)
        await message.reply(f"🎳 Шар в желобе! −{money(bet)}\nБаланс: {money(u['balance'])}")


@router.message(Cmd("футбол", "пенальти", "football", "penalty", section=S_CUBE, usage="футбол {ставка}",
                    desc="Пенальти на ириски"))
async def cmd_football(message: Message, args: str = "", **kw):
    bet = await _bet_of(message, args)
    if bet is None:
        return
    await db.add_balance(message.from_user.id, -bet, "football_bet")
    m = await message.answer_dice(emoji="⚽")
    await asyncio.sleep(3)
    v = m.dice.value
    if v in (3, 4, 5):
        win_amount = int(bet * 2.5)
        bal = await db.add_balance(message.from_user.id, win_amount, "football_win")
        await message.reply(f"⚽️ <b>ГОООЛ! x2.5!</b> +{money(win_amount - bet)}\nБаланс: {money(bal)}")
    else:
        u = await db.get_user(message.from_user.id)
        await message.reply(f"⚽️ Вратарь отбил мяч! −{money(bet)}\nБаланс: {money(u['balance'])}")


@router.message(Cmd("баскетбол", "basketball", section=S_CUBE, usage="баскетбол {ставка}",
                    desc="Баскетбол на ириски"))
async def cmd_basketball(message: Message, args: str = "", **kw):
    bet = await _bet_of(message, args)
    if bet is None:
        return
    await db.add_balance(message.from_user.id, -bet, "basketball_bet")
    m = await message.answer_dice(emoji="🏀")
    await asyncio.sleep(3)
    v = m.dice.value
    if v in (4, 5):
        bal = await db.add_balance(message.from_user.id, bet * 3, "basketball_win")
        await message.reply(f"🏀 <b>Точно в корзину! x3!</b> +{money(bet * 2)}\nБаланс: {money(bal)}")
    elif v == 3:
        win_amount = int(bet * 1.5)
        bal = await db.add_balance(message.from_user.id, win_amount, "basketball_win")
        await message.reply(f"🏀 <b>Отскок от кольца! x1.5!</b> +{money(win_amount - bet)}\nБаланс: {money(bal)}")
    else:
        u = await db.get_user(message.from_user.id)
        await message.reply(f"🏀 Мимо кольца! −{money(bet)}\nБаланс: {money(u['balance'])}")


@router.message(Cmd("казино", "казик", "играть", "casino", section=S_CUBE, usage="казино {ставка}",
                    desc="Случайная игра казино (слоты, кости, дартс, боулинг, футбол, баскетбол)"))
async def cmd_casino_random(message: Message, args: str = "", **kw):
    """Случайная игра казино при вызове «казик» или «казино»."""
    games = [cmd_slots, cmd_cube, cmd_darts, cmd_bowling, cmd_football, cmd_basketball]
    chosen_game = random.choice(games)
    await chosen_game(message, args=args, **kw)



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
