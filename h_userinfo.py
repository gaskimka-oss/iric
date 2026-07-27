"""Карточка пользователя «ирис инфа», описание и обязательная анкета."""
from __future__ import annotations

import html
import random
import re
import time

from aiogram import Bot, F, Router
from aiogram.types import ChatPermissions, Message

import db
from core_ranks import effective_rank, get_rank, rank_name
from core_registry import Cmd, stars
from core_resolve import real_reply, resolve_target
from utils import mention_id

router = Router(name="userinfo")
S = 8

# поля анкеты: ключ -> (подпись, колонка в БД)
FIELDS: list[tuple[str, str, str]] = [
    ("имя", "Имя", "real_name"),
    ("возраст", "Возраст", "age"),
    ("страна", "Страна", "country"),
    ("время по мск", "Время по МСК", "tz"),
    ("семейное положение", "Семейное положение", "family"),
    ("айди", "Айди", "nick2"),
    ("ник", "Ник", "hobby"),
]
FIELD_BY_KEY = {k: (label, col) for k, label, col in FIELDS}

# Синонимы для ввода
ALIASES = {
    "город": "страна", "страна/город": "страна", "гор": "страна",
    "возр": "возраст", "лет": "возраст",
    "мск": "время по мск", "время": "время по мск", "тз": "время по мск",
    "семья": "семейное положение", "сп": "семейное положение",
    "id": "айди", "ид": "айди",
    "nick": "ник", "никнейм": "ник",
}

TEMPLATE = """☆ Имя:
☆ Возраст:
☆ Страна:
☆ Время по мск:
☆ семейное положение:
☆ Айди:
☆ Ник:"""

LINE_RE = re.compile(r"^\s*[☆★*•▫️\-]*\s*([А-Яа-яЁёA-Za-z /]+?)\s*[:：]\s*(.*)$")

MUTE_OFF = ChatPermissions(can_send_messages=False, can_send_audios=False,
                           can_send_documents=False, can_send_photos=False,
                           can_send_videos=False, can_send_video_notes=False,
                           can_send_voice_notes=False, can_send_polls=False,
                           can_send_other_messages=False, can_add_web_page_previews=False)
MUTE_ON = ChatPermissions(can_send_messages=True, can_send_audios=True,
                          can_send_documents=True, can_send_photos=True,
                          can_send_videos=True, can_send_video_notes=True,
                          can_send_voice_notes=True, can_send_polls=True,
                          can_send_other_messages=True, can_add_web_page_previews=True)


# ---------------- helpers ----------------
async def _profile(uid: int):
    row = await db.fetchone("SELECT * FROM profiles WHERE user_id=?", (uid,))
    if not row:
        await db.execute("INSERT OR IGNORE INTO profiles (user_id) VALUES (?)", (uid,))
        row = await db.fetchone("SELECT * FROM profiles WHERE user_id=?", (uid,))
    return row


def _split_lines(text: str) -> list[str]:
    """Режем текст на строки. Если анкету прислали одной строкой
    («☆ Имя: Дима ☆ Возраст: 19»), разделяем по звёздочкам-маркерам."""
    text = text or ""
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) <= 1 and text.count(":") >= 2:
        parts = re.split(r"\s*[☆★•▫️]\s*", text)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) >= 2:
            return parts
    return lines


def parse_form(text: str) -> dict[str, str]:
    """Разбирает «☆ Имя: Мася» построчно -> {колонка: значение}."""
    out: dict[str, str] = {}
    for raw in _split_lines(text):
        m = LINE_RE.match(raw.strip())
        if not m:
            continue
        key = m.group(1).strip().lower().replace("ё", "е")
        val = m.group(2).strip()
        key = ALIASES.get(key, key)
        if key not in FIELD_BY_KEY:
            for k in FIELD_BY_KEY:
                if k.startswith(key) or key.startswith(k):
                    key = k
                    break
        if key in FIELD_BY_KEY and val:
            out[FIELD_BY_KEY[key][1]] = val[:64]
    return out


def human_since(ts: int) -> str:
    """'3 месяца 5 дн'."""
    if not ts:
        return "неизвестно"
    d = max(0, int(time.time()) - ts)
    days = d // 86400
    if days >= 365:
        y, rest = divmod(days, 365)
        mo = rest // 30
        return f"{y} г {mo} мес" if mo else f"{y} г"
    if days >= 30:
        mo, rest = divmod(days, 30)
        return f"{mo} мес {rest} дн" if rest else f"{mo} мес"
    if days:
        return f"{days} дн"
    h = d // 3600
    return f"{h} ч" if h else f"{d // 60} мин"


def human_ago(ts: int) -> str:
    if not ts:
        return "давно"
    d = max(0, int(time.time()) - ts)
    if d < 60:
        return "только что"
    if d < 3600:
        return f"{d // 60} минут"
    if d < 86400:
        return f"{d // 3600} часов"
    return f"{d // 86400} дней"


def short_num(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


async def activity_counts(chat_id: int, uid: int) -> tuple[int, int, int, int]:
    """Активность: день | неделя | месяц | всего."""
    today = time.strftime("%Y-%m-%d")
    week = [time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
            for i in range(7)]
    month = [time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
             for i in range(30)]

    async def total(days: list[str]) -> int:
        if not days:
            return 0
        q = ",".join("?" * len(days))
        r = await db.fetchone(
            f"SELECT COALESCE(SUM(messages),0) s FROM daily_stats "
            f"WHERE chat_id=? AND user_id=? AND day IN ({q})",
            (chat_id, uid, *days))
        return int(r["s"]) if r else 0

    d = await total([today])
    w = await total(week)
    m = await total(month)
    r = await db.fetchone(
        "SELECT COALESCE(messages,0) s FROM chat_stats WHERE chat_id=? AND user_id=?",
        (chat_id, uid))
    allt = int(r["s"]) if r else 0
    return d, w, m, allt


async def is_tg_admin(bot: Bot, chat_id: int, uid: int) -> str | None:
    try:
        m = await bot.get_chat_member(chat_id, uid)
    except Exception:
        return None
    if m.status == "creator":
        return "Создатель чата в Telegram"
    if m.status == "administrator":
        return "Телеграм-админ этого чата"
    return None


# ---------------- ИРИС ИНФА ----------------
async def render_card(message: Message, bot: Bot, uid: int, name: str | None) -> str:
    """Карточка участника в стиле Ириса."""
    u = await db.get_user(uid)
    p = await _profile(uid)
    rank = await get_rank(message.chat.id, uid)
    tg = await is_tg_admin(bot, message.chat.id, uid)

    # состоит ли в чате
    in_chat = None
    try:
        m = await bot.get_chat_member(message.chat.id, uid)
        in_chat = m.status not in {"left", "kicked"}
    except Exception:
        pass

    fs = await db.fetchone("SELECT ts FROM first_seen WHERE chat_id=? AND user_id=?",
                           (message.chat.id, uid))
    first_ts = fs["ts"] if fs else (u["created_at"] or 0)
    st = await db.fetchone("SELECT last_seen FROM chat_stats WHERE chat_id=? AND user_id=?",
                           (message.chat.id, uid))
    last_ts = st["last_seen"] if st else 0
    d, w, m_, allt = await activity_counts(message.chat.id, uid)

    disp = html.escape(p["real_name"] or u["nick"] or name or str(uid))
    uname = u["username"]
    link = (f'<a href="https://telegram.me/{uname}">{disp}</a>' if uname
            else mention_id(uid, disp))

    out = [f"👤 <b>Это пользователь {link}</b>"]
    if tg:
        out.append(f"👨🏻‍🔧 {tg}")
    if in_chat is True:
        out.append("💚 Состоит в чате")
    elif in_chat is False:
        out.append("💔 Не состоит в чате")
    out.append("")
    out.append(f"▫️ [{rank}] Ранг: {rank_name(rank) if rank else 'Простой участник'}")
    out.append(f"Репутация: ✨ {u['rep']} | ➕ {u['messages']}")
    out.append(f"Первое появление: "
               f"{time.strftime('%d.%m.%Y', time.localtime(first_ts)) if first_ts else '—'}"
               f" ({human_since(first_ts)})")
    out.append(f"Последний актив: {human_ago(last_ts)}")
    out.append(f"Актив (д|н|м|весь): {d} | {w} | {m_} | {short_num(allt)}")

    shown = [f"▫️ ☆ {lbl}: {html.escape(str(p[col]))}"
             for _, lbl, col in FIELDS if col in p.keys() and p[col]][:3]
    if shown:
        out.append("")
        out.append("▫️ О СЕБЕ:")
        out += shown
        out.append("▫️☆")
        out.append("")
        out.append('🗓 Чтобы прочитать полное описание, введите команду '
                   '"описание @юзер"')
    return "\n".join(out)


@router.message(Cmd("инфа", "ирис инфа", "инфо", "кто это", "профиль игрока",
                    section=S, group_only=True, usage="инфа {ссылка}",
                    desc="Карточка участника: ранг, актив, описание"))
async def cmd_info(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        rows = await db.fetchall(
            "SELECT s.user_id, u.first_name FROM chat_stats s "
            "LEFT JOIN users u ON u.user_id=s.user_id "
            "WHERE s.chat_id=? AND s.user_id<>? ORDER BY RANDOM() LIMIT 1",
            (message.chat.id, message.from_user.id))
        if rows:
            uid, name = rows[0]["user_id"], rows[0]["first_name"]
        else:
            uid, name = message.from_user.id, message.from_user.first_name
    await message.reply(await render_card(message, bot, uid, name),
                        disable_web_page_preview=True)


@router.message(Cmd("кто я", "я кто", "кто йа", section=S, group_only=True,
                    usage="кто я", desc="Карточка о себе"))
async def cmd_who_am_i(message: Message, bot: Bot, **kw):
    await message.reply(
        await render_card(message, bot, message.from_user.id,
                          message.from_user.first_name),
        disable_web_page_preview=True)


@router.message(Cmd("кто ты", "ты кто", section=S, group_only=True,
                    usage="кто ты", desc="Информация о боте"))
async def cmd_who_are_you(message: Message, bot: Bot, **kw):
    from h_botinfo import bot_status_text
    await message.reply(await bot_status_text(bot), disable_web_page_preview=True)


# ---------------- ОПИСАНИЕ ----------------
@router.message(Cmd("описание", "анкета", "мое описание", "моё описание",
                    section=S, usage="описание {ссылка}",
                    desc="Полное описание участника"))
async def cmd_description(message: Message, bot: Bot, args: str = "", **kw):
    a = (args or "").strip()

    # «описание» + текст анкеты -> сохраняем
    if a and ("☆" in a or ":" in a) and len(a.splitlines()) >= 1 and LINE_RE.match(
            a.splitlines()[0].strip() or "x"):
        return await _save_form(message, a)

    # «описание» без указания на кого — всегда СВОЁ описание.
    # Чужое показываем, только если явно указан @ник / ссылка / id
    # либо это настоящий ответ на чужое сообщение.
    from core_resolve import real_reply
    me = message.from_user.id
    if a or real_reply(message) is not None:
        uid, name, _ = await resolve_target(message, a, bot)
        if not uid:
            uid, name = me, message.from_user.first_name
    else:
        uid, name = me, message.from_user.first_name

    u = await db.get_user(uid)
    p = await _profile(uid)
    mine = (uid == me)

    head = f"📋 <b>Описание</b> {mention_id(uid, html.escape(name or str(uid)))}"

    # если админ вписал своё описание — показываем именно его
    custom = p["custom"] if "custom" in p.keys() else None
    if custom:
        return await message.reply(f"{head}\n\n{html.escape(custom)}",
                                   disable_web_page_preview=True)

    lines = [head, ""]
    empty = True
    for key, label, col in FIELDS:
        val = p[col] if col in p.keys() else None
        lines.append(f"☆ {label}: {html.escape(str(val)) if val else '—'}")
        if val:
            empty = False
    if p["about"]:
        lines += ["", f"📝 {html.escape(p['about'])}"]
    if empty:
        if mine:
            lines += ["", "<i>Ваше описание не заполнено.</i>",
                      "Заполнить: напишите <code>шаблон</code> — "
                      "пришлю форму для заполнения."]
        else:
            lines += ["", "<i>Этот участник ещё не заполнил описание.</i>"]
    await message.reply("\n".join(lines), disable_web_page_preview=True)


EXAMPLE = """☆ Имя: Дима
☆ Возраст: 19
☆ Страна: Беларусь
☆ Время по мск: +0
☆ семейное положение: свободен
☆ Айди: 51288077171
☆ Ник: ZRG Dima"""


@router.message(Cmd("изменить описание", "редактировать описание",
                    "поменять описание", "задать описание", "описание изменить",
                    "правка описания", "изм описание",
                    section=S, rank=4, usage="изменить описание @ник\n{текст}",
                    desc="Вписать участнику своё описание (ранг 4+)"))
async def cmd_edit_description(message: Message, bot: Bot, args: str = "", **kw):
    """Админ вписывает человеку ЛЮБОЙ текст описания.

    Формат:
        изменить описание @ник
        любой текст, сколько угодно строк

    Или реплаем на сообщение человека:
        изменить описание
        любой текст
    """
    from core_ranks import require
    if not await require(message, bot, 4):
        return

    raw = (args or "").strip()
    if not raw and not real_reply(message):
        return await message.reply(
            "✏️ <b>Изменить описание участнику</b>\n\n"
            "<b>Способ 1 — по нику:</b>\n"
            "<code>изменить описание @ник\n"
            "Тут любой текст, который увидят все.\n"
            "Можно несколько строк.</code>\n\n"
            "<b>Способ 2 — ответом на его сообщение:</b>\n"
            "<code>изменить описание\n"
            "Тут текст</code>\n\n"
            "<b>Полезное:</b>\n"
            "<code>изменить описание @ник сброс</code> — вернуть анкету\n"
            "<code>описание @ник</code> — посмотреть\n\n"
            "<i>Текст пишете вы, бот ничего не меняет.</i>",
            disable_web_page_preview=True)

    # первая строка — на кого, остальное — текст описания
    parts = raw.split("\n", 1)
    head = parts[0].strip()
    body = parts[1].strip() if len(parts) > 1 else ""

    uid, name, rest = await resolve_target(message, head, bot)
    if not uid:
        return await message.reply(
            "🤔 Не понял, кому менять описание.\n"
            "Укажите <code>@ник</code> или ответьте на сообщение человека.")

    # текст мог остаться в первой строке после ника
    text = (rest.strip() + ("\n" + body if body else "")).strip() or body

    if text.lower() in {"сброс", "убрать", "очистить", "удалить", "-"}:
        await _profile(uid)
        await db.execute(
            "UPDATE profiles SET custom=NULL, custom_by=NULL, custom_ts=NULL "
            "WHERE user_id=?", (uid,))
        return await message.reply(
            f"🧹 Своё описание убрано у {mention_id(uid, html.escape(name or str(uid)))}.\n"
            f"Снова показывается обычная анкета.")

    if not text:
        return await message.reply(
            "📝 А что вписать? Текст пишется со <b>второй строки</b>:\n\n"
            f"<code>изменить описание @{html.escape(name or 'ник')}\n"
            f"Тут любой текст</code>")

    text = text[:2000]
    await _profile(uid)
    await db.execute(
        "UPDATE profiles SET custom=?, custom_by=?, custom_ts=?, "
        "filled=1, filled_ts=COALESCE(filled_ts, ?) WHERE user_id=?",
        (text, message.from_user.id, int(time.time()), int(time.time()), uid))

    await message.reply(
        f"✅ <b>Описание изменено</b>\n"
        f"👤 {mention_id(uid, html.escape(name or str(uid)))}\n\n"
        f"{html.escape(text[:600])}\n\n"
        f"<i>Показывается вместо анкеты. Вернуть анкету:</i>\n"
        f"<code>изменить описание @ник сброс</code>",
        disable_web_page_preview=True)


@router.message(Cmd("+описание", "+ описание", "добавить описание",
                    "новое описание", "изменить описание", "заполнить анкету",
                    "+анкета", section=S, usage="+описание [текст анкеты]",
                    desc="Добавить или изменить своё описание"))
async def cmd_add_description(message: Message, bot: Bot, args: str = "", **kw):
    """«+описание» — добавить своё описание.

    Можно сразу с текстом: «+описание ☆ Имя: Дима …» — тогда сохраним.
    Без текста — покажем форму и объясним, что делать.
    """
    a = (args or "").strip()
    if a and parse_form(a):
        return await _save_form(message, a)
    return await cmd_template(message, bot, **kw)


@router.message(Cmd("шаблон", "шаблон описания", "заполнить описание",
                    "как заполнить описание", "анкета шаблон", section=S,
                    usage="шаблон", desc="Шаблон анкеты и как её заполнить"))
async def cmd_template(message: Message, bot: Bot, **kw):
    """Шаблон + короткая инструкция. Форма отдельным сообщением —
    так её удобно скопировать одним касанием."""
    where = ""
    if message.chat.type != "private":
        ft = await get_form_topic(message.chat.id)
        if ft and topic_id(message) != ft:
            where = ("\n\n📌 Заполнять нужно в теме описаний:\n"
                     + topic_link(message.chat.id, ft))

    await message.reply(
        "📝 <b>Как заполнить описание</b>\n\n"
        "<b>1.</b> Нажмите на форму ниже — она скопируется целиком.\n"
        "<b>2.</b> Вставьте её в поле ввода.\n"
        "<b>3.</b> Впишите свои данные после двоеточий.\n"
        "<b>4.</b> Отправьте — я сохраню автоматически.\n\n"
        "<b>Пример заполненной:</b>\n"
        f"<code>{EXAMPLE}</code>\n\n"
        "Достаточно заполнить хотя бы 2 строки. "
        "Заполняется <b>один раз</b> — потом пишите в любой теме.\n\n"
        "<i>Можно и одной командой:</i>\n"
        "<code>+описание ☆ Имя: Дима ☆ Возраст: 19</code>"
        + where,
        disable_web_page_preview=True)

    # сама форма — отдельным сообщением, чтобы копировалась без лишнего текста
    try:
        await message.answer(f"<code>{TEMPLATE}</code>")
    except Exception:
        pass


async def _save_form(message: Message, text: str) -> None:
    data = parse_form(text)
    if not data:
        return await message.reply(
            "Не удалось распознать анкету.\nШаблон: <code>шаблон</code>")
    uid = message.from_user.id
    await _profile(uid)
    sets = ", ".join(f"{c}=?" for c in data)
    await db.execute(f"UPDATE profiles SET {sets} WHERE user_id=?",
                     (*data.values(), uid))
    # описание готово, если заполнено хотя бы MIN_FIELDS полей
    p = await _profile(uid)
    filled = sum(1 for _, _, c in FIELDS if p[c])
    was_done = bool(p["filled"])
    if filled >= MIN_FIELDS and not was_done:
        # ставим метку один раз и навсегда: больше нигде не переспросим
        await db.execute("UPDATE profiles SET filled=1, filled_ts=? WHERE user_id=?",
                         (int(time.time()), uid))
    ok = ", ".join(lbl for _, lbl, c in FIELDS if c in data)
    tail = ""
    if filled >= MIN_FIELDS and not was_done:
        tail = ("\n\n✅ <b>Описание принято!</b>\n"
                "Теперь можете писать в любой теме и в любом чате — "
                "заполнять второй раз не нужно.")
    elif filled < MIN_FIELDS:
        need = MIN_FIELDS - filled
        tail = (f"\n\n⚠️ Заполните ещё {need} "
                f"{'поле' if need == 1 else 'поля'}, чтобы открыть чат.")
    await message.reply(f"💾 Сохранено: {html.escape(ok)}{tail}")


# ---------------- ОБЯЗАТЕЛЬНАЯ АНКЕТА ----------------
@router.message(Cmd("анкета обязательна", "требовать анкету", "обязательное описание",
                    section=S, rank=4, usage="анкета обязательна вкл|выкл",
                    desc="Новичок обязан заполнить описание"))
async def cmd_require_form(message: Message, bot: Bot, args: str = "", **kw):
    from core_ranks import require
    if not await require(message, bot, 4):
        return
    a = (args or "").strip().lower()
    if a in {"вкл", "on", "да"}:
        await db.set_setting(message.chat.id, "form_required", "1")
        return await message.reply(
            "✅ <b>Обязательная анкета включена</b>\n\n"
            "Новые участники не смогут писать в чат, пока не заполнят описание.\n"
            "Им будет доступна только команда <code>описание</code> и шаблон.")
    if a in {"выкл", "off", "нет"}:
        await db.set_setting(message.chat.id, "form_required", "0")
        return await message.reply("⚠️ Обязательная анкета выключена.")
    cur = await db.get_setting(message.chat.id, "form_required", "0")
    await message.reply(
        f"Сейчас: <b>{'включена' if cur == '1' else 'выключена'}</b>\n"
        f"Изменить: <code>анкета обязательна вкл</code>")


async def get_form_topic(chat_id: int) -> int:
    """ID темы, где новички заполняют описание. 0 — не задана."""
    v = await db.get_setting(chat_id, "form_topic", "0")
    try:
        return int(v)
    except ValueError:
        return 0


def topic_id(message: Message) -> int:
    """Номер темы сообщения (0 — General/обычный чат)."""
    return int(getattr(message, "message_thread_id", None) or 0)


def topic_link(chat_id: int, tid: int) -> str:
    cid = str(chat_id)
    short = cid[4:] if cid.startswith("-100") else cid.lstrip("-")
    return f"https://t.me/c/{short}/{tid}"


# Сколько полей достаточно, чтобы описание считалось заполненным.
MIN_FIELDS = 2


async def form_done(uid: int) -> bool:
    """Заполнено ли описание. Описание одно на человека — на все чаты и темы.

    Достаточно заполнить один раз в теме описаний: дальше человек свободно
    пишет в любой теме и в любом чате сетки, повторять не нужно.
    """
    p = await db.fetchone("SELECT * FROM profiles WHERE user_id=?", (uid,))
    if not p:
        return False
    # админ вписал описание вручную — считаем заполненным
    if "custom" in p.keys() and p["custom"]:
        return True
    if p["filled"]:
        return True
    return sum(1 for _, _, c in FIELDS if p[c]) >= MIN_FIELDS


async def needs_form(chat_id: int, uid: int) -> bool:
    """Требуется ли этому участнику заполнить анкету."""
    if await db.get_setting(chat_id, "form_required", "0") != "1":
        return False
    return not await form_done(uid)




@router.message(Cmd("тема описания", "тема описаний", "тема описание",
                    "тема анкет", "тема анкеты", "установить тему описания",
                    section=S, rank=4, group_only=True,
                    usage="тема описания [ссылка|номер]",
                    desc="Тема, где новички заполняют описание"))
async def cmd_form_topic(message: Message, bot: Bot, args: str = "", **kw):
    from core_ranks import require
    if not await require(message, bot, 4):
        return
    a = (args or "").strip()

    if a.lower() in {"сброс", "убрать", "выкл", "off"}:
        await db.set_setting(message.chat.id, "form_topic", "0")
        return await message.reply("✅ Привязка к теме снята.\n"
                                   "Новички смогут заполнять описание в любой теме.")

    tid = 0
    m = re.search(r"t\.me/c/\d+/(\d+)", a)
    if m:
        tid = int(m.group(1))
    elif a.isdigit():
        tid = int(a)
    elif not a:
        tid = topic_id(message)

    if not tid:
        cur = await get_form_topic(message.chat.id)
        cur_txt = (f"Сейчас: {topic_link(message.chat.id, cur)}" if cur
                   else "Сейчас: не задана")
        return await message.reply(
            f"📌 <b>Тема для описаний</b>\n\n{cur_txt}\n\n"
            f"Установить — напишите команду <b>в нужной теме</b>:\n"
            f"<code>тема описания</code>\n\n"
            f"Или укажите ссылку:\n"
            f"<code>тема описания https://t.me/c/123456/789</code>\n\n"
            f"Снять: <code>тема описания сброс</code>",
            disable_web_page_preview=True)

    await db.set_setting(message.chat.id, "form_topic", str(tid))
    await db.set_setting(message.chat.id, "form_required", "1")
    await message.reply(
        f"✅ <b>Тема для описаний установлена</b>\n\n"
        f"📌 {topic_link(message.chat.id, tid)}\n\n"
        f"Пока новичок не заполнит описание, он сможет писать "
        f"<b>только в этой теме</b>. В остальных его сообщения удаляются.",
        disable_web_page_preview=True)
