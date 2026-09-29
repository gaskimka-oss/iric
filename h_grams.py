"""Монеты-бот: игровая валюта «монеты» 🪙, предприятия, динамический рынок и игры.

Игры: слоты/казино, орёл/решка, мины, дартс, краш, колесо, сапёр (на двоих), кубик, рулетка.
Бизнесы и недвижимость: фермы, аренда домов, заводы, ТЦ, шахты, электростанции, вышки, космодромы.
Динамический рынок: цены колеблются каждый час в зависимости от спроса.
Игровой уровень: прокачка за игры в казино и открытие новых бизнесов.
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
from utils import hms, mention, mention_id, parse_amount, money

router = Router(name="grams")
S = 33  # раздел «Монеты, бизнесы и игры»

COIN = "🌑"
COINS = COIN
COMET = COIN
GRAM = COIN  # алиас для совместимости
MIN_BET = 100
MAX_BET = 50_000_000
DAILY_COINS = 100_000
DAILY_COMETS = DAILY_COINS
DAILY_GRAMS = DAILY_COINS
DAILY_CD = 24 * 3600
START_COINS = 10_000
START_COMETS = START_COINS
START_GRAMS = START_COINS


def c(n: int) -> str:
    """Форматирование: 1 500 000 → 1 500 000 🌑"""
    return f"{n:,}".replace(",", " ") + f" {COIN}"


g = c  # алиас для совместимости


# ═══════════════ СПИСОК ПРЕДПРИЯТИЙ И НЕДВИЖИМОСТИ ═══════════════
BUSINESS_TYPES: dict[str, dict] = {
    "farm": {
        "name": "Ферма",
        "emoji": "🌾",
        "base_price": 5_000,
        "income_per_min": 15,
        "req_lvl": 1,
        "desc": "Выращивание урожая и органических культур",
        "aliases": ["ферма", "ферму", "фермы", "farm", "1"]
    },
    "house": {
        "name": "Дом в аренду",
        "emoji": "🏠",
        "base_price": 18_000,
        "income_per_min": 55,
        "req_lvl": 2,
        "desc": "Сдача коттеджа жильцам",
        "aliases": ["дом", "дом в аренду", "коттедж", "аренда", "house", "2"]
    },
    "factory": {
        "name": "Завод",
        "emoji": "🏭",
        "base_price": 60_000,
        "income_per_min": 200,
        "req_lvl": 3,
        "desc": "Производство электроники и товаров",
        "aliases": ["завод", "заводы", "фабрика", "factory", "3"]
    },
    "mall": {
        "name": "Торговый центр",
        "emoji": "🏢",
        "base_price": 200_000,
        "income_per_min": 750,
        "req_lvl": 4,
        "desc": "Аренда бутиков и магазинов",
        "aliases": ["тц", "торговый центр", "бизнес-центр", "бц", "mall", "4"]
    },
    "mine": {
        "name": "Крипто-шахта",
        "emoji": "⛏",
        "base_price": 750_000,
        "income_per_min": 3_000,
        "req_lvl": 5,
        "desc": "Добыча редких кристаллов и крипто-руды",
        "aliases": ["шахта", "шахту", "крипто-шахта", "криптошахта", "mine", "5"]
    },
    "power": {
        "name": "Электростанция",
        "emoji": "⚡",
        "base_price": 2_500_000,
        "income_per_min": 11_000,
        "req_lvl": 6,
        "desc": "Генерация энергии для мегаполиса",
        "aliases": ["станция", "электростанция", "аэс", "гэс", "power", "6"]
    },
    "rig": {
        "name": "Нефтяная вышка",
        "emoji": "🛢",
        "base_price": 8_000_000,
        "income_per_min": 38_000,
        "req_lvl": 8,
        "desc": "Добыча и переработка чёрного золота",
        "aliases": ["вышка", "вышку", "нефтяная вышка", "нефть", "rig", "7"]
    },
    "space": {
        "name": "Космодром",
        "emoji": "🚀",
        "base_price": 30_000_000,
        "income_per_min": 160_000,
        "req_lvl": 10,
        "desc": "Запуск коммерческих шаттлов и спутников",
        "aliases": ["космодром", "ракета", "space", "8"]
    },
}


def get_market_multiplier(biz_key: str) -> float:
    """Динамический множитель рынка (меняется каждый час, от 0.80 до 1.30)."""
    hour_seed = int(time.time() // 3600)
    # Псевдослучайный хэш для стабильности в течение часа
    h = (abs(hash(f"{biz_key}:{hour_seed}")) % 1000)
    return round(0.80 + (h / 1000.0) * 0.50, 2)


def get_market_price(biz_key: str, is_sell: bool = False) -> tuple[int, str]:
    """Возвращает (цена_акции, тренд_строка)."""
    info = BUSINESS_TYPES.get(biz_key)
    if not info:
        return 0, "➡️ 0%"
    mult = get_market_multiplier(biz_key)
    base = info["base_price"]
    if is_sell:
        price = max(1, int(base * mult * 0.90))  # 10% комиссия брокера при продаже
    else:
        price = max(1, int(base * mult))

    diff_pct = int(round((mult - 1.0) * 100))
    if diff_pct > 5:
        trend = f"📈 +{diff_pct}%"
    elif diff_pct < -5:
        trend = f"📉 {diff_pct}%"
    else:
        trend = f"➡️ ~0%"
    return price, trend


def find_business_by_alias(query: str) -> tuple[str | None, dict | None]:
    q = (query or "").strip().lower()
    for k, v in BUSINESS_TYPES.items():
        if q == k or q in v["aliases"] or q.startswith(v["name"].lower()):
            return k, v
    return None, None


async def _ensure_start(uid: int) -> None:
    """Первый вход — выдаём стартовые монеты."""
    u = await db.get_user(uid)
    if u["grams"] == 0:
        row = await db.fetchone(
            "SELECT 1 FROM log WHERE user_id=? AND action='gram_start'", (uid,))
        if not row:
            await db.add_coins(uid, START_COINS, "gram_start")


async def get_gram_topic(chat_id: int) -> int:
    from core_seed import MAIN_CHAT
    default_val = "132681" if (chat_id == MAIN_CHAT or str(chat_id).endswith("3934033202")) else "0"
    v = await db.get_setting(chat_id, "gram_topic", default_val)
    try:
        val = int(v)
        if val == 0 and (chat_id == MAIN_CHAT or str(chat_id).endswith("3934033202")):
            return 132681
        return val
    except ValueError:
        return 132681 if (chat_id == MAIN_CHAT or str(chat_id).endswith("3934033202")) else 0


def _tid(message: Message) -> int:
    return int(getattr(message, "message_thread_id", None) or 0)


def _tlink(chat_id: int, tid: int) -> str:
    cid = str(chat_id)
    short = cid[4:] if cid.startswith("-100") else cid.lstrip("-")
    return f"https://t.me/c/{short}/{tid}"


async def topic_ok(message: Message) -> bool:
    """Проверяет тему для игр, казино, заработка, ограблений и монет."""
    if message.chat.type == "private":
        return True
    ft = await get_gram_topic(message.chat.id)
    if not ft:
        return True

    tid = _tid(message)
    if tid == ft:
        return True

    chat_id = message.chat.id
    text = (
        f"❌ {mention(message.from_user)}, здесь нельзя играть и совершать операции с валютой!\n\n"
        f"🎰 <b>Игры, казино, работа, ограбления и монеты</b> — только в этой теме:\n"
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
    """Проверяет ставку в монетах."""
    if not await topic_ok(message):
        return None
    uid = message.from_user.id
    await _ensure_start(uid)
    bal = await db.get_coins(uid)
    bet = parse_amount(raw, bal, MIN_BET)
    if not bet or bet < MIN_BET:
        await message.reply(
            f"Минимальная ставка — <b>{c(MIN_BET)}</b>\n"
            f"Ваш баланс: <b>{c(bal)}</b>\n\n"
            f"Пример: <code>орёл 1000</code> · <code>мины 5к</code> · "
            f"<code>краш все</code>")
        return None
    if bet > MAX_BET:
        await message.reply(f"Максимальная ставка — <b>{c(MAX_BET)}</b>")
        return None
    if bet > bal:
        await message.reply(f"Недостаточно монет.\nВаш баланс: <b>{c(bal)}</b>")
        return None
    return bet


# ═══════════════ БАЛАНС И СТАТИСТИКА ═══════════════
@router.message(Cmd("б", "баланс", "монеты", "коины", "граммы", "деньги", "мои монеты", "баланс монет", "мои коины", "мои граммы", "б монет", "coins", "grams", section=S,
                    usage="б", desc="Финансовый профиль и баланс"))
async def cmd_balance(message: Message, bot: Bot, args: str = "", **kw):
    if not await topic_ok(message):
        return
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        uid, name = message.from_user.id, message.from_user.first_name
    await _ensure_start(uid)

    bal = await db.get_balance(uid)

    # Игровой уровень и опыт
    prof = await db.get_game_profile(uid)
    lvl = prof["level"]
    xp = prof["xp"]
    next_xp = prof["next_xp"]
    pct = prof["progress_pct"]
    bar_len = 10
    filled = int((pct / 100) * bar_len)
    bar = "▰" * filled + "▱" * (bar_len - filled)

    # Бизнесы и пассивный доход
    user_biz = await db.get_user_businesses(uid)
    total_biz = sum(b["count"] for b in user_biz.values())
    income_min = sum(user_biz[k]["count"] * BUSINESS_TYPES[k]["income_per_min"] for k in user_biz if k in BUSINESS_TYPES)

    # Проверка защиты мешка
    hide_left = await db.cooldown_left(uid, "bag_hidden", 5 * 3600)
    bag_status = f"🛡 Защищён ({hms(hide_left)})" if hide_left else "🔓 Открыт для воров"

    # Бонус
    vip_lvl, _, vip_active = await db.get_vip_info(uid)
    cd = 3600 if (vip_active and vip_lvl >= 2) else (7200 if (vip_active and vip_lvl >= 1) else 14400)
    left_bonus = await db.cooldown_left(uid, "gram_daily", cd)
    if left_bonus:
        bonus_line = f"⏳ Бонус через: <b>{hms(left_bonus)}</b>"
    else:
        bonus_line = f"🎁 <b>Бонус готов!</b> Заберите <code>бонус</code>"

    txt = (
        f"💳 <b>ФИНАНСОВЫЙ ПРОФИЛЬ</b>\n"
        f"👤 {mention_id(uid, name)}\n\n"
        f"🌑 <b>Баланс:</b> <code>{c(bal)}</code>\n\n"
        f"🎮 <b>Игровой уровень:</b> <b>{lvl} LVL</b> ({xp}/{next_xp} XP)\n"
        f"📊 Прогресс: <code>[{bar}]</code> {pct}%\n"
        f"🎲 Сыграно игр: <b>{prof['games_played']}</b> (побед: {prof['games_won']})\n\n"
        f"🏢 <b>Предприятия:</b> <b>{total_biz} шт.</b>\n"
        f"💵 Доход: <b>+{income_min:,} 🌑/мин</b>\n"
        f"🔒 Мешок: <b>{bag_status}</b>\n\n"
        f"{bonus_line}\n"
        f"💡 <i>Команды:</i> <code>бизнесы</code> · <code>игры</code> · <code>скрыть мешок</code>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏢 Мои бизнесы", callback_data="biz:menu"),
        InlineKeyboardButton(text="💰 Собрать прибыль", callback_data="biz:collect")
    ]])
    await message.reply(txt, reply_markup=kb)


@router.message(Cmd("бонус", "бонус монет", "бонус коинов", "бонус грамм", "монеты бонус", "ежедневный бонус", section=S,
                    usage="бонус", desc=f"Бонус {DAILY_COINS:,} монет"))
async def cmd_daily(message: Message, **kw):
    if not await topic_ok(message):
        return
    uid = message.from_user.id
    await _ensure_start(uid)
    vip_lvl, _, vip_active = await db.get_vip_info(uid)
    cd = 3600 if (vip_active and vip_lvl >= 2) else (7200 if (vip_active and vip_lvl >= 1) else 14400)
    left = await db.cooldown_left(uid, "gram_daily", cd)
    if left:
        return await message.reply(f"⏳ Бонус уже получен.\nСледующий через <b>{hms(left)}</b>")
    bal = await db.add_balance(uid, DAILY_COINS, "daily_bonus")
    await db.set_cooldown(uid, "gram_daily")
    await message.reply(
        f"🎁 <b>Ежедневный бонус!</b>\n\n"
        f"Начислено: <b>+{c(DAILY_COINS)}</b> 🎉\n"
        f"Ваш баланс: <b>{c(bal)}</b>")


@router.message(Cmd("топ", "топ монет", "топ игроков", "топ коинов", "топ грамм", "топ грами", "топ богатых", "топ баланс", "топ по ирискам", "топ ирисок", section=S,
                    usage="топ", desc="Богатейшие игроки"))
async def cmd_top(message: Message, **kw):
    if not await topic_ok(message):
        return
    rows = await db.fetchall(
        "SELECT user_id, first_name, balance FROM users WHERE balance > 0 "
        "ORDER BY balance DESC LIMIT 10")
    if not rows:
        return await message.reply("Пока никто не играл.")
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    await message.reply(f"🌑 <b>Топ игроков по балансу</b>\n\n" + "\n".join(
        f"{medals[i]} {mention_id(r['user_id'], r['first_name'])} — {c(r['balance'])}"
        for i, r in enumerate(rows)))


@router.message(Cmd("восстановить топ", "сброс топа", "сбросить топ", "вернуть топ", "фикс топа", "исправить топ",
                    "restore top", "reset top", rank=6, section=S,
                    usage="восстановить топ", desc="Восстановить эталонный топ балансов и сбросить баганные триллионы"))
async def cmd_restore_top(message: Message, bot: Bot, **kw):
    from core_ranks import require
    if not await require(message, bot, 6):
        return
    
    res = await db.reset_all_businesses_and_levels()
    rows = await db.fetchall(
        "SELECT user_id, first_name, balance FROM users WHERE balance > 0 "
        "ORDER BY balance DESC LIMIT 10")
    
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    top_lines = "\n".join(
        f"{medals[i]} {mention_id(r['user_id'], r['first_name'])} — {c(r['balance'])}"
        for i, r in enumerate(rows))
    
    await message.reply(
        f"🏆 <b>Эталонный топ балансов успешно восстановлен!</b>\n\n"
        f"✅ Сброшены накрученные триллионы и баги\n"
        f"✅ Снесено накрученных предприятий: <b>{res['businesses_deleted']}</b> шт.\n"
        f"✅ Сброшены уровни казино у <b>{res['stats_reset']}</b> пользователей\n\n"
        f"🌑 <b>Актуальный топ по балансу:</b>\n{top_lines}")


@router.message(Cmd("снести фермы", "сброс ферм", "сбросить фермы", "снести бизнесы", "сброс бизнесов",
                    "сбросить бизнесы", "сброс экономики", "сбросить экономику", "снести все фермы",
                    "вайп ферм", "вайп бизнесов", "вайп экономики", "сброс уровней", "reset biz",
                    rank=6, section=S,
                    usage="снести фермы", desc="Снести все купленные фермы/заводы, сбросить уровни и вернуть балансы"))
async def cmd_wipe_businesses(message: Message, bot: Bot, **kw):
    from core_ranks import require
    if not await require(message, bot, 6):
        return

    res = await db.reset_all_businesses_and_levels()
    rows = await db.fetchall(
        "SELECT user_id, first_name, balance FROM users WHERE balance > 0 "
        "ORDER BY balance DESC LIMIT 10")

    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    top_lines = "\n".join(
        f"{medals[i]} {mention_id(r['user_id'], r['first_name'])} — {c(r['balance'])}"
        for i, r in enumerate(rows))

    await message.reply(
        f"🧹 <b>Экономика и имущество полностью очищены!</b>\n\n"
        f"✅ <b>Снесено предприятий:</b> {res['businesses_deleted']} шт. (все фермы, заводы, дома, ТЦ, шахты удалены)\n"
        f"✅ <b>Сброшены уровни казино:</b> у {res['stats_reset']} игроков\n"
        f"✅ <b>Балансы игроков:</b> возвращены к исходному состоянию до ошибки!\n\n"
        f"🌑 <b>Актуальный эталонный топ:</b>\n{top_lines}")


@router.message(Cmd("п", "п.", "передать", "перевод", "дать", "передать монеты", "дать монеты", "перевод монет",
                    "передать коины", "дать коины", "передать граммы", "дать граммы", "pay", "give", section=S,
                    usage="п {ссылка} {сумма}", desc="Передать валюту 🌑"))
async def cmd_give(message: Message, bot: Bot, args: str = "", **kw):
    if not await topic_ok(message):
        return
    uid, name, rest = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите получателя: реплаем или @ником.\nПример: <code>п @user 5000</code> или <code>п 5000</code> ответом")
    if uid == message.from_user.id:
        return await message.reply("Себе передать нельзя 🙂")
    bal = await db.get_balance(message.from_user.id)
    amount = parse_amount(rest, bal, 1)
    if not amount or amount <= 0:
        return await message.reply("Укажите сумму: <code>п @user 5000</code> или <code>п 5000</code> ответом")
    if amount > bal:
        return await message.reply(f"Недостаточно средств.\nВаш баланс: <b>{c(bal)}</b>")
    
    sender_bal = await db.add_balance(message.from_user.id, -amount, "give_out", str(uid))
    await db.add_balance(uid, amount, "give_in", str(message.from_user.id))
    await message.reply(
        f"✅ {mention(message.from_user)} ➡️ {mention_id(uid, name)}\n"
        f"Передано: <b>{c(amount)}</b>\n"
        f"Остаток на балансе: <b>{c(sender_bal)}</b>")



# ═══════════════ СИСТЕМА БИЗНЕСОВ И РЫНКА ═══════════════
def _render_biz_menu(uid: int, user_biz: dict[str, dict], prof: dict) -> tuple[str, InlineKeyboardMarkup]:
    lvl = prof["level"]
    now = int(time.time())

    # Подсчет дохода и накопленной прибыли
    total_income_min = 0
    accumulated_profit = 0
    owned_lines = []

    for k, info in BUSINESS_TYPES.items():
        cnt = user_biz.get(k, {}).get("count", 0)
        if cnt > 0:
            last_col = user_biz[k].get("last_collect", now)
            mins = min(24 * 60, max(0, int((now - last_col) // 60)))
            profit = mins * cnt * info["income_per_min"]
            total_income_min += cnt * info["income_per_min"]
            accumulated_profit += profit
            owned_lines.append(f"• {info['emoji']} <b>{info['name']}:</b> {cnt} шт. (доход: +{cnt*info['income_per_min']:,} 🌑/мин)")

    market_lines = []
    for k, info in BUSINESS_TYPES.items():
        buy_p, trend = get_market_price(k, is_sell=False)
        sell_p, _ = get_market_price(k, is_sell=True)
        lock = "🔒 " if lvl < info["req_lvl"] else "✅ "
        lvl_note = f"<i>(с {info['req_lvl']} LVL)</i>" if lvl < info["req_lvl"] else ""
        market_lines.append(
            f"{lock}{info['emoji']} <b>{info['name']}</b> {lvl_note}\n"
            f"   Купить: <b>{c(buy_p)}</b> [{trend}] · Продать: <b>{c(sell_p)}</b>\n"
            f"   Доход: <code>+{info['income_per_min']} 🌑/мин</code>"
        )

    owned_txt = "\n".join(owned_lines) if owned_lines else "<i>У вас пока нет купленных предприятий.</i>"
    market_txt = "\n\n".join(market_lines)

    text = (
        f"🏢 <b>РЫНОК БИЗНЕСОВ И ИМУЩЕСТВА</b> 📈\n\n"
        f"🎮 <b>Ваш игровой уровень:</b> <b>{lvl} LVL</b> ({prof['xp']}/{prof['next_xp']} XP)\n"
        f"💵 <b>Суммарный доход:</b> <b>+{total_income_min:,} 🌑/мин</b>\n"
        f"💰 <b>Накоплено к сбору:</b> <b>+{accumulated_profit:,} 🌑</b>\n\n"
        f"📦 <b>Ваше имущество:</b>\n{owned_txt}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Каталог рынка (цены обновляются каждый час):</b>\n\n"
        f"{market_txt}\n\n"
        f"💡 <i>Команды:</i> <code>купить [название] [кол-во]</code> · <code>продать [название] [кол-во]</code> · <code>собрать</code>"
    )

    rows = [
        [InlineKeyboardButton(text=f"💰 Собрать прибыль (+{accumulated_profit:,} 🌑)", callback_data="biz:collect")],
        [InlineKeyboardButton(text="🌾 Купить Ферму", callback_data="biz:buy:farm"),
         InlineKeyboardButton(text="🏠 Купить Дом", callback_data="biz:buy:house")],
        [InlineKeyboardButton(text="🏭 Купить Завод", callback_data="biz:buy:factory"),
         InlineKeyboardButton(text="🏢 Купить ТЦ", callback_data="biz:buy:mall")],
        [InlineKeyboardButton(text="⛏ Купить Шахту", callback_data="biz:buy:mine"),
         InlineKeyboardButton(text="⚡ Электростанция", callback_data="biz:buy:power")],
        [InlineKeyboardButton(text="🔄 Обновить рынок", callback_data="biz:refresh")]
    ]
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Cmd("бизнесы", "бизнес", "рынок", "предприятия", "имущество", "заводы", "фермы", "недвижимость", section=S,
                    usage="бизнесы", desc="Рынок предприятий, покупка и сбор прибыли"))
async def cmd_businesses(message: Message, **kw):
    if not await topic_ok(message):
        return
    uid = message.from_user.id
    await _ensure_start(uid)
    user_biz = await db.get_user_businesses(uid)
    prof = await db.get_game_profile(uid)
    text, kb = _render_biz_menu(uid, user_biz, prof)
    await message.reply(text, reply_markup=kb)


@router.message(Cmd("собрать", "прибыль", "собрать прибыль", "снять прибыль", section=S,
                    usage="собрать", desc="Собрать накопленную прибыль с предприятий"))
async def cmd_collect_profit(message: Message, **kw):
    if not await topic_ok(message):
        return
    uid = message.from_user.id
    await _ensure_start(uid)
    user_biz = await db.get_user_businesses(uid)
    if not user_biz:
        return await message.reply("У вас пока нет купленных предприятий. Купите что-нибудь в <code>бизнесы</code>!")

    now = int(time.time())
    total_collected = 0
    keys_to_update = []

    for k, data in user_biz.items():
        if k in BUSINESS_TYPES and data["count"] > 0:
            last_col = data.get("last_collect", now)
            mins = min(24 * 60, max(0, int((now - last_col) // 60)))
            if mins > 0:
                profit = mins * data["count"] * BUSINESS_TYPES[k]["income_per_min"]
                total_collected += profit
                keys_to_update.append(k)

    if total_collected <= 0:
        return await message.reply("⏳ Прибыль ещё не успела накопиться (начисление происходит каждую минуту).")

    await db.update_business_collect_time(uid, keys_to_update)
    new_bal = await db.add_coins(uid, total_collected, "biz_income")

    await message.reply(
        f"💰 <b>Прибыль успешно собрана!</b>\n\n"
        f"Начислено: <b>+{c(total_collected)}</b> 🎉\n"
        f"Ваш новый баланс: <b>{c(new_bal)}</b>"
    )


@router.message(Cmd("купить", "приобрести", "buy", section=S,
                    usage="купить {название} [кол-во]", desc="Купить предприятие на рынке"))
async def cmd_buy_business(message: Message, args: str = "", **kw):
    if not await topic_ok(message):
        return
    uid = message.from_user.id
    await _ensure_start(uid)

    parts = (args or "").strip().split()
    if not parts:
        return await message.reply(
            "🏢 <b>Покупка предприятий:</b>\n"
            "Формат: <code>купить [название] [кол-во]</code>\n"
            "Пример: <code>купить ферму 2</code> · <code>купить завод</code> · <code>купить дом</code>\n\n"
            "Весь каталог: <code>бизнесы</code>")

    # Распознавание названия и количества
    count = 1
    if parts[-1].isdigit():
        count = max(1, min(100, int(parts[-1])))
        name_q = " ".join(parts[:-1])
    else:
        name_q = " ".join(parts)

    biz_key, info = find_business_by_alias(name_q)
    if not biz_key:
        return await message.reply("❌ Предприятие не найдено. Напишите <code>бизнесы</code>, чтобы посмотреть каталог.")

    prof = await db.get_game_profile(uid)
    if prof["level"] < info["req_lvl"]:
        return await message.reply(
            f"🔒 <b>Недостаточный игровой уровень!</b>\n\n"
            f"Для покупки {info['emoji']} <b>{info['name']}</b> требуется <b>{info['req_lvl']} LVL</b>.\n"
            f"Ваш текущий уровень: <b>{prof['level']} LVL</b>.\n"
            f"💡 Играйте в казино/дартс/кубик, чтобы прокачать уровень!")

    buy_price_unit, _ = get_market_price(biz_key, is_sell=False)
    total_cost = buy_price_unit * count
    bal = await db.get_coins(uid)

    if bal < total_cost:
        return await message.reply(
            f"❌ Недостаточно монет.\n"
            f"Стоимость: <b>{c(total_cost)}</b> (за {count} шт.)\n"
            f"Ваш баланс: <b>{c(bal)}</b>")

    await db.add_coins(uid, -total_cost, "biz_buy", biz_key)
    new_count = await db.change_user_business(uid, biz_key, count)
    new_bal = await db.get_coins(uid)

    await message.reply(
        f"🎉 <b>Успешная покупка!</b>\n\n"
        f"Вы приобрели: {info['emoji']} <b>{info['name']}</b> × {count} шт.\n"
        f"Списано: <b>−{c(total_cost)}</b>\n"
        f"Всего у вас: <b>{new_count} шт.</b>\n"
        f"Доход: <b>+{new_count * info['income_per_min']:,} 🌑/мин</b>\n"
        f"Баланс: <b>{c(new_bal)}</b>"
    )


@router.message(Cmd("продать", "sell", section=S,
                    usage="продать {название} [кол-во]", desc="Продать предприятие на рынке"))
async def cmd_sell_business(message: Message, args: str = "", **kw):
    if not await topic_ok(message):
        return
    uid = message.from_user.id
    await _ensure_start(uid)

    parts = (args or "").strip().split()
    if not parts:
        return await message.reply("Формат: <code>продать [название] [кол-во]</code>\nПример: <code>продать завод 1</code>")

    count = 1
    if parts[-1].isdigit():
        count = max(1, int(parts[-1]))
        name_q = " ".join(parts[:-1])
    else:
        name_q = " ".join(parts)

    biz_key, info = find_business_by_alias(name_q)
    if not biz_key:
        return await message.reply("❌ Предприятие не найдено. Напишите <code>бизнесы</code>.")

    user_biz = await db.get_user_businesses(uid)
    have = user_biz.get(biz_key, {}).get("count", 0)
    if have < count:
        return await message.reply(f"У вас нет столько предприятий. В наличии: <b>{have} шт.</b>")

    sell_price_unit, _ = get_market_price(biz_key, is_sell=True)
    total_gain = sell_price_unit * count

    await db.change_user_business(uid, biz_key, -count)
    new_bal = await db.add_coins(uid, total_gain, "biz_sell", biz_key)

    await message.reply(
        f"🏷 <b>Предприятие продано!</b>\n\n"
        f"Вы продали: {info['emoji']} <b>{info['name']}</b> × {count} шт.\n"
        f"Выручка: <b>+{c(total_gain)}</b>\n"
        f"Ваш новый баланс: <b>{c(new_bal)}</b>"
    )


@router.callback_query(F.data.startswith("biz:"))
async def cb_businesses(call: CallbackQuery):
    uid = call.from_user.id
    action = call.data.split(":")[1]

    if action in ("menu", "refresh"):
        user_biz = await db.get_user_businesses(uid)
        prof = await db.get_game_profile(uid)
        text, kb = _render_biz_menu(uid, user_biz, prof)
        try:
            await call.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
        return await call.answer("Рынок обновлён")

    if action == "collect":
        user_biz = await db.get_user_businesses(uid)
        if not user_biz:
            return await call.answer("У вас нет предприятий!", show_alert=True)
        now = int(time.time())
        total = 0
        keys = []
        for k, data in user_biz.items():
            if k in BUSINESS_TYPES and data["count"] > 0:
                mins = min(24 * 60, max(0, int((now - data.get("last_collect", now)) // 60)))
                if mins > 0:
                    total += mins * data["count"] * BUSINESS_TYPES[k]["income_per_min"]
                    keys.append(k)
        if total <= 0:
            return await call.answer("⏳ Прибыль ещё не накопилась (начисляется каждую минуту).", show_alert=True)
        await db.update_business_collect_time(uid, keys)
        await db.add_coins(uid, total, "biz_income")
        await call.answer(f"💰 Собрано: +{total:,} 🌑!", show_alert=True)
        # Обновляем меню
        user_biz = await db.get_user_businesses(uid)
        prof = await db.get_game_profile(uid)
        text, kb = _render_biz_menu(uid, user_biz, prof)
        try:
            await call.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
        return

    if action == "buy":
        biz_key = call.data.split(":")[2]
        info = BUSINESS_TYPES.get(biz_key)
        if not info:
            return await call.answer("Ошибка")
        prof = await db.get_game_profile(uid)
        if prof["level"] < info["req_lvl"]:
            return await call.answer(f"🔒 Требуется {info['req_lvl']} LVL!", show_alert=True)
        buy_p, _ = get_market_price(biz_key, is_sell=False)
        bal = await db.get_coins(uid)
        if bal < buy_p:
            return await call.answer(f"Недостаточно монет! Нужно {buy_p:,} 🌑", show_alert=True)
        await db.add_coins(uid, -buy_p, "biz_buy", biz_key)
        await db.change_user_business(uid, biz_key, 1)
        await call.answer(f"🎉 Куплено: {info['name']}!", show_alert=True)
        user_biz = await db.get_user_businesses(uid)
        text, kb = _render_biz_menu(uid, user_biz, prof)
        try:
            await call.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
        return


# ═══════════════ СПИСОК ИГР ═══════════════
GAMES_TEXT = f"""🎮 <b>ДОСТУПНЫЕ ИГРЫ НА МОНЕТЫ 🌑</b>

🎰 <b>СЛОТЫ / КАЗИНО</b> — <code>казик 1000</code> / <code>слоты 1к</code>
   Крути барабан · до x10

🪙 <b>ОРЁЛ / РЕШКА</b> — <code>орёл 1000</code> / <code>решка 1к</code>
   Угадай сторону монеты · x2

💣 <b>МИНЫ</b> — <code>мины 1000</code>
   Открывай клетки, не наткнись на мину · до x24

🎯 <b>ДАРТС</b> — <code>дартс 1000</code>
   Бросок в мишень · до x3

💥 <b>КРАШ</b> — <code>краш 1000</code>
   Множитель растёт — успей забрать · до x50

🎡 <b>КОЛЕСО</b> — <code>колесо 1000</code>
   Барабан удачи · до x10

🎲 <b>КУБИК / КОСТИ</b> — <code>куб 1000</code>
   Бросок костей с ботом · x2

💣 <b>САПЁР</b> — <code>сапёр 1000</code>
   Дуэль на двоих (ответом на сообщение друга)

🎡 <b>РУЛЕТКА</b> — <code>рулетка красное 1000</code>
   Цвет x2 · число x14

🚀 <i>За каждую игру вы получаете опыт XP и повышаете уровень для покупки заводов и ферм!</i>"""


@router.message(Cmd("игры", "список игр", "games", section=S, usage="игры",
                    desc="Список всех игр на монеты"))
async def cmd_games(message: Message, **kw):
    if not await topic_ok(message):
        return
    await message.reply(GAMES_TEXT)
    if not await topic_ok(message):
        return
    await message.reply(GAMES_TEXT)


# ═══════════════ МИНИ-ИГРЫ НА КОМЕТЫ ═══════════════

# 1. Орёл и Решка
@router.message(Cmd("орёл", "орел", "решка", "монетка", section=S,
                    usage="орёл {ставка}", desc="Орёл или решка (x2)"))
async def cmd_coin(message: Message, args: str = "", **kw):
    bet = await take_bet(message, args)
    if bet is None:
        return
    uid = message.from_user.id
    side = "орёл" if "ор" in (message.text or "").lower() else "решка"
    await db.add_comets(uid, -bet, "gram_bet_coin")
    flip = random.choice(["орёл", "решка"])
    is_win = flip == side
    lvl, lvl_up = await db.add_game_xp(uid, 1, is_win=is_win)
    lvl_note = f"\n🚀 <i>Игровой уровень повышен до <b>{lvl} LVL</b>!</i>" if lvl_up else ""
    if is_win:
        win = bet * 2
        bal = await db.add_comets(uid, win, "gram_win_coin")
        await message.reply(
            f"🪙 Выпал <b>{flip}</b>!\n\n"
            f"🎉 <b>ПОБЕДА! +{c(bet)}</b>\n"
            f"Баланс: <b>{c(bal)}</b>{lvl_note}")
    else:
        bal = await db.get_comets(uid)
        await message.reply(
            f"🪙 Выпал <b>{flip}</b>\n\n"
            f"💔 Проигрыш −{c(bet)}\n"
            f"Баланс: <b>{c(bal)}</b>{lvl_note}")


# 2. Мины
_mines: dict[str, dict] = {}
MINE_MULT = [1.1, 1.25, 1.5, 1.9, 2.5, 3.4, 4.8, 7.0, 11.0, 18.0, 32.0, 65.0]


def _mines_kb(key: str, state: dict, over: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for r in range(4):
        row = []
        for col in range(4):
            idx = r * 4 + col
            if idx in state["opened"]:
                row.append(InlineKeyboardButton(text="💎", callback_data="h:noop"))
            elif over and idx in state["bombs"]:
                row.append(InlineKeyboardButton(text="💣", callback_data="h:noop"))
            elif over:
                row.append(InlineKeyboardButton(text="▫️", callback_data="h:noop"))
            else:
                row.append(InlineKeyboardButton(text="⬛", callback_data=f"mine:{key}:{idx}"))
        rows.append(row)
    if not over and state["opened"]:
        mult = MINE_MULT[min(len(state["opened"]) - 1, len(MINE_MULT) - 1)]
        cash = int(state["bet"] * mult)
        rows.append([InlineKeyboardButton(
            text=f"💰 Забрать {c(cash)} (x{mult})", callback_data=f"mine:{key}:cash")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Cmd("мины", "mines", section=S, usage="мины {ставка}",
                    desc="Поле 4x4, 3 мины · до x24"))
async def cmd_mines(message: Message, args: str = "", **kw):
    bet = await take_bet(message, args)
    if bet is None:
        return
    uid = message.from_user.id
    await db.add_comets(uid, -bet, "gram_bet_mines")
    bombs = set(random.sample(range(16), 3))
    key = f"{message.chat.id}:{uid}:{int(time.time()*1000)}"
    st = {"bet": bet, "uid": uid, "bombs": bombs, "opened": set()}
    _mines[key] = st
    await message.reply(
        f"💣 <b>МИНЫ (3 мины на поле)</b>\n"
        f"Ставка: <b>{c(bet)}</b>\n\n"
        f"Открывайте клетки! 💎 увеличивает множитель.",
        reply_markup=_mines_kb(key, st))


@router.callback_query(F.data.startswith("mine:"))
async def cb_mine(call: CallbackQuery):
    parts = call.data.split(":")
    key = f"{parts[1]}:{parts[2]}:{parts[3]}"
    st = _mines.get(key)
    if not st:
        return await call.answer("Игра устарела.")
    if call.from_user.id != st["uid"]:
        return await call.answer("Это не ваша игра!", show_alert=True)

    action = parts[4]
    if action == "cash":
        _mines.pop(key, None)
        mult = MINE_MULT[min(len(st["opened"]) - 1, len(MINE_MULT) - 1)]
        win = int(st["bet"] * mult)
        bal = await db.add_comets(st["uid"], win, "gram_win_mines")
        lvl, lvl_up = await db.add_game_xp(st["uid"], 1, is_win=True)
        lvl_note = f"\n🚀 <i>Игровой уровень: <b>{lvl} LVL</b>!</i>" if lvl_up else ""
        await call.message.edit_text(
            f"💰 <b>ВЫИГРЫШ ЗАБРАН!</b> x{mult}\n\n"
            f"Начислено: <b>+{c(win - st['bet'])}</b>\n"
            f"Баланс: <b>{c(bal)}</b>{lvl_note}",
            reply_markup=_mines_kb(key, st, over=True))
        return await call.answer("Победа!")

    idx = int(action)
    if idx in st["opened"]:
        return await call.answer()

    if idx in st["bombs"]:
        _mines.pop(key, None)
        bal = await db.get_comets(st["uid"])
        await db.add_game_xp(st["uid"], 1, is_win=False)
        await call.message.edit_text(
            f"💥 <b>БА-БАХ! Вы наступили на мину.</b>\n\n"
            f"Проигрыш: <b>−{c(st['bet'])}</b>\n"
            f"Баланс: <b>{c(bal)}</b>",
            reply_markup=_mines_kb(key, st, over=True))
        return await call.answer("Взрыв!", show_alert=True)

    st["opened"].add(idx)
    if len(st["opened"]) >= 13:
        _mines.pop(key, None)
        mult = MINE_MULT[-1]
        win = int(st["bet"] * mult)
        bal = await db.add_comets(st["uid"], win, "gram_win_mines")
        lvl, lvl_up = await db.add_game_xp(st["uid"], 2, is_win=True)
        lvl_note = f"\n🚀 <i>Игровой уровень: <b>{lvl} LVL</b>!</i>" if lvl_up else ""
        await call.message.edit_text(
            f"🏆 <b>ПОЛЕ ПОЛНОСТЬЮ ОЧИЩЕНО!</b> x{mult}\n\n"
            f"Выигрыш: <b>+{c(win - st['bet'])}</b>\nБаланс: <b>{c(bal)}</b>{lvl_note}",
            reply_markup=_mines_kb(key, st, over=True))
        return await call.answer("Идеально!")

    mult = MINE_MULT[min(len(st["opened"]) - 1, len(MINE_MULT) - 1)]
    await call.message.edit_text(
        f"💣 <b>МИНЫ</b>\nСтавка: <b>{c(st['bet'])}</b> · "
        f"Открыто: <b>{len(st['opened'])}</b> · Множитель: <b>x{mult}</b>",
        reply_markup=_mines_kb(key, st))
    await call.answer(f"💎 x{mult}")


# 3. Дартс на кометы
@router.message(Cmd("дартс кометы", "дартс", "darts", section=S, usage="дартс {ставка}",
                    desc="🎯 Бросок в мишень · до x3"))
async def cmd_darts(message: Message, args: str = "", **kw):
    bet = await take_bet(message, args)
    if bet is None:
        return
    uid = message.from_user.id
    await db.add_comets(uid, -bet, "gram_bet_darts")
    m = await message.answer_dice(emoji="🎯")
    await asyncio.sleep(3.5)
    v = m.dice.value
    mult = {6: 3.0, 5: 2.0, 4: 1.5, 3: 1.0}.get(v, 0)
    names = {6: "🎯 В яблочко!", 5: "Почти центр", 4: "Хорошо",
             3: "Задел мишень", 2: "Край", 1: "Мимо"}
    is_win = mult > 1.0
    lvl, lvl_up = await db.add_game_xp(uid, 1, is_win=is_win)
    lvl_note = f"\n🚀 <i>Игровой уровень: <b>{lvl} LVL</b>!</i>" if lvl_up else ""
    if mult:
        win = int(bet * mult)
        bal = await db.add_comets(uid, win, "gram_win_darts")
        diff = win - bet
        res = (f"🎉 <b>+{c(diff)}</b>" if diff > 0 else "🔸 Ставка возвращена")
        await message.reply(f"🎯 {names[v]} (x{mult})\n\n{res}\nБаланс: <b>{c(bal)}</b>{lvl_note}")
    else:
        bal = await db.get_comets(uid)
        await message.reply(f"🎯 {names.get(v, 'Мимо')}\n\n"
                            f"💔 Проигрыш −{c(bet)}\nБаланс: <b>{c(bal)}</b>{lvl_note}")


# 4. Краш
_crash: dict[str, dict] = {}


@router.message(Cmd("краш", "crash", section=S, usage="краш {ставка}",
                    desc="💥 Множитель растёт — успей забрать"))
async def cmd_crash(message: Message, args: str = "", **kw):
    bet = await take_bet(message, args)
    if bet is None:
        return
    uid = message.from_user.id
    await db.add_comets(uid, -bet, "gram_bet_crash")

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
                   "cashed": False, "over": False}

    msg = await message.reply(
        f"🚀 <b>КРАШ</b> · Ставка: <b>{c(bet)}</b>\n\n"
        f"Множитель: <b>x1.00</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"cr:{key}:cash")]]))

    mults = [1.1, 1.25, 1.5, 1.8, 2.2, 2.7, 3.5, 4.5, 6.0, 8.0, 12.0, 20.0, 35.0, 50.0]
    cur = 1.0
    for target in mults:
        await asyncio.sleep(1.2)
        st = _crash.get(key)
        if not st or st["cashed"]:
            return
        if target > crash_at:
            st["over"] = True
            _crash.pop(key, None)
            bal = await db.get_comets(uid)
            await db.add_game_xp(uid, 1, is_win=False)
            try:
                await msg.edit_text(
                    f"💥 <b>КРАШ НА x{crash_at:.2f}!</b>\n\n"
                    f"Вы не успели забрать.\n"
                    f"Проигрыш: <b>−{c(bet)}</b>\nБаланс: <b>{c(bal)}</b>")
            except Exception:
                pass
            return
        cur = target
        st["cur"] = cur
        try:
            await msg.edit_text(
                f"🚀 <b>КРАШ</b> · Ставка: <b>{c(bet)}</b>\n\n"
                f"Множитель: <b>x{cur:.2f}</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text=f"💰 ЗАБРАТЬ x{cur:.2f} (+{c(int(bet*cur)-bet)})",
                        callback_data=f"cr:{key}:cash")]]))
        except Exception:
            pass


@router.callback_query(F.data.startswith("cr:"))
async def cb_crash(call: CallbackQuery):
    parts = call.data.split(":")
    key = f"{parts[1]}:{parts[2]}:{parts[3]}"
    st = _crash.get(key)
    if not st or st["cashed"] or st["over"]:
        return await call.answer("Игра завершена.")
    if call.from_user.id != st["uid"]:
        return await call.answer("Это не ваша игра!", show_alert=True)
    st["cashed"] = True
    _crash.pop(key, None)
    cur = st.get("cur", 1.1)
    win = int(st["bet"] * cur)
    bal = await db.add_comets(st["uid"], win, "gram_win_crash")
    lvl, lvl_up = await db.add_game_xp(st["uid"], 1, is_win=True)
    lvl_note = f"\n🚀 <i>Игровой уровень: <b>{lvl} LVL</b>!</i>" if lvl_up else ""
    await call.message.edit_text(
        f"🎉 <b>УСПЕЛ ЗАБРАТЬ!</b>\n\n"
        f"Множитель: <b>x{cur:.2f}</b>\n"
        f"Выигрыш: <b>+{c(win - st['bet'])}</b>\n"
        f"Баланс: <b>{c(bal)}</b>{lvl_note}")
    await call.answer(f"Забрано x{cur:.2f}!")


# 5. Колесо фортуны
WHEEL_SECTORS = [
    (0, "0x · Пусто"),
    (0.5, "0.5x · Половина"),
    (1.0, "1x · Возврат"),
    (1.5, "1.5x"),
    (2.0, "2x"),
    (3.0, "3x"),
    (5.0, "5x"),
    (10.0, "🔥 10x ДЖЕКПОТ"),
]


@router.message(Cmd("колесо", "wheel", "фортуна", section=S,
                    usage="колесо {ставка}", desc="Колесо фортуны (до x10)"))
async def cmd_wheel(message: Message, args: str = "", **kw):
    bet = await take_bet(message, args)
    if bet is None:
        return
    uid = message.from_user.id
    await db.add_comets(uid, -bet, "gram_bet_wheel")
    msg = await message.reply("🎡 <i>Крутим барабан…</i>")
    await asyncio.sleep(2.5)

    weights = [30, 25, 20, 12, 7, 4, 1.5, 0.5]
    mult, label = random.choices(WHEEL_SECTORS, weights=weights, k=1)[0]
    is_win = mult > 1.0
    lvl, lvl_up = await db.add_game_xp(uid, 1, is_win=is_win)
    lvl_note = f"\n🚀 <i>Игровой уровень: <b>{lvl} LVL</b>!</i>" if lvl_up else ""
    if mult > 0:
        win = int(bet * mult)
        bal = await db.add_comets(uid, win, "gram_win_wheel")
        diff = win - bet
        res = (f"🎉 <b>+{c(diff)}</b>" if diff > 0 else (f"🔸 Возврат" if diff == 0 else f"💔 −{c(-diff)}"))
        await msg.edit_text(
            f"🎡 Сектор: <b>{label}</b>\n\n"
            f"{res}\nБаланс: <b>{c(bal)}</b>{lvl_note}")
    else:
        bal = await db.get_comets(uid)
        await msg.edit_text(
            f"🎡 Сектор: <b>{label}</b>\n\n"
            f"💔 Проигрыш −{c(bet)}\nБаланс: <b>{c(bal)}</b>{lvl_note}")


# 6. Сапёр (Дуэль на двоих)
_sapper_duels: dict[str, dict] = {}


@router.message(Cmd("сапёр", "сапер", "sapper", section=S,
                    usage="сапёр {ставка} (ответом на сообщение)",
                    desc="Дуэль в сапёра на двоих"))
async def cmd_sapper(message: Message, bot: Bot, args: str = "", **kw):
    if not await topic_ok(message):
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply("Ответьте командой на сообщение соперника!")
    target = message.reply_to_message.from_user
    if target.id == message.from_user.id or target.is_bot:
        return await message.reply("Нельзя вызвать себя или бота.")

    bet = await take_bet(message, args)
    if bet is None:
        return

    bal_t = await db.get_comets(target.id)
    if bal_t < bet:
        return await message.reply(f"У соперника недостаточно комет.")

    key = f"{message.chat.id}:{message.from_user.id}:{target.id}"
    _sapper_duels[key] = {
        "u1": message.from_user.id, "n1": message.from_user.first_name,
        "u2": target.id, "n2": target.first_name,
        "bet": bet, "bomb": random.randint(0, 8),
        "turn": message.from_user.id, "opened": set()
    }

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⚔️ ПРИНЯТЬ ДУЭЛЬ", callback_data=f"sap:{key}:accept"),
        InlineKeyboardButton(text="❌ ОТКАЗ", callback_data=f"sap:{key}:decline")]])

    await message.reply(
        f"💣 <b>ДУЭЛЬ В САПЁРА</b>\n\n"
        f"{mention(message.from_user)} вызывает {mention(target)}!\n"
        f"Ставка: <b>{c(bet)}</b> с каждого.\n\n"
        f"Поле 3x3 (9 клеток). На поле 1 мина. Кто наступит — проиграл!",
        reply_markup=kb)


@router.callback_query(F.data.startswith("sap:"))
async def cb_sapper(call: CallbackQuery):
    parts = call.data.split(":")
    key = f"{parts[1]}:{parts[2]}:{parts[3]}"
    st = _sapper_duels.get(key)
    if not st:
        return await call.answer("Дуэль устарела.")

    action = parts[4]
    if action == "decline":
        if call.from_user.id != st["u2"]:
            return await call.answer("Только соперник может отклонить.")
        _sapper_duels.pop(key, None)
        return await call.message.edit_text("❌ Дуэль отклонена соперником.")

    if action == "accept":
        if call.from_user.id != st["u2"]:
            return await call.answer("Только соперник может принять!")
        b1 = await db.get_comets(st["u1"])
        b2 = await db.get_comets(st["u2"])
        if b1 < st["bet"] or b2 < st["bet"]:
            _sapper_duels.pop(key, None)
            return await call.message.edit_text("У одного из участников не хватает комет.")

        await db.add_comets(st["u1"], -st["bet"], "sap_bet")
        await db.add_comets(st["u2"], -st["bet"], "sap_bet")

        rows = []
        for r in range(3):
            row = []
            for col in range(3):
                idx = r * 3 + col
                row.append(InlineKeyboardButton(text="⬛", callback_data=f"sap:{key}:step:{idx}"))
            rows.append(row)

        await call.message.edit_text(
            f"💣 <b>САПЁР</b> · Банк: <b>{c(st['bet']*2)}</b>\n\n"
            f"Ходит: <b>{st['n1']}</b>\n"
            f"Открывайте клетки по очереди!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        return

    if action == "step":
        idx = int(parts[5])
        if call.from_user.id != st["turn"]:
            return await call.answer("Сейчас не ваш ход!", show_alert=True)
        if idx in st["opened"]:
            return await call.answer()

        st["opened"].add(idx)

        if idx == st["bomb"]:
            _sapper_duels.pop(key, None)
            loser_id = call.from_user.id
            winner_id = st["u2"] if loser_id == st["u1"] else st["u1"]
            winner_name = st["n2"] if loser_id == st["u1"] else st["n1"]
            bank = int(st["bet"] * 2 * 0.95)
            await db.add_comets(winner_id, bank, "sap_win")
            await db.add_game_xp(winner_id, 2, is_win=True)
            await db.add_game_xp(loser_id, 1, is_win=False)

            return await call.message.edit_text(
                f"💥 <b>БА-БАХ! Клетка {idx+1} оказалась миной!</b>\n\n"
                f"🏆 Победитель: <b>{winner_name}</b> (+{c(bank - st['bet'])})\n"
                f"💀 {call.from_user.first_name} подорвался на мине!")

        # Передача хода
        st["turn"] = st["u2"] if st["turn"] == st["u1"] else st["u1"]
        next_name = st["n2"] if st["turn"] == st["u2"] else st["n1"]

        rows = []
        for r in range(3):
            row = []
            for col in range(3):
                i = r * 3 + col
                if i in st["opened"]:
                    row.append(InlineKeyboardButton(text="💎", callback_data="h:noop"))
                else:
                    row.append(InlineKeyboardButton(text="⬛", callback_data=f"sap:{key}:step:{i}"))
            rows.append(row)

        await call.message.edit_text(
            f"💣 <b>САПЁР</b> · Банк: <b>{c(st['bet']*2)}</b>\n\n"
            f"Ходит: <b>{next_name}</b>\n"
            f"Открыто клеток: {len(st['opened'])}/9",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        return


# 7. Рулетка на кометы
@router.message(Cmd("рулетка кометы", section=S,
                    usage="рулетка красное 1000", desc="Рулетка на кометы"))
async def cmd_comet_roulette(message: Message, args: str = "", **kw):
    p = (args or "").split()
    if len(p) < 2:
        return await message.reply("Формат: <code>рулетка красное 1000</code>")
    choice = p[0].lower()
    bet = await take_bet(message, p[1])
    if bet is None:
        return
    uid = message.from_user.id
    await db.add_comets(uid, -bet, "gram_bet_roulette")
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

    is_win = mult > 0
    lvl, lvl_up = await db.add_game_xp(uid, 1, is_win=is_win)
    lvl_note = f"\n🚀 <i>Игровой уровень: <b>{lvl} LVL</b>!</i>" if lvl_up else ""
    if mult:
        win = bet * mult
        bal = await db.add_comets(uid, win, "gram_win_roulette")
        await message.reply(f"🎡 Выпало <b>{num} {color}</b> — x{mult}: +{c(win - bet)}\nБаланс: <b>{c(bal)}</b>{lvl_note}")
    else:
        bal = await db.get_comets(uid)
        await message.reply(f"🎡 Выпало <b>{num} {color}</b> — проигрыш −{c(bet)}\nБаланс: <b>{c(bal)}</b>{lvl_note}")


# ═══════════════ АДМИНСКИЕ КОМАНДЫ ДЛЯ ВАЛЮТЫ ═══════════════
@router.message(Cmd("монеты выдать", "выдать монеты", "начислить монеты", "coin give", "coins give", "выдать коины", "выдать граммы", "выдать кометы", "дать монеты", "дать коины", "кометы выдать", "выдать", "начислить", "p give", section=S, rank=6,
                    usage="выдать {ссылка} {сумма}",
                    desc="Начислить валюту 🌑 (техадмин / 6+ ранг)"))
async def cmd_give_admin(message: Message, bot: Bot, args: str = "", **kw):
    from core_ranks import require
    if not await require(message, bot, 6):
        return
    uid, name, rest = await resolve_target(message, args, bot)
    if not uid:
        # Если цель не указана — действие к себе
        uid, name = message.from_user.id, message.from_user.first_name
        rest = args
    amount = parse_amount(rest, 10**14, 1)
    if not amount:
        return await message.reply("Укажите сумму: <code>выдать @user 50000</code>")
    bal = await db.add_balance(uid, amount, "admin_add", str(message.from_user.id))
    await message.reply(f"✅ {mention_id(uid, name)} получил <b>+{c(amount)}</b>\n"
                        f"Баланс: <b>{c(bal)}</b>")


@router.message(Cmd("монеты сет", "монеты set", "сет монет", "установить монеты", "coin set", "set coins", "кометы сет", "сет", "set", "установить", "p set", section=S, rank=6,
                    usage="сет {ссылка} {сумма}",
                    desc="Установить точный баланс (техадмин / 6+ ранг)"))
async def cmd_set_admin(message: Message, bot: Bot, args: str = "", **kw):
    from core_ranks import require
    if not await require(message, bot, 6):
        return
    uid, name, rest = await resolve_target(message, args, bot)
    if not uid:
        uid, name = message.from_user.id, message.from_user.first_name
        rest = args
    amount = parse_amount(rest, 10**14, 0)
    if amount is None or amount < 0:
        return await message.reply("Укажите сумму: <code>сет @user 100000</code>")
    bal = await db.set_balance(uid, amount)
    await message.reply(f"✅ Баланс {mention_id(uid, name)} установлен на <b>{c(bal)}</b>")


@router.message(Cmd("монеты снять", "снять монеты", "забрать монеты", "снять коины", "забрать коины", "кометы снять", "снять", "забрать", section=S, rank=6,
                    usage="снять {ссылка} {сумма}",
                    desc="Снять валюту 🌑 (техадмин / 6+ ранг)"))
async def cmd_take_admin(message: Message, bot: Bot, args: str = "", **kw):
    from core_ranks import require
    if not await require(message, bot, 6):
        return
    uid, name, rest = await resolve_target(message, args, bot)
    if not uid:
        uid, name = message.from_user.id, message.from_user.first_name
        rest = args
    amount = parse_amount(rest, 10**14, 1)
    if not amount:
        return await message.reply("Укажите сумму: <code>снять @user 50000</code>")
    bal = await db.add_balance(uid, -amount, "admin_take", str(message.from_user.id))
    await message.reply(f"✅ У {mention_id(uid, name)} списано <b>−{c(amount)}</b>\n"
                        f"Баланс: <b>{c(bal)}</b>")


# ═══════════════ ПРИВЯЗКА ТЕМЫ ДЛЯ ИГР ═══════════════
@router.message(Cmd("тема игр", "тема монет", "тема коинов", "тема казино", "тема граммов", "тема комет", section=S, rank=4,
                    usage="тема игр [ссылка]",
                    desc="Тема, где работают игры и валюта"))
async def cmd_gram_topic(message: Message, bot: Bot, args: str = "", **kw):
    from core_ranks import require
    if not await require(message, bot, 4):
        return
    a = (args or "").strip()

    if a.lower() in {"сброс", "убрать", "выкл", "off"}:
        await db.set_setting(message.chat.id, "gram_topic", "0")
        return await message.reply("✅ Привязка снята — игры работают везде.")

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
            f"🌑 <b>Тема для игр и валюты</b>\n\n{cur_txt}\n\n"
            f"Установить — напишите команду <b>в нужной теме</b>:\n"
            f"<code>тема игр</code>\n\n"
            f"Или ссылкой:\n<code>тема игр https://t.me/c/123456/789</code>\n\n"
            f"Снять: <code>тема игр сброс</code>",
            disable_web_page_preview=True)

    await db.set_setting(message.chat.id, "gram_topic", str(tid))
    await message.reply(
        f"✅ <b>Тема для игр и валюты установлена</b>\n\n🌑 {_tlink(message.chat.id, tid)}\n\n"
        f"Все игры и команды валюты теперь работают <b>только там</b>.",
        disable_web_page_preview=True)


# ═══════════════ ИНФОРМАЦИЯ О ЕДИНОЙ ВАЛЮТЕ ═══════════════
@router.message(Cmd("обмен", "обменять", "курс", "exchange", section=S,
                    usage="обмен",
                    desc="Информация о единой валюте бота"))
async def cmd_exchange(message: Message, **kw):
    if not await topic_ok(message):
        return
    uid = message.from_user.id
    await _ensure_start(uid)
    bal = await db.get_balance(uid)
    await message.reply(
        f"ℹ️ В боте действует <b>единая валюта {COIN}</b>!\n\n"
        f"💰 Ваш баланс: <b>{c(bal)}</b>\n\n"
        f"Обмен не требуется — все игры, предприятия, переводы и покупки работают напрямую с вашим единым балансом 🌑.\n\n"
        f"💡 <i>Открыть рынок: <code>бизнесы</code> · Игры: <code>игры</code> · Баланс: <code>б</code></i>")


# ═══════════════ ВЫПКА (VIP) ЗА ВАЛЮТУ ═══════════════
VIP_PRICE = 100_000
VIP_DAYS = 5


@router.message(Cmd("выпка", "купить выпку", "вypka", section=S,
                    usage="выпка",
                    desc=f"Купить выпку на {VIP_DAYS} дней за {c(VIP_PRICE)}"))
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
    bal = await db.get_balance(uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"👑 Купить за {c(VIP_PRICE)}",
                             callback_data="vipbuy")]])
    await message.reply(
        f"👑 <b>ВЫПКА</b> — {VIP_DAYS} дней за <b>{c(VIP_PRICE)}</b>\n\n"
        f"Что даёт:\n"
        f"• ×2 к ежедневным бонусам\n"
        f"• Бонусы к работе и защита от воров\n"
        f"• 👑 значок в профиле\n\n"
        f"Ваш баланс: <b>{c(bal)}</b>{left}",
        reply_markup=kb)


@router.callback_query(F.data == "vipbuy")
async def cb_vip(call: CallbackQuery):
    uid = call.from_user.id
    bal = await db.get_balance(uid)
    if bal < VIP_PRICE:
        return await call.answer(
            f"Недостаточно средств.\nНужно {c(VIP_PRICE)}, у вас {c(bal)}",
            show_alert=True)
    await db.add_balance(uid, -VIP_PRICE, "vip_buy")
    row = await db.fetchone("SELECT until FROM vip WHERE user_id=?", (uid,))
    base = max(int(time.time()), int(row["until"]) if row else 0)
    until = base + VIP_DAYS * 86400
    await db.execute(
        "INSERT INTO vip (user_id, until, level) VALUES (?,?,1) "
        "ON CONFLICT(user_id) DO UPDATE SET until=excluded.until", (uid, until))
    nu = await db.get_balance(uid)
    try:
        await call.message.edit_text(
            f"👑 <b>Выпка куплена!</b>\n\n"
            f"Срок: <b>{VIP_DAYS} дней</b>\n"
            f"Списано: <b>−{c(VIP_PRICE)}</b>\n"
            f"Баланс: <b>{c(nu)}</b>")
    except Exception:
        pass
    await call.answer("👑 Выпка активирована!")


# ═══════════════ ВЫДАЧА ВЫПКИ АДМИНОМ ═══════════════
@router.message(Cmd("выдать выпку", "дать выпку", "+выпка", "выпку",
                    "начислить выпку", section=S, rank=4,
                    usage="выдать выпку @ник 7 дней",
                    desc="Выдать участнику выпку бесплатно (ранг 4+)"))
async def cmd_vip_give(message: Message, bot: Bot, args: str = "", **kw):
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
        until = 4102444800
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
