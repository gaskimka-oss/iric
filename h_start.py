"""Старт в личке: капча -> главное меню (беседы, топ дня, ириски, магазин)."""
from __future__ import annotations

import html
import random
import time

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, LabeledPrice, Message,
                           PreCheckoutQuery)

import db
from config import START_BALANCE
import core_keyboard as kb
from core_registry import Cmd
from utils import mention_id, money

router = Router(name="start")
router.message.filter(F.chat.type == "private")

# --- Капча ----------------------------------------------------------------
EMOJI = ["🍎", "🍌", "🍇", "🍓", "🍒", "🥝", "🍑", "🍍", "🥥", "🍋"]
_captcha: dict[int, dict] = {}


def _captcha_kb(right: str, options: list[str]) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text=o, callback_data=f"cap:{o}") for o in options]
    return InlineKeyboardMarkup(inline_keyboard=[row[:3], row[3:]])


async def send_captcha(message: Message) -> None:
    right = random.choice(EMOJI)
    others = random.sample([e for e in EMOJI if e != right], 5)
    options = others + [right]
    random.shuffle(options)
    _captcha[message.from_user.id] = {"right": right, "tries": 0, "ts": time.time()}
    # на время капчи нижнее меню убираем — откроется сразу после проверки
    await message.answer("🛡 Проверка, что вы человек…",
                         reply_markup=kb.hide())
    await message.answer(
        f"🛡 <b>Проверка, что вы человек</b>\n\n"
        f"Нажмите на этот символ: <b>{right}</b>\n\n"
        f"<i>Это займёт секунду и делается один раз.</i>",
        reply_markup=_captcha_kb(right, options))


@router.callback_query(F.data.startswith("cap:"))
async def cb_captcha(call: CallbackQuery):
    data = _captcha.get(call.from_user.id)
    if not data:
        await call.message.edit_text("Капча устарела. Отправьте /start ещё раз.")
        return await call.answer()
    choice = call.data.split(":", 1)[1]
    if choice != data["right"]:
        data["tries"] += 1
        if data["tries"] >= 3:
            _captcha.pop(call.from_user.id, None)
            await call.message.edit_text(
                "❌ Слишком много ошибок.\nОтправьте /start, чтобы попробовать снова.")
            return await call.answer("Не угадали", show_alert=True)
        return await call.answer(f"❌ Не то. Попыток осталось: {3 - data['tries']}",
                                 show_alert=True)
    _captcha.pop(call.from_user.id, None)
    await db.get_user(call.from_user.id)
    await db.execute("UPDATE users SET verified=1 WHERE user_id=?", (call.from_user.id,))
    u = await db.get_user(call.from_user.id)
    await call.message.edit_text(await main_text(call.from_user.first_name, u),
                                 reply_markup=await main_kb(call.from_user.id))
    # открываем постоянное меню внизу экрана — теперь оно всегда под рукой
    try:
        await call.message.answer(
            "⌨️ <b>Меню открыто</b>\n"
            "Кнопки внизу экрана — можно пользоваться без команд.",
            reply_markup=await kb.main_menu(call.from_user.id))
    except Exception:
        pass
    await call.answer("✅ Проверка пройдена!")


# --- Главное меню ---------------------------------------------------------
async def main_text(name: str | None, u) -> str:
    return (f"👋 Привет, {html.escape(name or 'друг')}!\n\n"
            f"<b>ZRGOblivion</b> — модерация, ранги, экономика и игры для вашей беседы.\n\n"
            f"🌑 Ваш баланс: <b>{money(u['balance'])}</b>\n\n"
            f"Выберите раздел ниже 👇")


async def main_kb(uid: int = 0) -> InlineKeyboardMarkup:
    """Главное меню. Кнопка админ-панели видна только администрации."""
    rows = [
        [InlineKeyboardButton(text="➕ Добавить в беседу", callback_data="mm:add"),
         InlineKeyboardButton(text="⚙️ Установка", callback_data="mm:setup")],
        [InlineKeyboardButton(text="🏢 Бизнесы и рынок", callback_data="mm:biz"),
         InlineKeyboardButton(text="🎮 Игры и казино", callback_data="mm:grams")],
        [InlineKeyboardButton(text="🏆 Топ дня", callback_data="mm:topday"),
         InlineKeyboardButton(text="💬 Супертоп бесед", callback_data="mm:topchats")],
        [InlineKeyboardButton(text="🎁 Бонусы", callback_data="mm:bonus"),
         InlineKeyboardButton(text="📖 Команды", callback_data="mm:cmds")],
    ]
    if uid:
        try:
            from h_adminpanel import is_staff
            if await is_staff(uid):
                rows.insert(0, [InlineKeyboardButton(
                    text="🛡 АДМИН-ПАНЕЛЬ", callback_data="ap:main")])
        except Exception:
            pass
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_kb(extra: list[list[InlineKeyboardButton]] | None = None) -> InlineKeyboardMarkup:
    rows = list(extra or [])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="mm:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(CommandStart())
async def cmd_start(message: Message):
    u = await db.get_user(message.from_user.id)
    if not u["verified"]:
        return await send_captcha(message)
    payload = (message.text or "").partition(" ")[2].strip()
    if payload == "bonus":
        return await message.answer(await grams_text(message.from_user.id),
                                    reply_markup=await grams_kb(message.from_user.id))
    await message.answer(await main_text(message.from_user.first_name, u),
                         reply_markup=await main_kb(message.from_user.id))


async def grams_text(uid: int) -> str:
    from h_grams import DAILY_CD, DAILY_COINS, COIN, c
    bal = await db.get_coins(uid)
    left = await db.cooldown_left(uid, "gram_daily", DAILY_CD)
    from utils import hms
    status = (f"⏳ Следующий бонус через <b>{hms(left)}</b>" if left
              else f"🎁 <b>Бонус готов!</b> Нажмите кнопку ниже")
    return (f"{COIN} <b>Монеты и игры</b>\n\n"
            f"💰 Ваш баланс: <b>{c(bal)}</b>\n\n"
            f"{status}\n\n"
            f"<b>Каждые 24 часа — {DAILY_COINS:,} 🌑</b>\n\n".replace(",", " ") +
            f"🎮 Игры: слоты, мины, дартс, краш, колесо, сапёр, рулетка, кубик\n"
            f"🏢 Бизнесы: фермы, заводы, шахты, аренда домов и др.\n"
            f"👑 Выпка на 5 дней — 100 000 🌑\n\n"
            f"<i>Играть можно в чате командой</i> <code>игры</code> или <code>бизнесы</code>")


async def grams_kb(uid: int) -> InlineKeyboardMarkup:
    from h_grams import DAILY_CD, DAILY_COINS, COIN
    left = await db.cooldown_left(uid, "gram_daily", DAILY_CD)
    rows = []
    if not left:
        rows.append([InlineKeyboardButton(
            text=f"🎁 Забрать {DAILY_COINS:,} {COIN}".replace(",", " "),
            callback_data="gbonus")])
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="mm:grams")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="mm:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "gbonus")
async def cb_gram_bonus(call: CallbackQuery):
    from h_grams import DAILY_CD, DAILY_COINS, c
    uid = call.from_user.id
    left = await db.cooldown_left(uid, "gram_daily", DAILY_CD)
    if left:
        from utils import hms
        return await call.answer(f"Бонус уже получен.\nЖдите {hms(left)}", show_alert=True)
    bal = await db.add_coins(uid, DAILY_COINS, "gram_daily")
    await db.set_cooldown(uid, "gram_daily")
    await call.message.edit_text(
        f"🎉 <b>Бонус получен!</b>\n\n"
        f"Начислено: <b>+{c(DAILY_COINS)}</b>\n"
        f"Баланс: <b>{c(bal)}</b>\n\n"
        f"<i>Следующий через 24 часа.</i>",
        reply_markup=await grams_kb(uid))
    await call.answer(f"🎁 +{DAILY_COINS:,} 🌑!".replace(",", " "))


@router.message(Cmd("меню", "menu", section=32, usage="меню", desc="Главное меню бота"))
async def cmd_menu(message: Message, **kw):
    u = await db.get_user(message.from_user.id)
    if not u["verified"]:
        return await send_captcha(message)
    await message.answer(await main_text(message.from_user.first_name, u),
                         reply_markup=await main_kb(message.from_user.id))
    await _ensure_keyboard(message)


async def _ensure_keyboard(message: Message) -> None:
    """Держим нижнее меню открытым."""
    try:
        await message.answer("⌨️ Меню доступно в кнопках ниже",
                             reply_markup=await kb.main_menu(message.from_user.id))
    except Exception:
        pass


ADD_TEXT = """➕ <b>Как добавить бота в беседу</b>

<b>Шаг 1.</b> Нажмите кнопку ниже — откроется список ваших чатов.
<b>Шаг 2.</b> Выберите беседу и подтвердите добавление.
<b>Шаг 3.</b> Telegram сразу предложит выдать права — оставьте все галочки:

🔧 Управление группой
🗑 Удаление сообщений
🚫 Блокировка пользователей
📌 Закрепление сообщений
🔗 Приглашение по ссылке

<b>Шаг 4.</b> В беседе напишите <code>проверка</code> — бот покажет,
всё ли настроено.

👑 Владелец беседы автоматически получает высший ранг."""

SETUP_TEXT = """⚙️ <b>Установка и настройка</b>

<b>1. Добавьте бота и выдайте права</b>
Кнопка «Добавить в беседу» сама предложит нужные галочки.
Проверить: напишите в беседе <code>проверка</code>

<b>2. Раздайте ранги</b>
<code>+модер 3 @user</code> — назначить админа
<code>кто админ</code> — посмотреть состав
<code>ранги</code> — все ранги и привилегии

<b>3. Настройте права команд</b>
<code>ДК</code> — какой ранг нужен для каждой команды
<code>+лдк @user мут</code> — выдать команду лично

<b>4. Анкеты участников</b>
<code>анкета обязательна вкл</code> — новичок обязан
заполнить описание, прежде чем писать в чат

<b>5. Полезное</b>
<code>-чат 23:00</code> — авто-закрытие беседы на ночь
<code>установить правила Текст</code> — правила чата"""

IRIS_TEXT = """🌑 <b>Экономика и имущество</b>

В боте действует единая валюта <b>🌑</b>. Зарабатывайте, покупайте бизнес и соревнуйтесь в играх!

<b>Как заработать:</b>
🎁 <code>бонус</code> — ежедневный бонус
🛠 <code>работа</code> — заработок каждый час
🕵️ <code>крайм</code> — рискованная вылазка
🏢 <code>бизнесы</code> — покупка заводов, ферм, шахт и пассивный доход
💰 <code>собрать</code> — сбор накопленной прибыли каждую минуту
🦹‍♂️ <code>украсть @юзер</code> — ограбление других игроков

<b>Защита средств:</b>
🛡 <code>скрыть мешок</code> — скрыть мешок от воров на 1–5 часов

<b>Куда потратить:</b>
🏢 Покупка и продажа предприятий на динамическом рынке
🎰 <code>казик 1к</code> · 🎯 <code>дартс</code> · 💣 <code>мины</code> · 💥 <code>краш</code>
🎲 <code>кубик</code> · 🎡 <code>рулетка</code> · ⚔️ <code>дуэль</code>
💝 <code>передать @user 500</code> — перевод валюты

Баланс: <code>б</code> или <code>баланс</code> · Топ: <code>топ</code>"""

BONUS_TEXT = """🎁 <b>Бонусы и заработок</b>

<b>Ежедневный бонус</b> — <code>бонус</code>
Раз в 24 часа. С VIP — в 2 раза чаще!

<b>Работа</b> — <code>работа</code>
Заработок раз в час без риска.

<b>Криминал</b> — <code>крайм</code>
55% успех. Провал: штраф.

<b>Бизнесы</b> — <code>бизнесы</code>
Покупка предприятий для пассивного дохода.

<b>Сбор прибыли</b> — <code>собрать</code>
Накопленный доход от ваших ферм и заводов.

<b>Репутация</b> — <code>реп</code> реплаем"""


@router.callback_query(F.data.startswith("mm:"))
async def cb_menu(call: CallbackQuery, bot: Bot):
    what = call.data.split(":", 1)[1]
    uid = call.from_user.id

    if what == "main":
        u = await db.get_user(uid)
        await call.message.edit_text(await main_text(call.from_user.first_name, u),
                                     reply_markup=await main_kb(uid))
        return await call.answer()

    if what == "add":
        me = await bot.me()
        rights = ("change_info+delete_messages+restrict_members+invite_users"
                  "+pin_messages+manage_chat")
        kb = back_kb([[InlineKeyboardButton(
            text="➕ Выбрать беседу",
            url=f"https://t.me/{me.username}?startgroup&admin={rights}")]])
        await call.message.edit_text(ADD_TEXT, reply_markup=kb)
        return await call.answer()

    if what == "setup":
        await call.message.edit_text(SETUP_TEXT, reply_markup=back_kb(),
                                     disable_web_page_preview=True)
        return await call.answer()

    if what == "iris":
        await call.message.edit_text(IRIS_TEXT, reply_markup=back_kb())
        return await call.answer()

    if what == "bonus":
        await call.message.edit_text(BONUS_TEXT, reply_markup=back_kb())
        return await call.answer()

    if what == "cmds":
        import core_docs as docs
        from h_helpmenu import _menu_kb, _menu_text
        url = docs.cached().get("url")
        kb = _menu_kb(0)
        rows = list(kb.inline_keyboard)
        rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="mm:main")])
        await call.message.edit_text(
            _menu_text(), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            disable_web_page_preview=True)
        return await call.answer()

    if what == "topday":
        day = time.strftime("%Y-%m-%d")
        rows = await db.fetchall(
            "SELECT d.user_id, SUM(d.messages) m, u.first_name FROM daily_stats d "
            "LEFT JOIN users u ON u.user_id=d.user_id WHERE d.day=? "
            "GROUP BY d.user_id ORDER BY m DESC LIMIT 10", (day,))
        if not rows:
            txt = "🏆 <b>Топ дня</b>\n\nСегодня ещё никто не активничал."
        else:
            medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
            txt = "🏆 <b>Топ дня по активности</b>\n\n" + "\n".join(
                f"{medals[i]} {mention_id(r['user_id'], r['first_name'])} — "
                f"{r['m']} сообщ." for i, r in enumerate(rows))
        await call.message.edit_text(txt, reply_markup=back_kb())
        return await call.answer()

    if what == "topchats":
        rows = await db.fetchall(
            "SELECT c.chat_id, c.title, COUNT(s.user_id) people, "
            "COALESCE(SUM(s.messages),0) msgs FROM chats c "
            "LEFT JOIN chat_stats s ON s.chat_id=c.chat_id "
            "GROUP BY c.chat_id ORDER BY msgs DESC LIMIT 10")
        if not rows:
            txt = "💬 <b>Супертоп бесед</b>\n\nПока пусто."
        else:
            medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
            txt = "💬 <b>Супертоп бесед</b>\n\n" + "\n".join(
                f"{medals[i]} <b>{html.escape(r['title'] or 'беседа')}</b>\n"
                f"   👥 {r['people']} чел · 💬 {r['msgs']} сообщ."
                for i, r in enumerate(rows))
        await call.message.edit_text(txt, reply_markup=back_kb())
        return await call.answer()

    if what == "grams":
        await call.message.edit_text(await grams_text(uid),
                                     reply_markup=await grams_kb(uid))
        return await call.answer()

    if what == "shop":
        await call.message.edit_text(SHOP_TEXT, reply_markup=shop_kb())
        return await call.answer()

    await call.answer()


# --- Магазин за Telegram Stars -------------------------------------------
PACKS = {
    "s": (1, 5_000, "🍬 Горсть ирисок"),
    "m": (5, 30_000, "🍭 Пакет ирисок"),
    "l": (15, 120_000, "🎁 Коробка ирисок"),
    "xl": (50, 500_000, "💎 Сундук ирисок"),
    "vip": (25, 0, "👑 VIP на 30 дней"),
}

SHOP_TEXT = """🛒 <b>Магазин</b>

Покупка за ⭐️ <b>Telegram Stars</b> — внутреннюю валюту Telegram.
Звёзды покупаются прямо в приложении.

🍬 Горсть — 1 ⭐️ → 5 000 ириск
🍭 Пакет — 5 ⭐️ → 30 000 ириск
🎁 Коробка — 15 ⭐️ → 120 000 ириск
💎 Сундук — 50 ⭐️ → 500 000 ириск

👑 <b>VIP на 30 дней</b> — 25 ⭐️
   Удвоенный ежедневный бонус и значок в профиле.

<i>Возврат звёзд возможен в течение 21 дня.</i>"""


def shop_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{t} — {p} ⭐️", callback_data=f"buy:{k}")]
            for k, (p, _, t) in PACKS.items()]
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="mm:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery, bot: Bot):
    key = call.data.split(":", 1)[1]
    pack = PACKS.get(key)
    if not pack:
        return await call.answer("Товар не найден", show_alert=True)
    price, amount, title = pack
    desc = (f"{amount:,} ириск на баланс".replace(",", " ") if amount
            else "VIP-статус на 30 дней: удвоенный бонус")
    try:
        await bot.send_invoice(
            chat_id=call.from_user.id, title=title, description=desc,
            payload=f"pack:{key}", currency="XTR",
            prices=[LabeledPrice(label=title, amount=price)])
        await call.answer()
    except Exception as e:
        await call.answer(f"Не удалось открыть оплату: {str(e)[:150]}", show_alert=True)


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(q.id, ok=True)


@router.message(F.successful_payment)
async def on_paid(message: Message):
    sp = message.successful_payment
    key = (sp.invoice_payload or "").split(":")[-1]
    pack = PACKS.get(key)
    uid = message.from_user.id
    if not pack:
        return await message.answer("Платёж получен, но товар не распознан. "
                                    "Напишите владельцу бота.")
    price, amount, title = pack
    await db.execute("INSERT INTO purchases (user_id,item,stars,amount,ts) VALUES (?,?,?,?,?)",
                     (uid, key, price, amount, int(time.time())))
    if amount:
        bal = await db.add_balance(uid, amount, "shop_buy", key)
        await message.answer(
            f"✅ <b>Оплачено!</b>\n\n{title}\n"
            f"Начислено: <b>{money(amount)}</b>\nБаланс: <b>{money(bal)}</b>\n\n"
            f"Спасибо за поддержку! ⭐️", reply_markup=await main_kb(uid))
    else:
        await db.execute(
            "INSERT INTO vip (user_id, until, level) VALUES (?,?,1) "
            "ON CONFLICT(user_id) DO UPDATE SET until=MAX(vip.until, ?) ",
            (uid, int(time.time()) + 30 * 86400, int(time.time()) + 30 * 86400))
        await message.answer(
            f"✅ <b>Оплачено!</b>\n\n👑 VIP активирован на 30 дней.\n"
            f"Ежедневный бонус теперь удвоенный!", reply_markup=await main_kb(uid))



