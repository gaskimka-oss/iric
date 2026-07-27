"""Автомодерация: мут за оскорбления и мат. Словарь + ИИ-надзор."""
from __future__ import annotations

import html
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.types import ChatPermissions, Message

import db
import core_modlog as modlog
import core_toxicity as toxicity
from core_punish import log_punish
from core_ranks import effective_rank, require
from core_registry import Cmd
from core_resolve import human_period, parse_period
from utils import mention, mention_id

router = Router(name="automod")
S = 3

MUTE_OFF = ChatPermissions(
    can_send_messages=False, can_send_audios=False, can_send_documents=False,
    can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
    can_send_voice_notes=False, can_send_polls=False,
    can_send_other_messages=False, can_add_web_page_previews=False)

# уровень -> (срок мута в секундах, подпись)
DEFAULT_ACTIONS = {
    1: (0, "предупреждение"),      # 0 = только варн, без мута
    2: (3600, "мут 1 час"),        # оскорбление
    3: (3600, "мут 1 час"),        # мат / угроза
}


async def is_enabled(chat_id: int) -> bool:
    return await db.get_setting(chat_id, "automod", "0") == "1"


async def get_mute_time(chat_id: int, level: int) -> int:
    v = await db.get_setting(chat_id, f"automod_time_{level}", "")
    if v.isdigit():
        return int(v)
    return DEFAULT_ACTIONS.get(level, (3600, ""))[0]


async def _delete_flag(chat_id: int) -> bool:
    return await db.get_setting(chat_id, "automod_delete", "1") == "1"


def uid_self(message: Message) -> int:
    return message.from_user.id if message.from_user else 0


async def handle(message: Message, bot: Bot) -> bool:
    """Проверяет сообщение. True — нарушение обработано."""
    if message.chat.type == "private":
        return False
    if not message.from_user or message.from_user.is_bot:
        return False
    if not await is_enabled(message.chat.id):
        return False

    text = (message.text or message.caption or "").strip()
    if len(text) < 2:
        return False

    # модерацию не трогаем
    min_rank = int(await db.get_setting(message.chat.id, "automod_skip_rank", "1"))
    if await effective_rank(message, bot) >= min_rank:
        return False

    use_ai = await db.get_setting(message.chat.id, "automod_ai", "1") == "1"
    strict = await db.get_setting(message.chat.id, "automod_strict", "0") == "1"
    addressed = bool(message.reply_to_message and message.reply_to_message.from_user
                     and message.reply_to_message.from_user.id != uid_self(message))
    ai_ctx = ""
    if use_ai:
        try:
            import core_ai as _ai
            if _ai.available():
                ai_ctx = await modlog.build_context(message.chat.id,
                                                    message.from_user.id, text)
        except Exception:
            pass
    level, reason, source = await toxicity.check(
        text, use_ai=use_ai, addressed=addressed, punish_soft_mat=strict,
        context=ai_ctx)
    if level < 2:
        return False

    uid = message.from_user.id
    secs = await get_mute_time(message.chat.id, level)

    if await _delete_flag(message.chat.id):
        try:
            await message.delete()
        except Exception:
            pass

    full_reason = f"автомодерация: {reason}"
    pid = await log_punish(message.chat.id, uid, "mute" if secs else "warn",
                           full_reason, secs, 0)

    if secs:
        until = datetime.now(timezone.utc) + timedelta(seconds=secs)
        try:
            await bot.restrict_chat_member(message.chat.id, uid, MUTE_OFF,
                                           until_date=until)
        except Exception as e:
            note = ("<i>(это админ Telegram — мут не применён)</i>"
                    if "administrator" in str(e).lower() else
                    "<i>(не хватило прав на мут)</i>")
            try:
                await message.answer(
                    f"🤖 <b>Автомодерация</b>\n"
                    f"👤 {mention(message.from_user)}\n"
                    f"📝 {html.escape(reason)}\n{note}")
            except Exception:
                pass
            return True
        await db.execute(
            "INSERT INTO mutes (chat_id,user_id,reason,by_id,until,ts) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET "
            "reason=excluded.reason, until=excluded.until",
            (message.chat.id, uid, full_reason, 0, int(time.time()) + secs,
             int(time.time())))
    else:
        await db.execute(
            "INSERT INTO warns (chat_id,user_id,admin_id,reason,ts) VALUES (?,?,?,?,?)",
            (message.chat.id, uid, 0, full_reason, int(time.time())))

    ctx = await modlog.build_context(message.chat.id, uid, text)
    await modlog.write(message.chat.id, pid, uid,
                       message.from_user.first_name or str(uid),
                       0, "автомодерация",
                       "mute" if secs else "warn", reason, secs,
                       "автомодерация", ctx, bot=bot)

    icon = "🔇" if secs else "⚠️"
    action = f"мут на <b>{human_period(secs)}</b>" if secs else "<b>предупреждение</b>"
    try:
        sent = await message.answer(
            f"🤖 <b>Автомодерация</b>\n\n"
            f"👤 {mention(message.from_user)}\n"
            f"📝 Причина: <b>{html.escape(reason)}</b>\n"
            f"{icon} Наказание: {action}\n"
            f"🔍 Обнаружено: {source}\n"
            f"<code>#{pid}</code>")
        modlog.schedule_autodelete(bot, sent)
    except Exception:
        pass
    return True


# ═══════════════ НАСТРОЙКА ═══════════════
@router.message(Cmd("автомут", "автомодерация", "антимат", section=S, rank=4,
                    usage="автомут вкл|выкл",
                    desc="🤖 Автомут за оскорбления и мат"))
async def cmd_automod(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 4):
        return
    a = (args or "").strip().lower()
    cid = message.chat.id

    if a in {"вкл", "on", "да", "включить"}:
        await db.set_setting(cid, "automod", "1")
        t2 = await get_mute_time(cid, 2)
        import core_ai as ai
        brain = (f"🧠 ИИ-надзор: <b>включён</b> ({ai.provider()})"
                 if ai.available() else
                 "🧠 ИИ-надзор: <b>выключен</b> — работает словарь\n"
                 "<i>Включить: добавьте AI_API_KEY на хостинге</i>")
        return await message.reply(
            f"🤖 <b>Автомодерация включена</b>\n\n"
            f"За оскорбления и мат — мут на <b>{human_period(t2)}</b>\n"
            f"Сообщение нарушителя удаляется\n"
            f"Модерация (ранг 1+) не проверяется\n\n"
            f"{brain}\n\n"
            f"<i>Настройки: </i><code>автомут время 2 часа</code> · "
            f"<code>автомут тест текст</code>")

    if a in {"выкл", "off", "нет", "выключить"}:
        await db.set_setting(cid, "automod", "0")
        return await message.reply("🤖 Автомодерация <b>выключена</b>.")

    # автомут время 2 часа
    if a.startswith("время"):
        secs, _ = parse_period(a[5:])
        if not secs:
            return await message.reply(
                "Формат: <code>автомут время 2 часа</code>\n"
                "Можно: 30 минут · 1 час · 1 день")
        await db.set_setting(cid, "automod_time_2", str(secs))
        await db.set_setting(cid, "automod_time_3", str(secs))
        return await message.reply(f"⏱ Срок автомута: <b>{human_period(secs)}</b>")

    # автомут тест <текст>
    if a.startswith("тест"):
        probe = (args or "")[4:].strip()
        if not probe:
            return await message.reply("Формат: <code>автомут тест ты дебил</code>")
        lvl, reason, src = await toxicity.check(probe)
        verdict = {0: "✅ чисто", 1: "🟡 грубость",
                   2: "🟠 оскорбление", 3: "🔴 мат/угроза"}[lvl]
        secs = await get_mute_time(cid, lvl) if lvl >= 2 else 0
        act = f"мут {human_period(secs)}" if secs else "без наказания"
        return await message.reply(
            f"🔍 <b>Проверка текста</b>\n\n"
            f"«{html.escape(probe[:120])}»\n\n"
            f"Вердикт: {verdict}\n"
            f"Причина: {html.escape(reason or '—')}\n"
            f"Источник: {src}\n"
            f"Действие: <b>{act}</b>")

    if a.startswith("ии"):
        import core_ai as ai
        val = "0" if "выкл" in a else "1"
        await db.set_setting(cid, "automod_ai", val)
        state = "включён" if val == "1" else "выключен"
        extra = ("" if ai.available() else
                 "\n\n⚠️ <i>Ключ ИИ не задан — пока работает только словарь. "
                 "Как включить: команда </i><code>ии</code>")
        return await message.reply(f"🧠 ИИ-надзор: <b>{state}</b>{extra}")

    if a.startswith("удаление"):
        val = "0" if "выкл" in a else "1"
        await db.set_setting(cid, "automod_delete", val)
        return await message.reply(
            f"🗑 Удаление сообщений: <b>{'включено' if val == '1' else 'выключено'}</b>")

    on = await is_enabled(cid)
    t2 = await get_mute_time(cid, 2)
    dele = await _delete_flag(cid)
    import core_ai as ai
    ai_on = await db.get_setting(cid, "automod_ai", "1") == "1"
    ai_txt = (f"🟢 {ai.provider()}" if ai.available() and ai_on
              else "🔴 выключен" if not ai_on
              else "⚪️ ключ не задан")
    await message.reply(
        f"🤖 <b>Автомодерация</b>\n\n"
        f"Состояние: <b>{'🟢 включена' if on else '🔴 выключена'}</b>\n"
        f"Срок мута: <b>{human_period(t2)}</b>\n"
        f"Удалять сообщение: <b>{'да' if dele else 'нет'}</b>\n"
        f"ИИ-надзор: <b>{ai_txt}</b>\n\n"
        f"<code>автомут вкл</code> — включить\n"
        f"<code>автомут выкл</code> — выключить\n"
        f"<code>автомут время 2 часа</code> — срок мута\n"
        f"<code>автомут тест текст</code> — проверить фразу\n"
        f"<code>автомут удаление выкл</code> — не удалять\n"
        f"<code>автомут ии выкл</code> — только словарь\n"
        f"<code>ии</code> — настройки ИИ-надзора")


@router.message(Cmd("нарушения", "лог автомута", section=S, rank=1,
                    usage="нарушения", desc="Последние срабатывания автомодерации"))
async def cmd_violations(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 1):
        return
    rows = await db.fetchall(
        "SELECT p.*, u.first_name FROM punishments p "
        "LEFT JOIN users u ON u.user_id=p.user_id "
        "WHERE p.chat_id=? AND p.by_id=0 AND p.reason LIKE 'автомодерация%' "
        "ORDER BY p.id DESC LIMIT 15", (message.chat.id,))
    if not rows:
        return await message.reply("🤖 Автомодерация ещё не срабатывала.")
    lines = ["🤖 <b>Срабатывания автомодерации</b>\n"]
    for r in rows:
        lines.append(
            f"• {mention_id(r['user_id'], r['first_name'])} — "
            f"{html.escape((r['reason'] or '').replace('автомодерация: ', ''))}\n"
            f"   {time.strftime('%d.%m %H:%M', time.localtime(r['ts']))} · "
            f"<code>#{r['id']}</code>")
    await message.reply("\n".join(lines)[:3800], disable_web_page_preview=True)


@router.message(Cmd("автомут строгий", "строгий мат", section=S, rank=4,
                    usage="автомут строгий вкл|выкл",
                    desc="Наказывать мат даже без адресата"))
async def cmd_strict(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 4):
        return
    a = (args or "").strip().lower()
    if a in {"вкл", "on", "да"}:
        await db.set_setting(message.chat.id, "automod_strict", "1")
        return await message.reply(
            "🔴 <b>Строгий режим включён</b>\n\n"
            "Теперь наказывается любой мат, даже «бля» без адресата.")
    if a in {"выкл", "off", "нет"}:
        await db.set_setting(message.chat.id, "automod_strict", "0")
        return await message.reply(
            "🟢 <b>Строгий режим выключен</b>\n\n"
            "Мат-междометия («бля», «пиздец», «заебался») не наказываются.\n"
            "Наказывается только мат в адрес человека.")
    cur = await db.get_setting(message.chat.id, "automod_strict", "0")
    await message.reply(
        f"Строгий режим: <b>{'включён' if cur == '1' else 'выключен'}</b>\n\n"
        f"<i>Выключен — «бля» и «пиздец» без адресата пропускаются.</i>\n"
        f"Изменить: <code>автомут строгий вкл</code>")


# ═══════════════ ИИ-НАДЗОР ═══════════════
@router.message(Cmd("ии", "ai", "нейросеть", "ии надзор", section=S, rank=6,
                    usage="ии", desc="🧠 ИИ-надзор: статус и настройка"))
async def cmd_ai(message: Message, bot: Bot, args: str = "", **kw):
    """Статус ИИ, включение оповещений, сводка по чату."""
    if not await require(message, bot, 6):
        return
    import core_ai as ai
    cid = message.chat.id
    a = (args or "").strip().lower()

    # ии оповещения вкл|выкл
    if a.startswith(("оповещ", "уведом", "алерт")):
        val = "0" if "выкл" in a else "1"
        await db.set_setting(cid, "ai_alerts", val)
        return await message.reply(
            f"🔔 Оповещения о спорных наказаниях: "
            f"<b>{'включены' if val == '1' else 'выключены'}</b>")

    # ии сводка — что происходит в чате
    if a.startswith(("сводка", "отчет", "отчёт", "анализ")):
        if not ai.available():
            return await message.reply("⚠️ Ключ ИИ не задан.")
        m = await message.reply("🧠 Читаю переписку…")
        ctx = await modlog.build_context(cid, 0)
        res = await ai.chat_summary(ctx)
        if not res:
            return await m.edit_text("😕 ИИ не ответил. Попробуйте позже.")
        mood = str(res.get("mood", "—"))
        out = [f"{ai.MOOD_ICON.get(mood, '💬')} <b>Обстановка: {mood}</b>\n",
               html.escape(str(res.get("summary", ""))[:600])]
        if res.get("problems"):
            out.append(f"\n⚠️ <b>Проблемы:</b>\n{html.escape(str(res['problems'])[:400])}")
        if res.get("advice"):
            out.append(f"\n💡 <b>Совет:</b>\n{html.escape(str(res['advice'])[:400])}")
        return await m.edit_text("\n".join(out))

    # ии проверь <текст> — разовая проверка
    if a.startswith(("проверь", "тест")):
        probe = (args or "")[len(a.split()[0]):].strip()
        if not probe:
            return await message.reply("Формат: <code>ии проверь ты дебил</code>")
        if not ai.available():
            return await message.reply("⚠️ Ключ ИИ не задан.")
        m = await message.reply("🧠 Думаю…")
        ctx = await modlog.build_context(cid, 0)
        res = await ai.watch_message(probe, ctx)
        if not res:
            return await m.edit_text("😕 ИИ не ответил.")
        names = {0: "✅ норма", 1: "🟡 грубость",
                 2: "🟠 оскорбление", 3: "🔴 мат/травля"}
        extra = (f"\n👤 Зачинщик: {html.escape(res['instigator'])}"
                 if res.get("instigator") else "")
        return await m.edit_text(
            f"🧠 <b>Оценка ИИ</b>\n\n«{html.escape(probe[:150])}»\n\n"
            f"Вердикт: <b>{names[res['level']]}</b>\n"
            f"💬 {html.escape(res['reason'])}{extra}")

    # статус
    alerts = await db.get_setting(cid, "ai_alerts", "1") == "1"
    watch = await db.get_setting(cid, "automod_ai", "1") == "1"
    stat = await db.fetchone(
        "SELECT COUNT(*) c FROM mod_log WHERE chat_id=? AND ai_verdict IS NOT NULL",
        (cid,))
    bad = await db.fetchone(
        "SELECT COUNT(*) c FROM mod_log WHERE chat_id=? AND ai_verdict "
        "IN ('harsh','wrong') AND ai_score>=6", (cid,))

    if not ai.available():
        return await message.reply(
            "🧠 <b>ИИ-надзор</b>\n\n"
            "Состояние: <b>🔴 ключ не задан</b>\n\n"
            "<b>Что даёт ИИ:</b>\n"
            "• проверяет каждое наказание — справедливо ли\n"
            "• пишет вам, если модератор перегнул\n"
            "• понимает контекст: отличает дружеский подкол\n"
            "  от настоящего оскорбления\n"
            "• делает сводку обстановки в чате\n\n"
            "<b>Как включить:</b>\n"
            "1. Возьмите ключ API (OpenAI, DeepSeek, OpenRouter)\n"
            "2. На хостинге добавьте переменную:\n"
            "   <code>AI_API_KEY</code> = ваш ключ\n"
            "3. Если сервис не OpenAI, добавьте ещё:\n"
            "   <code>AI_API_URL</code> и <code>AI_MODEL</code>\n"
            "4. Перезапустите бота\n\n"
            "<i>DeepSeek дешевле всего — около 1₽ за 1000 проверок.</i>")

    await message.reply(
        f"🧠 <b>ИИ-надзор</b>\n\n"
        f"Состояние: <b>🟢 работает</b>\n"
        f"Сервис: <b>{ai.provider()}</b>\n"
        f"Модель: <code>{html.escape(ai.MODEL)}</code>\n\n"
        f"👁 Следит за чатом: <b>{'да' if watch else 'нет'}</b>\n"
        f"🔔 Пишет о спорных наказаниях: <b>{'да' if alerts else 'нет'}</b>\n\n"
        f"📊 Проверено наказаний: <b>{stat['c']}</b>\n"
        f"⚠️ Спорных: <b>{bad['c']}</b>\n\n"
        f"<code>ии сводка</code> — что происходит в чате\n"
        f"<code>ии проверь текст</code> — оценить фразу\n"
        f"<code>ии оповещения выкл</code> — не писать в ЛС\n"
        f"<code>автомут ии выкл</code> — только словарь")
