"""Разделы 3,4,6,7,8,9,10,11,12,28,32: анкета, статистика, настройки чата,
триггеры, доступ команд, сетка, темы, голосования, антиспам, инлайн, интеграция."""
from __future__ import annotations

import html
import time

from aiogram import Bot, F, Router
from aiogram.types import (CallbackQuery, InlineQuery, InlineQueryResultArticle,
                           InputTextMessageContent, Message)

import db
from core_ranks import effective_rank, rank_label, rank_name, require
from core_registry import REGISTRY, Cmd, find_commands
from core_resolve import human_period, parse_period, resolve_target
from utils import level_of, mention, mention_id, money

router = Router(name="chatset")
(S_TRIG, S_ACCESS, S_CHAT, S_NET, S_FORM, S_STAT,
 S_TOPIC, S_VOTE, S_SPAM, S_INLINE, S_TG) = (3, 4, 6, 7, 8, 9, 10, 11, 12, 28, 32)


# ================= 8. АНКЕТА =================
FIELDS = {"о себе": "about", "город": "city", "возраст": "age",
          "др": "birthday", "днюха": "birthday", "хобби": "hobby", "контакт": "contact"}



@router.message(Cmd("установить", "заполнить", section=S_FORM,
                    usage="установить город Москва", desc="Заполнить поле анкеты"))
async def form_set(message: Message, args: str = "", **kw):
    a = (args or "").strip()
    for label in sorted(FIELDS, key=len, reverse=True):
        if a.lower().startswith(label):
            val = a[len(label):].strip()
            if not val:
                return await message.reply(f"Укажите значение: <code>установить {label} ...</code>")
            col = FIELDS[label]
            await db.execute("INSERT INTO profiles (user_id) VALUES (?) "
                             "ON CONFLICT(user_id) DO NOTHING", (message.from_user.id,))
            await db.execute(f"UPDATE profiles SET {col}=? WHERE user_id=?",
                             (val, message.from_user.id))
            return await message.reply(f"✅ {label.capitalize()}: <b>{html.escape(val)}</b>")
    await message.reply("Доступные поля: " + ", ".join(FIELDS) +
                        "\nПример: <code>установить город Москва</code>")


@router.message(Cmd("ник", "сменить ник", section=S_FORM, usage="ник {текст}",
                    desc="Установить ник"))
async def form_nick(message: Message, args: str = "", **kw):
    nick = (args or "").strip()
    if not nick:
        return await message.reply("Формат: <code>ник Босс</code>")
    if len(nick) > 32:
        return await message.reply("Максимум 32 символа.")
    await db.get_user(message.from_user.id)
    await db.execute("UPDATE users SET nick=? WHERE user_id=?", (nick, message.from_user.id))
    await message.reply(f"🏷 Ник установлен: <b>{html.escape(nick)}</b>")


@router.message(Cmd("ид", "id", "айди", section=S_FORM, usage="ид {ссылка}",
                    desc="Узнать ID пользователя и чата"))
async def form_id(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, _ = await resolve_target(message, args, bot)
    extra = f"\n👤 {html.escape(str(name))}: <code>{uid}</code>" if uid else ""
    await message.reply(f"🆔 Ваш ID: <code>{message.from_user.id}</code>\n"
                        f"💬 Чат: <code>{message.chat.id}</code>{extra}")


# ================= 9. СТАТИСТИКА =================
@router.message(Cmd("стата", "статистика", "моя стата", "stats", section=S_STAT, usage="стата",
                    desc="Статистика активности"))
async def stat_me(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        uid, name = message.from_user.id, message.from_user.first_name
    row = await db.fetchone("SELECT messages, xp, last_seen FROM chat_stats "
                            "WHERE chat_id=? AND user_id=?", (message.chat.id, uid))
    u = await db.get_user(uid)
    pos = await db.fetchone(
        "SELECT COUNT(*)+1 p FROM chat_stats WHERE chat_id=? AND messages > "
        "(SELECT COALESCE(messages,0) FROM chat_stats WHERE chat_id=? AND user_id=?)",
        (message.chat.id, message.chat.id, uid))
    lvl, title, *_ = level_of(u["xp"])
    seen = time.strftime("%d.%m %H:%M", time.localtime(row["last_seen"])) if row else "—"
    await message.reply(
        f"📊 <b>Статистика</b> {mention_id(uid, name)}\n"
        f"💬 Сообщений в чате: <b>{row['messages'] if row else 0}</b>\n"
        f"🏅 Место в чате: <b>{pos['p']}</b>\n"
        f"📈 Уровень: <b>{lvl}</b> ({title}), XP {u['xp']}\n"
        f"🕒 Последняя активность: {seen}")


@router.message(Cmd("топ чата", "топчата", "актив", "топ актив", section=S_STAT, group_only=True,
                    usage="топ чата", desc="Топ активных участников"))
async def stat_top(message: Message, **kw):
    rows = await db.fetchall(
        "SELECT s.user_id, s.messages, u.first_name FROM chat_stats s "
        "LEFT JOIN users u ON u.user_id=s.user_id WHERE s.chat_id=? "
        "ORDER BY s.messages DESC LIMIT 10", (message.chat.id,))
    if not rows:
        return await message.reply("Статистика пока пуста.")
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    lines = [f"{medals[i]} {mention_id(r['user_id'], r['first_name'])} — {r['messages']}"
             for i, r in enumerate(rows)]
    await message.reply("💬 <b>Топ активности чата</b>\n" + "\n".join(lines))


@router.message(Cmd("топ уровней", "топлвл", "топ лвл", section=S_STAT, usage="топ уровней",
                    desc="Топ по уровням"))
async def stat_top_lvl(message: Message, **kw):
    rows = await db.fetchall("SELECT user_id, first_name, xp FROM users ORDER BY xp DESC LIMIT 10")
    lines = []
    for i, r in enumerate(rows):
        lvl, title, *_ = level_of(r["xp"])
        lines.append(f"{i+1}. {mention_id(r['user_id'], r['first_name'])} — {lvl} ур. ({title})")
    await message.reply("📈 <b>Топ уровней</b>\n" + ("\n".join(lines) or "пусто"))


@router.message(Cmd("инфо чата", "чат", "информация", section=S_STAT, group_only=True, usage="инфо чата",
                    desc="Информация о чате"))
async def stat_chat(message: Message, bot: Bot, **kw):
    try:
        cnt = await bot.get_chat_member_count(message.chat.id)
    except Exception:
        cnt = "?"
    row = await db.fetchone("SELECT COUNT(*) c, SUM(messages) m FROM chat_stats WHERE chat_id=?",
                            (message.chat.id,))
    mods = await db.fetchone("SELECT COUNT(*) c FROM ranks WHERE chat_id=? AND rank>0",
                             (message.chat.id,))
    await message.reply(
        f"💬 <b>{html.escape(message.chat.title or 'Чат')}</b>\n"
        f"🆔 <code>{message.chat.id}</code>\n"
        f"👥 Участников: <b>{cnt}</b>\n"
        f"👮 Модераторов: <b>{mods['c']}</b>\n"
        f"📊 В базе: <b>{row['c'] or 0}</b> чел., <b>{row['m'] or 0}</b> сообщений")


# ================= 6. НАСТРОЙКА ЧАТА =================
@router.message(Cmd("правила", "rules", section=S_CHAT, group_only=True, usage="правила", desc="Правила чата"))
async def rules_show(message: Message, **kw):
    txt = await db.get_setting(message.chat.id, "rules")
    if not txt:
        return await message.reply("Правила не установлены.\n"
                                   "Установить: <code>установить правила Текст</code>")
    await message.reply(f"📜 <b>Правила чата</b>\n\n{txt}")


@router.message(Cmd("установить правила", "изменить правила", section=S_CHAT, rank=3,
                    usage="установить правила {текст}", desc="Задать правила"))
async def rules_set(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 3):
        return
    txt = args or (message.reply_to_message.text if message.reply_to_message else "")
    if not txt:
        return await message.reply("Укажите текст правил.")
    await db.set_setting(message.chat.id, "rules", txt)
    await message.reply("✅ Правила обновлены.")


@router.message(Cmd("приветствие", "greeting", section=S_CHAT, usage="приветствие",
                    desc="Показать приветствие"))
async def greet_show(message: Message, **kw):
    txt = await db.get_setting(message.chat.id, "greeting")
    await message.reply(f"👋 <b>Приветствие</b>\n\n{txt}" if txt else
                        "Приветствие не установлено.\n"
                        "Установить: <code>установить приветствие Привет, %имя%!</code>")


@router.message(Cmd("установить приветствие", section=S_CHAT, rank=3,
                    usage="установить приветствие {текст}", desc="Задать приветствие"))
async def greet_set(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 3):
        return
    if not args:
        return await message.reply("Доступные переменные: %имя%, %чат%\n"
                                   "Пример: <code>установить приветствие Привет, %имя%!</code>")
    await db.set_setting(message.chat.id, "greeting", args)
    await message.reply("✅ Приветствие установлено.")


@router.message(Cmd("удалить приветствие", section=S_CHAT, rank=3,
                    usage="удалить приветствие", desc="Убрать приветствие"))
async def greet_del(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 3):
        return
    await db.set_setting(message.chat.id, "greeting", "")
    await message.reply("🗑 Приветствие удалено.")


@router.message(Cmd("закрепить", "пин", section=S_CHAT, rank=2, usage="закрепить (реплаем)",
                    desc="Закрепить сообщение"))
async def pin_msg(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 2):
        return
    if not message.reply_to_message:
        return await message.reply("Ответьте на сообщение, которое надо закрепить.")
    try:
        await bot.pin_chat_message(message.chat.id, message.reply_to_message.message_id)
        await message.reply("📌 Закреплено.")
    except Exception as e:
        await message.reply(f"⚠️ {html.escape(str(e))}")


@router.message(Cmd("открепить", "анпин", section=S_CHAT, rank=2, usage="открепить",
                    desc="Открепить сообщение"))
async def unpin_msg(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 2):
        return
    try:
        if message.reply_to_message:
            await bot.unpin_chat_message(message.chat.id, message.reply_to_message.message_id)
        else:
            await bot.unpin_all_chat_messages(message.chat.id)
        await message.reply("📌 Откреплено.")
    except Exception as e:
        await message.reply(f"⚠️ {html.escape(str(e))}")


@router.message(Cmd("выключить чат", "отключить чат", section=S_CHAT, rank=4,
                    usage="выключить чат", desc="Отключить бота в чате"))
async def chat_off(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 4):
        return
    await db.set_setting(message.chat.id, "silent", "1")
    await message.reply("🔕 Бот отключён в этом чате. Включить: <code>включить чат</code>")


@router.message(Cmd("включить чат", section=S_CHAT, rank=4, usage="включить чат",
                    desc="Включить бота в чате"))
async def chat_on(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 4):
        return
    await db.set_setting(message.chat.id, "silent", "0")
    await message.reply("🔔 Бот снова активен.")


@router.message(Cmd("автокик", section=S_CHAT, rank=4, usage="автокик {период}",
                    desc="Автокик неактивных"))
async def autokick(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 4):
        return
    secs, _ = parse_period(args or "")
    if not secs:
        cur = await db.get_setting(message.chat.id, "autokick", "0")
        return await message.reply(f"Автокик: <b>{human_period(int(cur))}</b>\n"
                                   f"Изменить: <code>автокик 30 дней</code>")
    await db.set_setting(message.chat.id, "autokick", str(secs))
    await message.reply(f"✅ Автокик неактивных: {human_period(secs)}")


@router.message(Cmd("теги", "тег всех", "всем", section=S_CHAT, rank=2, usage="теги {текст}",
                    desc="Тегнуть участников"))
async def tag_all(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 2):
        return
    rows = await db.fetchall("SELECT s.user_id, u.first_name FROM chat_stats s "
                             "LEFT JOIN users u ON u.user_id=s.user_id WHERE s.chat_id=? "
                             "ORDER BY s.last_seen DESC LIMIT 30", (message.chat.id,))
    if not rows:
        return await message.reply("Некого тегать.")
    tags = " ".join(mention_id(r["user_id"], r["first_name"]) for r in rows)
    await message.reply(f"📢 {html.escape(args or 'Внимание!')}\n\n{tags}")


# ================= 3. ТРИГГЕРЫ =================
@router.message(Cmd("добавить триггер", "новый триггер", section=S_TRIG, rank=2,
                    usage="добавить триггер {слово} = {ответ}", desc="Создать автоответ"))
async def trig_add(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 2):
        return
    if "=" not in (args or ""):
        return await message.reply("Формат: <code>добавить триггер привет = Привет!</code>")
    pat, ans = args.split("=", 1)
    await db.execute("INSERT INTO triggers (chat_id,pattern,answer,by_id,ts) VALUES (?,?,?,?,?)",
                     (message.chat.id, pat.strip().lower(), ans.strip(),
                      message.from_user.id, int(time.time())))
    await message.reply(f"⚡️ Триггер добавлен: <b>{html.escape(pat.strip())}</b>")


@router.message(Cmd("триггеры", "список триггеров", section=S_TRIG, usage="триггеры",
                    desc="Список триггеров"))
async def trig_list(message: Message, **kw):
    rows = await db.fetchall("SELECT id,pattern,answer FROM triggers WHERE chat_id=? LIMIT 30",
                             (message.chat.id,))
    if not rows:
        return await message.reply("Триггеров нет.")
    lines = [f"#{r['id']} <b>{html.escape(r['pattern'])}</b> → "
             f"{html.escape(r['answer'][:40])}" for r in rows]
    await message.reply("⚡️ <b>Триггеры чата</b>\n" + "\n".join(lines))


@router.message(Cmd("удалить триггер", section=S_TRIG, rank=2, usage="удалить триггер {id|слово}",
                    desc="Удалить триггер"))
async def trig_del(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 2):
        return
    a = (args or "").strip()
    if a.isdigit():
        await db.execute("DELETE FROM triggers WHERE id=? AND chat_id=?", (int(a), message.chat.id))
    else:
        await db.execute("DELETE FROM triggers WHERE lower(pattern)=lower(?) AND chat_id=?",
                         (a, message.chat.id))
    await message.reply("🗑 Триггер удалён.")


# ================= 4. ДОСТУП КОМАНД =================





# ================= 7. СЕТКА ЧАТОВ =================
@router.message(Cmd("сетка", "мои чаты", section=S_NET, rank=4, usage="сетка",
                    desc="Список чатов сетки"))
async def net_list(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 4):
        return
    rows = await db.fetchall("SELECT c.chat_id, ch.title, c.num FROM net_chats c "
                             "LEFT JOIN chats ch ON ch.chat_id=c.chat_id "
                             "WHERE c.net_id=? ORDER BY c.num", (message.from_user.id,))
    if not rows:
        return await message.reply("Сетка пуста.\nДобавить: <code>сетка добавить</code>")
    lines = [f"{r['num']}. {html.escape(r['title'] or str(r['chat_id']))}" for r in rows]
    await message.reply("🕸 <b>Ваша сетка чатов</b>\n" + "\n".join(lines))


@router.message(Cmd("сетка добавить", "добавить в сетку", section=S_NET, rank=5,
                    usage="сетка добавить", desc="Добавить чат в сетку"))
async def net_add(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 5):
        return
    row = await db.fetchone("SELECT COALESCE(MAX(num),0)+1 n FROM net_chats WHERE net_id=?",
                            (message.from_user.id,))
    await db.execute("INSERT OR IGNORE INTO net_chats (net_id,chat_id,num) VALUES (?,?,?)",
                     (message.from_user.id, message.chat.id, row["n"]))
    await message.reply(f"🕸 Чат добавлен в сетку под номером <b>{row['n']}</b>")


# ================= 10. ТЕМЫ МОДЕРАТОРОВ =================
@router.message(Cmd("тема", "темы", section=S_TOPIC, rank=1, usage="тема",
                    desc="Что настроено в этой теме"))
async def topic(message: Message, bot: Bot, args: str = "", **kw):
    """Показывает назначение ИМЕННО той темы, где написана команда.

    Раньше здесь была общая заметка на весь чат, из-за чего в теме
    описаний могло показываться «граммы». Теперь бот смотрит,
    что реально привязано к текущей теме.
    """
    if not await require(message, bot, 1):
        return

    here = int(getattr(message, "message_thread_id", None) or 0)

    from h_userinfo import get_form_topic, topic_link
    from h_grams import get_gram_topic
    form_t = await get_form_topic(message.chat.id)
    gram_t = await get_gram_topic(message.chat.id)

    if args:
        # старое поведение: подписать текущую тему вручную
        key = f"topic_note:{here}" if here else "topic"
        await db.set_setting(message.chat.id, key, args)
        return await message.reply(
            f"🧵 Подпись для этой темы: <b>{html.escape(args)}</b>")

    if here and here == form_t:
        return await message.reply(
            "📝 <b>Эта тема: описания</b>\n\n"
            "Здесь новички заполняют анкету.\n"
            "Всё, кроме анкет, удаляется.\n\n"
            "Заполнить: <code>+описание</code> или <code>шаблон</code>")

    if here and here == gram_t:
        return await message.reply(
            "💊 <b>Эта тема: граммы и игры</b>\n\n"
            "Здесь работают команды граммов.\n"
            "Баланс: <code>б</code> · Игры: <code>игры</code>\n"
            "Бонус: <code>бонус граммы</code>")

    # прочие темы — показываем подпись и общую карту настроек
    note = await db.get_setting(message.chat.id, f"topic_note:{here}", "")
    if not note and not here:
        note = await db.get_setting(message.chat.id, "topic", "")

    lines = ["🧵 <b>Эта тема: обычное общение</b>"]
    if note:
        lines.append(f"Подпись: <b>{html.escape(note)}</b>")
    lines.append("")
    lines.append("<b>Настроенные темы чата:</b>")
    lines.append(f"📝 Описания: "
                 + (topic_link(message.chat.id, form_t) if form_t else "не задана"))
    lines.append(f"💊 Граммы: "
                 + (topic_link(message.chat.id, gram_t) if gram_t else "не задана"))
    await message.reply("\n".join(lines), disable_web_page_preview=True)


# ================= 11. ГОЛОСОВАНИЯ =================
@router.message(Cmd("голосование", "голос", "опрос", section=S_VOTE,
                    usage="голосование {вопрос}", desc="Создать голосование"))
async def vote_create(message: Message, bot: Bot, args: str = "", **kw):
    if not args:
        return await message.reply("Формат: <code>голосование Забанить спамера?</code>")
    try:
        await bot.send_poll(message.chat.id, question=args[:255],
                            options=["👍 За", "👎 Против"], is_anonymous=False)
    except Exception as e:
        await message.reply(f"⚠️ {html.escape(str(e))}")


@router.message(Cmd("голосование за бан", "вотбан", section=S_VOTE, rank=1,
                    usage="вотбан {ссылка}", desc="Голосование за бан"))
async def vote_ban(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 1):
        return
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя.")
    try:
        await bot.send_poll(message.chat.id, question=f"Забанить {name}?",
                            options=["👍 Да", "👎 Нет"], is_anonymous=False)
    except Exception as e:
        await message.reply(f"⚠️ {html.escape(str(e))}")


# ================= 12. АНТИСПАМ =================
@router.message(Cmd("спам", "в спам", "антиспам", section=S_SPAM, rank=4,
                    usage="спам {ссылка} {причина}", desc="Добавить в базу спамеров"))
async def spam_add(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 4):
        return
    uid, name, rest = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя.")
    await db.execute("INSERT OR REPLACE INTO spam_base (user_id,reason,by_id,ts) VALUES (?,?,?,?)",
                     (uid, rest or "спам", message.from_user.id, int(time.time())))
    await message.reply(f"🛰 {mention_id(uid, name)} добавлен в базу спамеров.\n"
                        f"Причина: {html.escape(rest or 'спам')}")


@router.message(Cmd("проверить", "чек", "scam", section=S_SPAM, usage="проверить {ссылка}",
                    desc="Проверить по базе спамеров"))
async def spam_check(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя.")
    row = await db.fetchone("SELECT * FROM spam_base WHERE user_id=?", (uid,))
    if row:
        return await message.reply(f"⛔️ {mention_id(uid, name)} <b>в базе спамеров</b>\n"
                                   f"Причина: {html.escape(row['reason'] or '—')}")
    await message.reply(f"✅ {mention_id(uid, name)} не найден в базе спамеров.")


@router.message(Cmd("убрать из спама", section=S_SPAM, rank=4, usage="убрать из спама {ссылка}",
                    desc="Убрать из базы спамеров"))
async def spam_del(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 4):
        return
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя.")
    await db.execute("DELETE FROM spam_base WHERE user_id=?", (uid,))
    await message.reply(f"✅ {mention_id(uid, name)} убран из базы.")


# ================= 28. ИНЛАЙН =================
@router.inline_query()
async def inline_mode(q: InlineQuery):
    text = (q.query or "").strip()
    results = []
    found = find_commands(text) if text else REGISTRY[:20]
    for i, c in enumerate(found[:30]):
        results.append(InlineQueryResultArticle(
            id=str(i), title="/".join(c.names[:2]),
            description=c.desc or c.usage,
            input_message_content=InputTextMessageContent(
                message_text=f"<b>{html.escape(c.usage)}</b>\n{html.escape(c.desc)}",
                parse_mode="HTML")))
    if not results:
        results = [InlineQueryResultArticle(
            id="none", title="Ничего не найдено",
            input_message_content=InputTextMessageContent(message_text="Команда не найдена"))]
    await q.answer(results, cache_time=10, is_personal=True)


@router.callback_query(F.data == "chk:rights")
async def cb_check_rights(call: CallbackQuery, bot: Bot):
    """Кнопка «Проверить права» из приветствия."""
    me = await bot.me()
    try:
        m = await bot.get_chat_member(call.message.chat.id, me.id)
    except Exception as e:
        return await call.answer(str(e)[:180], show_alert=True)
    if m.status != "administrator":
        return await call.answer(
            "❌ Я ещё не администратор.\nВыдайте права кнопкой выше.", show_alert=True)
    need = {
        "🔧 Управление группой": getattr(m, "can_change_info", False),
        "🗑 Удаление сообщений": getattr(m, "can_delete_messages", False),
        "🚫 Блокировка": getattr(m, "can_restrict_members", False),
        "📌 Закрепление": getattr(m, "can_pin_messages", False),
        "🔗 Пригл. по ссылке": getattr(m, "can_invite_users", False),
    }
    missing = [k for k, v in need.items() if not v]
    if missing:
        return await call.answer("Не хватает:\n" + "\n".join(missing), show_alert=True)
    await call.answer("✅ Все права на месте — бот готов!", show_alert=True)


# ================= 32. ИНТЕГРАЦИЯ =================
@router.message(Cmd("проверка", "check", "права", section=S_TG, group_only=True, usage="проверка",
                    desc="Диагностика прав бота"))
async def tg_check(message: Message, bot: Bot, **kw):
    me = await bot.me()
    try:
        m = await bot.get_chat_member(message.chat.id, me.id)
    except Exception as e:
        return await message.reply(f"⚠️ {html.escape(str(e))}")
    adm = m.status == "administrator"
    restrict = bool(getattr(m, "can_restrict_members", False))
    delete = bool(getattr(m, "can_delete_messages", False))
    pin = bool(getattr(m, "can_pin_messages", False))
    invite = bool(getattr(m, "can_invite_users", False))
    manage = bool(getattr(m, "can_change_info", False))
    priv = me.can_read_all_group_messages
    mark = lambda b: "✅" if b else "❌"
    tips = []
    if not adm:
        tips.append("• Выдайте боту права администратора")
    else:
        if not restrict: tips.append("• Право «Блокировка пользователей» — для мутов и банов")
        if not delete: tips.append("• Право «Удаление сообщений» — для чистки")
        if not pin: tips.append("• Право «Закрепление сообщений» — для пина")
        if not invite: tips.append("• Право «Приглашение по ссылке»")
        if not manage: tips.append("• Право «Управление группой»")
    # про Privacy Mode не пишем: он уже настроен, подсказка только мешает
    r = await effective_rank(message, bot)
    await message.reply(
        f"🩺 <b>Диагностика</b>\n\n"
        f"{mark(adm)} Администратор чата\n"
        f"{mark(restrict)} Может банить и мутить\n"
        f"{mark(delete)} Может удалять сообщения\n"
        f"{mark(pin)} Может закреплять\n"
        f"{mark(invite)} Приглашение по ссылке\n"
        f"{mark(manage)} Управление группой\n\n"
        f"Ваш ранг: <b>{rank_label(r) if r else 'Участник'}</b>"
        + (("\n\n<b>Что исправить:</b>\n" + "\n".join(tips)) if tips else "\n\n🎉 Всё настроено!"))
