"""Грамм-бот: вторая валюта «граммы» и игры на неё.

Игры: орёл/решка, мины, дартс, краш, колесо, сапёр (на двоих), рулетка.
"""
from __future__ import annotations

import asyncio
import html
import random
import time

from aiogram import Bot, F, Router
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

import db
from core_registry import Cmd
from core_resolve import human_period, parse_period, resolve_target
from utils import hms, mention, mention_id, parse_amount

router = Router(name="grams")
S = 33  # раздел «Граммы и игры»

GRAM = "💊"
MIN_BET = 100
MAX_BET = 50_000_000
DAILY_GRAMS = 100_000
DAILY_CD = 24 * 3600
START_GRAMS = 10_000


def g(n: int) -> str:
    """Форматирование: 1 500 000 → 1.5кк"""
    return f"{n:,}".replace(",", " ") + f" {GRAM}"


async def _ensure_start(uid: int) -> None:
    """Первый вход — выдаём стартовые граммы."""
    u = await db.get_user(uid)
    if u["grams"] == 0:
        row = await db.fetchone(
            "SELECT 1 FROM log WHERE user_id=? AND action='gram_start'", (uid,))
        if not row:
            await db.add_grams(uid, START_GRAMS, "gram_start")


async def get_gram_topic(chat_id: int) -> int:
    v = await db.get_setting(chat_id, "gram_topic", "0")
    try:
        return int(v)
    except ValueError:
        return 0


def _tid(message: Message) -> int:
    return int(getattr(message, "message_thread_id", None) or 0)


def _tlink(chat_id: int, tid: int) -> str:
    cid = str(chat_id)
    short = cid[4:] if cid.startswith("-100") else cid.lstrip("-")
    return f"https://t.me/c/{short}/{tid}"


async def topic_ok(message: Message) -> bool:
    """Проверяет тему. Подсказка только про граммы, удаляется через минуту."""
    if message.chat.type == "private":
        return True
    ft = await get_gram_topic(message.chat.id)
    if not ft or _tid(message) == ft:
        return True

    chat_id = message.chat.id
    text = (
        f"❌ {mention(message.from_user)}, здесь нельзя играть!\n\n"
        f"🎮 <b>Игры и граммы</b> — только в этой теме:\n"
        f"{_tlink(chat_id, ft)}\n\n"
        f"<i>Сообщение исчезнет через минуту.</i>"
    )
    try:
        warn = await message.reply(text, disable_web_page_preview=True)
        asyncio.create_task(_autodel(message, warn))
    except Exception:
        pass
    return False


async def _autodel(user_msg: Message, bot_msg: Message, delay: int = 60) -> None:
    """Через минуту убирает и команду игрока, и подсказку бота."""
    await asyncio.sleep(delay)
    for m in (bot_msg, user_msg):
        try:
            await m.delete()
        except Exception:
            pass


async def take_bet(message: Message, raw: str) -> int | None:
    """Проверяет ставку в граммах."""
    if not await topic_ok(message):
        return None
    uid = message.from_user.id
    await _ensure_start(uid)
    bal = await db.get_grams(uid)
    bet = parse_amount(raw, bal, MIN_BET)
    if not bet or bet < MIN_BET:
        await message.reply(
            f"Минимальная ставка — <b>{g(MIN_BET)}</b>\n"
            f"Ваш баланс: <b>{g(bal)}</b>\n\n"
            f"Пример: <code>орёл 1000</code> · <code>мины 5к</code> · "
            f"<code>краш все</code>")
        return None
    if bet > MAX_BET:
        await message.reply(f"Максимальная ставка — <b>{g(MAX_BET)}</b>")
        return None
    if bet > bal:
        await message.reply(f"Недостаточно граммов.\nВаш баланс: <b>{g(bal)}</b>")
        return None
    return bet


# ═══════════════ БАЛАНС И БОНУС ═══════════════
@router.message(Cmd("б", "баланс граммов", "граммы", "мои граммы", section=S,
                    usage="б", desc="Баланс граммов"))
async def cmd_balance(message: Message, bot: Bot, args: str = "", **kw):
    if not await topic_ok(message):
        return
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        uid, name = message.from_user.id, message.from_user.first_name
    await _ensure_start(uid)
    bal = await db.get_grams(uid)
    won = await db.fetchone(
        "SELECT COALESCE(SUM(amount),0) s FROM log WHERE user_id=? AND amount>0 "
        "AND action LIKE 'gram_win%'", (uid,))
    lost = await db.fetchone(
        "SELECT COALESCE(SUM(-amount),0) s FROM log WHERE user_id=? AND amount<0 "
        "AND action LIKE 'gram_bet%'", (uid,))
    pos = await db.fetchone(
        "SELECT COUNT(*)+1 p FROM users WHERE grams > (SELECT grams FROM users "
        "WHERE user_id=?)", (uid,))
    left = await db.cooldown_left(uid, "gram_daily", DAILY_CD)
    if left:
        bonus_line = f"🎁 Бонус будет доступен через <b>{hms(left)}</b>"
        kb = None
    else:
        bonus_line = f"🎁 <b>Бонус готов!</b> Заберите {g(DAILY_GRAMS)} в боте 👇"
        me = await bot.me()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=f"🎁 Забрать {DAILY_GRAMS:,} {GRAM}".replace(",", " "),
            url=f"https://t.me/{me.username}?start=bonus")]])

    await message.reply(
        f"{GRAM} <b>Баланс граммов</b>\n"
        f"👤 {mention_id(uid, name)}\n\n"
        f"💰 На руках: <b>{g(bal)}</b>\n"
        f"🏆 Место в топе: <b>{pos['p']}</b>\n"
        f"📈 Всего выиграно: {g(int(won['s']))}\n"
        f"📉 Всего поставлено: {g(int(lost['s']))}\n\n"
        f"{bonus_line}\n"
        f"🎮 <code>игры</code> — список игр · 👑 <code>выпка</code>",
        reply_markup=kb)


@router.message(Cmd("бонус граммы", "грамм бонус", "ежедневные граммы", section=S,
                    usage="бонус граммы", desc=f"Ежедневный бонус {DAILY_GRAMS:,} граммов"))
async def cmd_daily(message: Message, **kw):
    if not await topic_ok(message):
        return
    uid = message.from_user.id
    await _ensure_start(uid)
    left = await db.cooldown_left(uid, "gram_daily", DAILY_CD)
    if left:
        return await message.reply(
            f"⏳ Бонус уже получен.\nСледующий через <b>{hms(left)}</b>")
    bal = await db.add_grams(uid, DAILY_GRAMS, "gram_daily")
    await db.set_cooldown(uid, "gram_daily")
    await message.reply(
        f"🎁 <b>Ежедневный бонус!</b>\n"
        f"Получено: <b>+{g(DAILY_GRAMS)}</b>\n"
        f"Баланс: <b>{g(bal)}</b>")


@router.message(Cmd("топ граммов", "топ грамм", "грамм топ", section=S,
                    usage="топ граммов", desc="Богатейшие по граммам"))
async def cmd_top(message: Message, **kw):
    if not await topic_ok(message):
        return
    rows = await db.fetchall(
        "SELECT user_id, first_name, grams FROM users WHERE grams > 0 "
        "ORDER BY grams DESC LIMIT 10")
    if not rows:
        return await message.reply("Пока никто не играл.")
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    await message.reply(f"{GRAM} <b>Топ по граммам</b>\n\n" + "\n".join(
        f"{medals[i]} {mention_id(r['user_id'], r['first_name'])} — {g(r['grams'])}"
        for i, r in enumerate(rows)))


@router.message(Cmd("передать граммы", "перевод граммов", "дать граммы", section=S,
                    usage="передать граммы {ссылка} {сумма}", desc="Передать граммы"))
async def cmd_give(message: Message, bot: Bot, args: str = "", **kw):
    if not await topic_ok(message):
        return
    uid, name, rest = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите получателя: реплаем или @ником.")
    if uid == message.from_user.id:
        return await message.reply("Себе передать нельзя 🙂")
    bal = await db.get_grams(message.from_user.id)
    amount = parse_amount(rest, bal, 1)
    if not amount or amount <= 0:
        return await message.reply("Укажите сумму: <code>передать граммы @user 5000</code>")
    if amount > bal:
        return await message.reply(f"Недостаточно. Баланс: <b>{g(bal)}</b>")
    await db.add_grams(message.from_user.id, -amount, "gram_give_out", str(uid))
    await db.add_grams(uid, amount, "gram_give_in", str(message.from_user.id))
    await message.reply(
        f"✅ {mention(message.from_user)} → {mention_id(uid, name)}\n"
        f"Передано: <b>{g(amount)}</b>")


# ═══════════════ СПИСОК ИГР ═══════════════
GAMES_TEXT = f"""🎮 <b>ДОСТУПНЫЕ ИГРЫ</b>

🪙 <b>ОРЁЛ/РЕШКА</b> — <code>орёл 1000</code>
   Угадай сторону монеты · x2

💣 <b>МИНЫ</b> — <code>мины 1000</code>
   Открывай клетки, не наткнись на мину · до x24

🎯 <b>ДАРТС</b> — <code>дартс 1000</code>
   Бросок в мишень · до x3

💥 <b>КРАШ</b> — <code>краш 1000</code>
   Множитель растёт — успей забрать · до x50

🎡 <b>КОЛЕСО</b> — <code>колесо 1000</code>
   Крути барабан удачи · до x10

💣 <b>САПЁР</b> — <code>сапёр 1000</code>
   Дуэль на двоих (ответь на сообщение друга)

🎰 <b>РУЛЕТКА</b> — <code>рулетка красное 1000</code>
   Цвет x2 · число x14

━━━━━━━━━━━━━━━
{GRAM} <code>б</code> — баланс
🎁 <code>бонус граммы</code> — {DAILY_GRAMS:,} в день
🏆 <code>топ граммов</code> — рейтинг"""


@router.message(Cmd("игры", "games", "список игр", section=S, usage="игры",
                    desc="Список игр на граммы"))
async def cmd_games(message: Message, **kw):
    if not await topic_ok(message):
        return
    await message.reply(GAMES_TEXT)


# ═══════════════ 🪙 ОРЁЛ/РЕШКА ═══════════════
@router.message(Cmd("орёл", "орел", "решка", "монета грамм", section=S,
                    usage="орёл {ставка}", desc="🪙 Орёл или решка · x2"))
async def cmd_coin(message: Message, args: str = "", cmd_name: str = "", **kw):
    side = "решка" if cmd_name.startswith("решк") else "орёл"
    bet = await take_bet(message, args)
    if bet is None:
        return
    uid = message.from_user.id
    await db.add_grams(uid, -bet, "gram_bet_coin")
    m = await message.reply(f"🪙 Монета в воздухе… Ваш выбор: <b>{side}</b>")
    await asyncio.sleep(1.5)
    result = random.choice(["орёл", "решка"])
    if result == side:
        bal = await db.add_grams(uid, bet * 2, "gram_win_coin")
        text = (f"🪙 Выпал <b>{result}</b>\n\n"
                f"🎉 <b>Победа!</b> +{g(bet)}\nБаланс: <b>{g(bal)}</b>")
    else:
        bal = await db.get_grams(uid)
        text = (f"🪙 Выпал <b>{result}</b>\n\n"
                f"💔 Проигрыш −{g(bet)}\nБаланс: <b>{g(bal)}</b>")
    try:
        await m.edit_text(text)
    except Exception:
        await message.reply(text)


# ═══════════════ 💣 МИНЫ ═══════════════
_mines: dict[str, dict] = {}
MINE_MULT = [1.0, 1.2, 1.5, 1.9, 2.4, 3.1, 4.0, 5.3, 7.1, 9.7,
             13.5, 19.3, 28.4, 43.2, 68.5, 114, 200, 380, 800, 1900, 6000, 24000]


def _mines_kb(key: str, st: dict, over: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for r in range(5):
        row = []
        for c in range(5):
            i = r * 5 + c
            if i in st["opened"]:
                txt = "💎"
            elif over and i in st["bombs"]:
                txt = "💣"
            else:
                txt = "⬜️"
            row.append(InlineKeyboardButton(
                text=txt, callback_data="mn:x" if over else f"mn:o:{key}:{i}"))
        rows.append(row)
    if not over and st["opened"]:
        mult = MINE_MULT[min(len(st["opened"]), len(MINE_MULT) - 1)]
        rows.append([InlineKeyboardButton(
            text=f"💰 Забрать {int(st['bet'] * mult):,} {GRAM}".replace(",", " "),
            callback_data=f"mn:t:{key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)   # игра — без «в меню»


@router.message(Cmd("мины", "mines", section=S, usage="мины {ставка}",
                    desc="💣 Открывай клетки, не наткнись на мину"))
async def cmd_mines(message: Message, args: str = "", **kw):
    parts = (args or "").split()
    bombs_n = 3
    if len(parts) >= 2 and parts[1].isdigit():
        bombs_n = max(1, min(int(parts[1]), 24))
    bet = await take_bet(message, parts[0] if parts else "")
    if bet is None:
        return
    uid = message.from_user.id
    await db.add_grams(uid, -bet, "gram_bet_mines")
    key = f"{message.chat.id}:{uid}:{int(time.time())}"
    _mines[key] = {"bet": bet, "uid": uid, "opened": set(),
                   "bombs": set(random.sample(range(25), bombs_n))}
    await message.reply(
        f"💣 <b>МИНЫ</b>\nСтавка: <b>{g(bet)}</b> · Мин: <b>{bombs_n}</b>\n\n"
        f"Открывайте клетки. Каждая безопасная повышает множитель.",
        reply_markup=_mines_kb(key, _mines[key]))


@router.callback_query(F.data.startswith("mn:"))
async def cb_mines(call: CallbackQuery):
    parts = call.data.split(":")
    if parts[1] == "x":
        return await call.answer()
    key = parts[2]
    st = _mines.get(key)
    if not st:
        return await call.answer("Игра завершена", show_alert=True)
    if call.from_user.id != st["uid"]:
        return await call.answer("Это не ваша игра", show_alert=True)

    if parts[1] == "t":            # забрать
        _mines.pop(key, None)
        mult = MINE_MULT[min(len(st["opened"]), len(MINE_MULT) - 1)]
        win = int(st["bet"] * mult)
        bal = await db.add_grams(st["uid"], win, "gram_win_mines")
        await call.message.edit_text(
            f"💣 <b>МИНЫ</b> — забрано на x{mult}\n\n"
            f"🎉 Выигрыш: <b>+{g(win - st['bet'])}</b>\nБаланс: <b>{g(bal)}</b>",
            reply_markup=_mines_kb(key, st, over=True))
        return await call.answer("Забрано!")

    idx = int(parts[3])
    if idx in st["opened"]:
        return await call.answer()
    if idx in st["bombs"]:         # взрыв
        _mines.pop(key, None)
        bal = await db.get_grams(st["uid"])
        await call.message.edit_text(
            f"💥 <b>БУМ!</b> Вы наткнулись на мину.\n\n"
            f"💔 Проигрыш: −{g(st['bet'])}\nБаланс: <b>{g(bal)}</b>",
            reply_markup=_mines_kb(key, st, over=True))
        return await call.answer("Мина!", show_alert=True)

    st["opened"].add(idx)
    if len(st["opened"]) >= 25 - len(st["bombs"]):   # всё открыто
        _mines.pop(key, None)
        mult = MINE_MULT[min(len(st["opened"]), len(MINE_MULT) - 1)]
        win = int(st["bet"] * mult)
        bal = await db.add_grams(st["uid"], win, "gram_win_mines")
        await call.message.edit_text(
            f"🏆 <b>ПОЛЕ ОЧИЩЕНО!</b> x{mult}\n\n"
            f"Выигрыш: <b>+{g(win - st['bet'])}</b>\nБаланс: <b>{g(bal)}</b>",
            reply_markup=_mines_kb(key, st, over=True))
        return await call.answer("Идеально!")

    mult = MINE_MULT[min(len(st["opened"]), len(MINE_MULT) - 1)]
    await call.message.edit_text(
        f"💣 <b>МИНЫ</b>\nСтавка: <b>{g(st['bet'])}</b> · "
        f"Открыто: <b>{len(st['opened'])}</b> · Множитель: <b>x{mult}</b>",
        reply_markup=_mines_kb(key, st))
    await call.answer(f"💎 x{mult}")


# ═══════════════ 🎯 ДАРТС ═══════════════
@router.message(Cmd("дартс", "darts", section=S, usage="дартс {ставка}",
                    desc="🎯 Бросок в мишень · до x3"))
async def cmd_darts(message: Message, args: str = "", **kw):
    bet = await take_bet(message, args)
    if bet is None:
        return
    uid = message.from_user.id
    await db.add_grams(uid, -bet, "gram_bet_darts")
    m = await message.answer_dice(emoji="🎯")
    await asyncio.sleep(3.5)
    v = m.dice.value            # 1..6, 6 = яблочко
    mult = {6: 3.0, 5: 2.0, 4: 1.5, 3: 1.0}.get(v, 0)
    names = {6: "🎯 В яблочко!", 5: "Почти центр", 4: "Хорошо",
             3: "Задел мишень", 2: "Край", 1: "Мимо"}
    if mult:
        win = int(bet * mult)
        bal = await db.add_grams(uid, win, "gram_win_darts")
        diff = win - bet
        res = (f"🎉 <b>+{g(diff)}</b>" if diff > 0 else "🔸 Ставка возвращена")
        await message.reply(f"🎯 {names[v]} (x{mult})\n\n{res}\nБаланс: <b>{g(bal)}</b>")
    else:
        bal = await db.get_grams(uid)
        await message.reply(f"🎯 {names.get(v, 'Мимо')}\n\n"
                            f"💔 Проигрыш −{g(bet)}\nБаланс: <b>{g(bal)}</b>")


# ═══════════════ 💥 КРАШ ═══════════════
_crash: dict[str, dict] = {}


@router.message(Cmd("краш", "crash", section=S, usage="краш {ставка}",
                    desc="💥 Множитель растёт — успей забрать"))
async def cmd_crash(message: Message, args: str = "", **kw):
    bet = await take_bet(message, args)
    if bet is None:
        return
    uid = message.from_user.id
    await db.add_grams(uid, -bet, "gram_bet_crash")

    # точка краша: чаще низкая, редко очень высокая
    r = random.random()
    if r < 0.03:
        crash_at = round(random.uniform(10, 50), 2)
    elif r < 0.25:
        crash_at = round(random.uniform(3, 10), 2)
    elif r < 0.65:
        crash_at = round(random.uniform(1.5, 3), 2)
    else:
        crash_at = round(random.uniform(1.0, 1.5), 2)

    key = f"{message.chat.id}:{uid}:{int(time.time()*1000)}"
    _crash[key] = {"bet": bet, "uid": uid, "crash": crash_at,
                   "cur": 1.0, "done": False}

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"cr:{key}")]])
    m = await message.reply(
        f"💥 <b>КРАШ</b>\nСтавка: <b>{g(bet)}</b>\n\n"
        f"📈 Множитель: <b>x1.00</b>\n<i>Успейте забрать до краша!</i>",
        reply_markup=kb)
    asyncio.create_task(_crash_loop(m, key))


async def _crash_loop(msg: Message, key: str) -> None:
    st = _crash.get(key)
    if not st:
        return
    cur = 1.0
    while cur < st["crash"]:
        await asyncio.sleep(1.4)
        st = _crash.get(key)
        if not st or st["done"]:
            return
        cur = round(cur * random.uniform(1.12, 1.35), 2)
        st["cur"] = min(cur, st["crash"])
        if cur >= st["crash"]:
            break
        try:
            await msg.edit_text(
                f"💥 <b>КРАШ</b>\nСтавка: <b>{g(st['bet'])}</b>\n\n"
                f"📈 Множитель: <b>x{st['cur']:.2f}</b>\n"
                f"💰 Сейчас: <b>{g(int(st['bet'] * st['cur']))}</b>",
                reply_markup=msg.reply_markup)
        except Exception:
            pass

    st = _crash.pop(key, None)
    if not st or st["done"]:
        return
    bal = await db.get_grams(st["uid"])
    try:
        await msg.edit_text(
            f"💥 <b>КРАШ на x{st['crash']:.2f}</b>\n\n"
            f"💔 Вы не успели! −{g(st['bet'])}\nБаланс: <b>{g(bal)}</b>")
    except Exception:
        pass


@router.callback_query(F.data.startswith("cr:"))
async def cb_crash(call: CallbackQuery):
    key = call.data.split(":", 1)[1]
    st = _crash.get(key)
    if not st or st["done"]:
        return await call.answer("Раунд окончен", show_alert=True)
    if call.from_user.id != st["uid"]:
        return await call.answer("Это не ваша игра", show_alert=True)
    st["done"] = True
    _crash.pop(key, None)
    mult = st["cur"]
    win = int(st["bet"] * mult)
    bal = await db.add_grams(st["uid"], win, "gram_win_crash")
    try:
        await call.message.edit_text(
            f"💰 <b>ЗАБРАНО на x{mult:.2f}</b>\n\n"
            f"🎉 Выигрыш: <b>+{g(win - st['bet'])}</b>\n"
            f"Баланс: <b>{g(bal)}</b>\n\n"
            f"<i>Краш был бы на x{st['crash']:.2f}</i>")
    except Exception:
        pass
    await call.answer(f"Забрано x{mult:.2f}!")


# ═══════════════ 🎡 КОЛЕСО ═══════════════
WHEEL = [
    (0.0, "💀 Пусто", 34),
    (1.5, "🔸 x1.5", 25),
    (2.0, "🔹 x2", 20),
    (3.0, "✨ x3", 12),
    (5.0, "💎 x5", 6),
    (10.0, "👑 x10", 3),
]


@router.message(Cmd("колесо", "wheel", "колесо удачи", section=S,
                    usage="колесо {ставка}", desc="🎡 Крути барабан · до x10"))
async def cmd_wheel(message: Message, args: str = "", **kw):
    bet = await take_bet(message, args)
    if bet is None:
        return
    uid = message.from_user.id
    await db.add_grams(uid, -bet, "gram_bet_wheel")
    m = await message.reply(f"🎡 <b>КОЛЕСО</b>\nСтавка: <b>{g(bet)}</b>\n\n"
                            f"Крутим… 🌀")
    for frame in ("🎡 ▫️▫️▫️", "🎡 ▪️▫️▫️", "🎡 ▪️▪️▫️", "🎡 ▪️▪️▪️"):
        await asyncio.sleep(0.7)
        try:
            await m.edit_text(f"🎡 <b>КОЛЕСО</b>\nСтавка: <b>{g(bet)}</b>\n\n{frame}")
        except Exception:
            pass

    mult, label, _ = random.choices(WHEEL, weights=[w for *_, w in WHEEL])[0]
    if mult:
        win = int(bet * mult)
        bal = await db.add_grams(uid, win, "gram_win_wheel")
        text = (f"🎡 Выпало: <b>{label}</b>\n\n"
                f"🎉 Выигрыш: <b>+{g(win - bet)}</b>\nБаланс: <b>{g(bal)}</b>")
    else:
        bal = await db.get_grams(uid)
        text = (f"🎡 Выпало: <b>{label}</b>\n\n"
                f"💔 Проигрыш −{g(bet)}\nБаланс: <b>{g(bal)}</b>")
    try:
        await m.edit_text(text)
    except Exception:
        await message.reply(text)


# ═══════════════ 💣 САПЁР (дуэль) ═══════════════
_sapper: dict[str, dict] = {}


@router.message(Cmd("сапёр", "сапер", "sapper", section=S,
                    usage="сапёр {ставка} (реплаем)",
                    desc="💣 Дуэль на двоих: кто взорвётся"))
async def cmd_sapper(message: Message, bot: Bot, args: str = "", **kw):
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply(
            "💣 <b>САПЁР</b> — игра на двоих.\n"
            "Ответьте на сообщение друга: <code>сапёр 1000</code>")
    opp = message.reply_to_message.from_user
    me = message.from_user
    if opp.id == me.id or opp.is_bot:
        return await message.reply("Нужен живой соперник.")
    bet = await take_bet(message, args)
    if bet is None:
        return
    await _ensure_start(opp.id)
    if await db.get_grams(opp.id) < bet:
        return await message.reply(f"У соперника недостаточно граммов.")

    key = f"{message.chat.id}:{me.id}:{opp.id}:{int(time.time())}"
    _sapper[key] = {"bet": bet, "a": me.id, "b": opp.id,
                    "a_name": me.first_name, "b_name": opp.first_name}
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💣 Принять", callback_data=f"sp:ok:{key}"),
        InlineKeyboardButton(text="🚫 Отказ", callback_data=f"sp:no:{key}")]])
    await message.reply(
        f"💣 <b>САПЁР</b>\n\n{mention(me)} вызывает {mention(opp)}\n"
        f"Ставка: <b>{g(bet)}</b>\n\n"
        f"<i>Проигравший «подрывается» и теряет ставку.</i>",
        reply_markup=kb)


@router.callback_query(F.data.startswith("sp:"))
async def cb_sapper(call: CallbackQuery):
    _, action, key = call.data.split(":", 2)
    st = _sapper.get(key)
    if not st:
        return await call.answer("Игра устарела", show_alert=True)
    if call.from_user.id != st["b"]:
        return await call.answer("Вызов не вам", show_alert=True)
    _sapper.pop(key, None)
    if action == "no":
        await call.message.edit_text("🚫 Вызов отклонён.")
        return await call.answer()

    bet = st["bet"]
    if await db.get_grams(st["a"]) < bet or await db.get_grams(st["b"]) < bet:
        return await call.message.edit_text("Недостаточно граммов — игра отменена.")

    await call.message.edit_text("💣 Провода… красный или синий? 🧨")
    await asyncio.sleep(2.5)
    loser, winner = ((st["a"], st["b"]) if random.random() < 0.5
                     else (st["b"], st["a"]))
    await db.add_grams(loser, -bet, "gram_bet_sapper")
    await db.add_grams(winner, bet, "gram_win_sapper")
    wn = st["a_name"] if winner == st["a"] else st["b_name"]
    ln = st["a_name"] if loser == st["a"] else st["b_name"]
    bal = await db.get_grams(winner)
    await call.message.edit_text(
        f"💥 <b>БУМ!</b>\n\n"
        f"💀 {mention_id(loser, ln)} подорвался\n"
        f"🏆 {mention_id(winner, wn)} забирает <b>{g(bet)}</b>\n\n"
        f"Баланс победителя: <b>{g(bal)}</b>")
    await call.answer()


# ═══════════════ 🎰 РУЛЕТКА ═══════════════
RED = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}


@router.message(Cmd("рулетка граммы", "грамм рулетка", section=S,
                    usage="рулетка красное 1000", desc="🎰 Рулетка на граммы"))
async def cmd_roulette(message: Message, args: str = "", **kw):
    parts = (args or "").split()
    if len(parts) < 2:
        return await message.reply(
            "🎰 <b>РУЛЕТКА</b>\n\n"
            "<code>рулетка красное 1000</code> — цвет, x2\n"
            "<code>рулетка чёт 1000</code> — чёт/нечет, x2\n"
            "<code>рулетка 17 1000</code> — число 0-36, x14\n"
            "<code>рулетка зеро 1000</code> — зеро, x14")
    choice = parts[0].lower()
    bet = await take_bet(message, parts[1])
    if bet is None:
        return
    uid = message.from_user.id
    await db.add_grams(uid, -bet, "gram_bet_roulette")
    m = await message.reply("🎰 Шарик крутится… 🌀")
    await asyncio.sleep(2)

    num = random.randint(0, 36)
    color = "зеро" if num == 0 else ("красное" if num in RED else "чёрное")
    mult = 0
    if choice in {"красное", "красн", "кр", "red"} and color == "красное":
        mult = 2
    elif choice in {"чёрное", "черное", "чёрн", "чер", "black"} and color == "чёрное":
        mult = 2
    elif choice in {"чёт", "чет", "even"} and num and num % 2 == 0:
        mult = 2
    elif choice in {"нечёт", "нечет", "odd"} and num % 2 == 1:
        mult = 2
    elif choice in {"зеро", "zero"} and num == 0:
        mult = 14
    elif choice.isdigit() and int(choice) == num:
        mult = 14

    emoji = "🟢" if num == 0 else ("🔴" if num in RED else "⚫️")
    if mult:
        win = bet * mult
        bal = await db.add_grams(uid, win, "gram_win_roulette")
        text = (f"🎰 Выпало: {emoji} <b>{num} {color}</b>\n\n"
                f"🎉 Выигрыш x{mult}: <b>+{g(win - bet)}</b>\n"
                f"Баланс: <b>{g(bal)}</b>")
    else:
        bal = await db.get_grams(uid)
        text = (f"🎰 Выпало: {emoji} <b>{num} {color}</b>\n\n"
                f"💔 Проигрыш −{g(bet)}\nБаланс: <b>{g(bal)}</b>")
    try:
        await m.edit_text(text)
    except Exception:
        await message.reply(text)


# ═══════════════ АДМИН ═══════════════
@router.message(Cmd("выдать граммы", "начислить граммы", section=S, rank=6,
                    usage="выдать граммы {ссылка} {сумма}",
                    desc="Начислить граммы (техадмин)"))
async def cmd_give_admin(message: Message, bot: Bot, args: str = "", **kw):
    from core_ranks import require
    if not await require(message, bot, 6):
        return
    uid, name, rest = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя.")
    amount = parse_amount(rest, 10**12, 1)
    if not amount:
        return await message.reply("Укажите сумму.")
    bal = await db.add_grams(uid, amount, "gram_admin_add", str(message.from_user.id))
    await message.reply(f"✅ {mention_id(uid, name)} получил <b>{g(amount)}</b>\n"
                        f"Баланс: <b>{g(bal)}</b>")


# ═══════════════ ПРИВЯЗКА ТЕМЫ ═══════════════
@router.message(Cmd("тема граммов", "тема граммы", "тема грамм", "тема казино",
                    "тема игр", "тема игры", "грамм тема", section=S, rank=4,
                    usage="тема граммов [ссылка]",
                    desc="Тема, где работают команды граммов"))
async def cmd_gram_topic(message: Message, bot: Bot, args: str = "", **kw):
    from core_ranks import require
    if not await require(message, bot, 4):
        return
    a = (args or "").strip()

    if a.lower() in {"сброс", "убрать", "выкл", "off"}:
        await db.set_setting(message.chat.id, "gram_topic", "0")
        return await message.reply("✅ Привязка снята — команды граммов работают везде.")

    import re as _re
    tid = 0
    m = _re.search(r"t\.me/c/\d+/(\d+)", a)
    if m:
        tid = int(m.group(1))
    elif a.isdigit():
        tid = int(a)
    elif not a:
        tid = _tid(message)

    if not tid:
        cur = await get_gram_topic(message.chat.id)
        cur_txt = (f"Сейчас: {_tlink(message.chat.id, cur)}" if cur else "Сейчас: не задана")
        return await message.reply(
            f"💊 <b>Тема для граммов</b>\n\n{cur_txt}\n\n"
            f"Установить — напишите команду <b>в нужной теме</b>:\n"
            f"<code>тема граммов</code>\n\n"
            f"Или ссылкой:\n<code>тема граммов https://t.me/c/123456/789</code>\n\n"
            f"Снять: <code>тема граммов сброс</code>",
            disable_web_page_preview=True)

    await db.set_setting(message.chat.id, "gram_topic", str(tid))
    await message.reply(
        f"✅ <b>Тема для граммов установлена</b>\n\n💊 {_tlink(message.chat.id, tid)}\n\n"
        f"Все команды граммов и игры теперь работают <b>только там</b>.",
        disable_web_page_preview=True)


# ═══════════════ ОБМЕН ГРАММЫ ⇄ ИРИСКИ ═══════════════
RATE = 20          # 20 граммов = 1 ириска (200 💊 → 10 🪙)


@router.message(Cmd("обмен", "обменять", "курс", "exchange", section=S,
                    usage="обмен {сумма}",
                    desc=f"Обменять граммы на ириски ({RATE}💊 = 1🪙)"))
async def cmd_exchange(message: Message, args: str = "", **kw):
    if not await topic_ok(message):
        return
    uid = message.from_user.id
    await _ensure_start(uid)
    bal_g = await db.get_grams(uid)
    u = await db.get_user(uid)

    a = (args or "").strip()
    if not a:
        return await message.reply(
            f"💱 <b>ОБМЕН</b>\n\n"
            f"Курс: <b>{RATE} {GRAM} = 1 🪙</b>\n"
            f"(200 {GRAM} → 10 🪙)\n\n"
            f"💊 Граммы: <b>{bal_g:,}</b>\n".replace(",", " ") +
            f"🪙 Ириски: <b>{u['balance']:,}</b>\n\n".replace(",", " ") +
            f"<code>обмен 200</code> — обменять 200 граммов\n"
            f"<code>обмен все</code> — обменять всё\n"
            f"<code>обмен обратно 10</code> — ириски → граммы")

    # обратный обмен: ириски → граммы
    if a.lower().startswith(("обратно", "назад", "back")):
        rest = a.split(maxsplit=1)[1] if len(a.split()) > 1 else ""
        amount = parse_amount(rest, u["balance"], 1)
        if not amount or amount <= 0:
            return await message.reply("Укажите сумму: <code>обмен обратно 10</code>")
        if amount > u["balance"]:
            return await message.reply(f"Недостаточно ирисок: {u['balance']:,}".replace(",", " "))
        got = amount * RATE
        await db.add_balance(uid, -amount, "exchange_out")
        new_g = await db.add_grams(uid, got, "exchange_in")
        return await message.reply(
            f"💱 <b>Обмен выполнен</b>\n\n"
            f"Отдали: <b>{amount:,} 🪙</b>\n".replace(",", " ") +
            f"Получили: <b>{g(got)}</b>\n\n"
            f"💊 {new_g:,} · 🪙 {u['balance'] - amount:,}".replace(",", " "))

    amount = parse_amount(a, bal_g, RATE)
    if not amount or amount < RATE:
        return await message.reply(f"Минимум {RATE} граммов за обмен.")
    if amount > bal_g:
        return await message.reply(f"Недостаточно граммов: <b>{g(bal_g)}</b>")

    got = amount // RATE
    spend = got * RATE          # без потери остатка
    if got < 1:
        return await message.reply(f"Слишком мало. Минимум {RATE} {GRAM}.")
    await db.add_grams(uid, -spend, "exchange_out")
    new_i = await db.add_balance(uid, got, "exchange_in")
    new_g = await db.get_grams(uid)
    await message.reply(
        f"💱 <b>Обмен выполнен</b>\n\n"
        f"Отдали: <b>{g(spend)}</b>\n"
        f"Получили: <b>{got:,} 🪙</b>\n\n".replace(",", " ") +
        f"💊 {new_g:,} · 🪙 {new_i:,}".replace(",", " "))


# ═══════════════ ВЫПКА (VIP) ЗА ИРИСКИ ═══════════════
VIP_PRICE = 100_000     # в ирисках 🪙
VIP_DAYS = 5


@router.message(Cmd("выпка", "купить выпку", "вypka", section=S,
                    usage="выпка",
                    desc=f"Купить выпку на {VIP_DAYS} дней за {VIP_PRICE:,} ирисок"))
async def cmd_vip(message: Message, **kw):
    if not await topic_ok(message):
        return
    uid = message.from_user.id
    await _ensure_start(uid)
    row = await db.fetchone("SELECT until FROM vip WHERE user_id=?", (uid,))
    active = row and row["until"] > time.time()
    left = ""
    if active:
        d = int((row["until"] - time.time()) // 86400)
        h = int(((row["until"] - time.time()) % 86400) // 3600)
        left = f"\n\n✅ <b>Выпка активна</b> ещё {d} д {h} ч"
    u = await db.get_user(uid)
    bal_g = await db.get_grams(uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"🪙 Купить за {VIP_PRICE:,}".replace(",", " "),
                             callback_data="vipbuy")]])
    await message.reply(
        f"👑 <b>ВЫПКА</b> — {VIP_DAYS} дней за <b>{VIP_PRICE:,} 🪙</b>\n\n".replace(",", " ") +
        f"Что даёт:\n"
        f"• ×2 к ежедневному бонусу ирисок\n"
        f"• ×2 к ежедневному бонусу граммов\n"
        f"• 👑 значок в профиле\n\n"
        f"Ваш баланс: <b>{u['balance']:,} 🪙</b> · {g(bal_g)}\n".replace(",", " ") +
        f"<i>Не хватает ирисок? </i><code>обмен 2000</code>{left}",
        reply_markup=kb)


@router.callback_query(F.data == "vipbuy")
async def cb_vip(call: CallbackQuery):
    uid = call.from_user.id
    u = await db.get_user(uid)
    if u["balance"] < VIP_PRICE:
        return await call.answer(
            f"Недостаточно ирисок.\nНужно {VIP_PRICE:,}, у вас {u['balance']:,}\n"
            f"Обменяйте граммы: обмен 2000".replace(",", " "),
            show_alert=True)
    await db.add_balance(uid, -VIP_PRICE, "vip_buy")
    row = await db.fetchone("SELECT until FROM vip WHERE user_id=?", (uid,))
    base = max(int(time.time()), int(row["until"]) if row else 0)
    until = base + VIP_DAYS * 86400
    await db.execute(
        "INSERT INTO vip (user_id, until, level) VALUES (?,?,1) "
        "ON CONFLICT(user_id) DO UPDATE SET until=excluded.until", (uid, until))
    nu = await db.get_user(uid)
    try:
        await call.message.edit_text(
            f"👑 <b>Выпка куплена!</b>\n\n"
            f"Срок: <b>{VIP_DAYS} дней</b>\n"
            f"Списано: <b>{VIP_PRICE:,} 🪙</b>\n".replace(",", " ") +
            f"Баланс: <b>{nu['balance']:,} 🪙</b>".replace(",", " "))
    except Exception:
        pass
    await call.answer("👑 Выпка активирована!")


# ═══════════════ ВЫДАЧА ВЫПКИ АДМИНОМ ═══════════════
@router.message(Cmd("выдать выпку", "дать выпку", "+выпка", "выпку",
                    "начислить выпку", section=S, rank=4,
                    usage="выдать выпку @ник 7 дней",
                    desc="Выдать участнику выпку бесплатно (ранг 4+)"))
async def cmd_vip_give(message: Message, bot: Bot, args: str = "", **kw):
    """Админ выдаёт выпку без списания ирисок.

    выдать выпку @ник 7 дней   — на срок
    выдать выпку @ник          — на 5 дней по умолчанию
    выдать выпку @ник навсегда — бессрочно
    """
    from core_ranks import require
    if not await require(message, bot, 4):
        return

    a = (args or "").strip()
    if not a and not message.reply_to_message:
        return await message.reply(
            "👑 <b>Выдать выпку</b>\n\n"
            "<code>выдать выпку @ник 7 дней</code>\n"
            "<code>выдать выпку @ник 1 месяц</code>\n"
            "<code>выдать выпку @ник навсегда</code>\n"
            "<code>выдать выпку @ник</code> — на 5 дней\n\n"
            "Или ответом на сообщение человека.\n\n"
            "Снять: <code>снять выпку @ник</code>\n"
            "Список: <code>кто с выпкой</code>")

    uid, name, rest = await resolve_target(message, a, bot)
    if not uid:
        return await message.reply(
            "🤔 Кому выдать? Укажите <code>@ник</code> "
            "или ответьте на сообщение человека.")

    rest = (rest or "").strip().lower()
    forever = rest in {"навсегда", "вечно", "бессрочно", "forever"}
    if forever:
        secs = 0
    else:
        secs, _ = parse_period(rest)
        if not secs:
            secs = VIP_DAYS * 86400

    row = await db.fetchone("SELECT until FROM vip WHERE user_id=?", (uid,))
    had = row and int(row["until"] or 0) > int(time.time())
    if forever:
        until = 4102444800          # 01.01.2100 — практически навсегда
    else:
        base = max(int(time.time()), int(row["until"]) if row else 0)
        until = base + secs

    await db.execute(
        "INSERT INTO vip (user_id, until, level) VALUES (?,?,1) "
        "ON CONFLICT(user_id) DO UPDATE SET until=excluded.until", (uid, until))

    term = "навсегда" if forever else human_period(secs)
    when = ("" if forever else
            f"\n📅 До: <b>{time.strftime('%d.%m.%Y %H:%M', time.localtime(until))}</b>")
    await message.reply(
        f"👑 <b>Выпка выдана</b>\n"
        f"👤 {mention_id(uid, name)}\n"
        f"⏱ Срок: <b>{term}</b>"
        f"{' <i>(продлена)</i>' if had and not forever else ''}"
        f"{when}\n"
        f"🎁 Бесплатно, от {mention_id(message.from_user.id, message.from_user.first_name)}")

    try:
        await bot.send_message(
            uid,
            f"👑 <b>Вам выдали выпку!</b>\n\n"
            f"⏱ Срок: <b>{term}</b>{when}\n\n"
            f"Что даёт: удвоенный бонус, приоритет в играх "
            f"и значок 👑 в профиле.")
    except Exception:
        pass


@router.message(Cmd("снять выпку", "убрать выпку", "-выпка", "забрать выпку",
                    section=S, rank=4, usage="снять выпку @ник",
                    desc="Снять выпку у участника (ранг 4+)"))
async def cmd_vip_take(message: Message, bot: Bot, args: str = "", **kw):
    from core_ranks import require
    if not await require(message, bot, 4):
        return
    a = (args or "").strip()
    uid, name, _ = await resolve_target(message, a, bot)
    if not uid:
        return await message.reply(
            "🤔 У кого снять? Укажите <code>@ник</code> или ответьте "
            "на сообщение.")
    row = await db.fetchone("SELECT until FROM vip WHERE user_id=?", (uid,))
    if not row or int(row["until"] or 0) <= int(time.time()):
        return await message.reply(f"У {mention_id(uid, name)} и так нет выпки.")
    await db.execute("DELETE FROM vip WHERE user_id=?", (uid,))
    await message.reply(f"🚫 Выпка снята у {mention_id(uid, name)}")


@router.message(Cmd("кто с выпкой", "список выпок", "выпки", "вип лист",
                    section=S, rank=1, usage="кто с выпкой",
                    desc="Список участников с выпкой"))
async def cmd_vip_list(message: Message, bot: Bot, **kw):
    from core_ranks import require
    if not await require(message, bot, 1):
        return
    now = int(time.time())
    rows = await db.fetchall(
        "SELECT v.user_id, v.until, u.first_name, u.username FROM vip v "
        "LEFT JOIN users u ON u.user_id=v.user_id "
        "WHERE v.until > ? ORDER BY v.until DESC LIMIT 40", (now,))
    if not rows:
        return await message.reply(
            "👑 Сейчас ни у кого нет выпки.\n\n"
            "Выдать: <code>выдать выпку @ник 7 дней</code>")
    out = [f"👑 <b>С выпкой: {len(rows)}</b>\n"]
    for r in rows:
        nm = r["first_name"] or (f"@{r['username']}" if r["username"] else str(r["user_id"]))
        left = int(r["until"]) - now
        term = "навсегда" if int(r["until"]) > 4000000000 else human_period(left)
        out.append(f"👑 {mention_id(r['user_id'], nm)} — ещё {term}")
    await message.reply("\n".join(out), disable_web_page_preview=True)
