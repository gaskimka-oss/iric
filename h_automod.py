"""Автомодерация: мут за оскорбления. Словарь + ИИ."""
from __future__ import annotations

import html
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.types import ChatPermissions, Message

import db
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
    level, reason, source = await toxicity.check(text, use_ai=use_ai)
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

    icon = "🔇" if secs else "⚠️"
    action = f"мут на <b>{human_period(secs)}</b>" if secs else "<b>предупреждение</b>"
    try:
        await message.answer(
            f"🤖 <b>Автомодерация</b>\n\n"
            f"👤 {mention(message.from_user)}\n"
            f"📝 Причина: <b>{html.escape(reason)}</b>\n"
            f"{icon} Наказание: {action}\n"
            f"🔍 Обнаружено: {source}\n"
            f"<code>#{pid}</code>")
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
        ai = "включён" if toxicity.ai_available() else "не подключён"
        return await message.reply(
            f"🤖 <b>Автомодерация включена</b>\n\n"
            f"За оскорбления и мат — мут на <b>{human_period(t2)}</b>\n"
            f"Сообщение нарушителя удаляется\n"
            f"Модерация (ранг 1+) не проверяется\n\n"
            f"🧠 ИИ-анализ: <b>{ai}</b>\n\n"
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

    if a.startswith("удаление"):
        val = "0" if "выкл" in a else "1"
        await db.set_setting(cid, "automod_delete", val)
        return await message.reply(
            f"🗑 Удаление сообщений: <b>{'включено' if val == '1' else 'выключено'}</b>")

    if a.startswith("ии"):
        val = "0" if "выкл" in a else "1"
        await db.set_setting(cid, "automod_ai", val)
        state = "включён" if val == "1" else "выключен"
        extra = ("" if toxicity.ai_available() else
                 "\n\n⚠️ <i>Ключ ИИ не задан в .env — работает только словарь.</i>")
        return await message.reply(f"🧠 ИИ-анализ: <b>{state}</b>{extra}")

    on = await is_enabled(cid)
    t2 = await get_mute_time(cid, 2)
    dele = await _delete_flag(cid)
    ai_on = await db.get_setting(cid, "automod_ai", "1") == "1"
    await message.reply(
        f"🤖 <b>Автомодерация</b>\n\n"
        f"Состояние: <b>{'🟢 включена' if on else '🔴 выключена'}</b>\n"
        f"Срок мута: <b>{human_period(t2)}</b>\n"
        f"Удалять сообщение: <b>{'да' if dele else 'нет'}</b>\n"
        f"ИИ-анализ: <b>{'да' if ai_on else 'нет'}</b>"
        f"{'' if toxicity.ai_available() else ' <i>(ключ не задан)</i>'}\n\n"
        f"<code>автомут вкл</code> — включить\n"
        f"<code>автомут выкл</code> — выключить\n"
        f"<code>автомут время 2 часа</code> — срок мута\n"
        f"<code>автомут тест текст</code> — проверить фразу\n"
        f"<code>автомут удаление выкл</code> — не удалять\n"
        f"<code>автомут ии выкл</code> — только словарь")


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
