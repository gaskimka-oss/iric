"""Админ-панель в личке бота: логи модерации, списки, разбор наказаний.

Видна только тем, у кого ранг >= MIN_RANK хотя бы в одном чате.
Из панели можно наказать модератора за неправильное наказание.
"""
from __future__ import annotations

import html
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.types import (CallbackQuery, ChatPermissions, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

import db
from core_punish import KIND_EMOJI, KIND_NAMES, log_punish
from core_ranks import rank_label
from core_registry import MAX_RANK, Cmd
from core_resolve import human_period
from utils import mention_id

router = Router(name="adminpanel")
router.message.filter(F.chat.type == "private")

S = 1
MIN_RANK = 4          # с какого ранга видна панель
PAGE = 5

MUTE_OFF = ChatPermissions(
    can_send_messages=False, can_send_audios=False, can_send_documents=False,
    can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
    can_send_voice_notes=False, can_send_polls=False,
    can_send_other_messages=False, can_add_web_page_previews=False)


async def top_rank(uid: int) -> int:
    """Максимальный ранг пользователя по всем чатам."""
    from config import ADMINS, OWNER_ID
    if uid == OWNER_ID or uid in ADMINS:
        return MAX_RANK
    best = 0
    for table in ("ranks", "staff"):
        row = await db.fetchone(
            f"SELECT MAX(rank) m FROM {table} WHERE user_id=?", (uid,))
        if row and row["m"]:
            best = max(best, int(row["m"]))
    return best


async def is_staff(uid: int) -> bool:
    return await top_rank(uid) >= MIN_RANK


# ═══════════════ ОПИСАНИЯ УЧАСТНИКОВ ═══════════════
_TEMPLATE = ("☆ Имя:\n☆ Возраст:\n☆ Страна:\n☆ Время по мск:\n"
             "☆ семейное положение:\n☆ Айди:\n☆ Ник:")


def _topic_link(chat_id: int, tid: int) -> str:
    cid = str(chat_id)
    short = cid[4:] if cid.startswith("-100") else cid.lstrip("-")
    return f"https://t.me/c/{short}/{tid}"


async def _form_chat_topic() -> tuple[int, int]:
    """Чат, где включена обязательная анкета, и номер темы."""
    row = await db.fetchone(
        "SELECT chat_id FROM settings WHERE key='form_required' AND value='1' LIMIT 1")
    if not row:
        row = await db.fetchone(
            "SELECT chat_id FROM settings WHERE key='form_topic' LIMIT 1")
    chat_id = int(row["chat_id"]) if row else 0
    t = await db.get_setting(chat_id, "form_topic", "0") if chat_id else "0"
    try:
        topic = int(t)
    except ValueError:
        topic = 0
    return chat_id, topic


def _filled_count(p) -> int:
    from h_userinfo import FIELDS
    return sum(1 for _, _, c in FIELDS if c in p.keys() and p[c])


async def _no_desc_users(chat_id: int) -> list:
    """Участники чата без описания."""
    rows = await db.fetchall(
        "SELECT s.user_id, u.first_name, u.username FROM chat_stats s "
        "LEFT JOIN users u ON u.user_id = s.user_id "
        "WHERE s.chat_id=? ORDER BY s.last_seen DESC", (chat_id,))
    out = []
    for r in rows:
        p = await db.fetchone("SELECT * FROM profiles WHERE user_id=?",
                              (r["user_id"],))
        if not p or (not p["filled"] and _filled_count(p) < 3):
            out.append(r)
    return out


async def desc_page(page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    chat_id, topic = await _form_chat_topic()
    if not chat_id:
        return ("📝 <b>Описания участников</b>\n\n"
                "Обязательные анкеты нигде не включены.\n"
                "В чате: <code>тема описания</code>",
                InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="⬅️ В панель",
                                         callback_data="ap:main"),
                    InlineKeyboardButton(text="🏠 В меню",
                                         callback_data="nav:home")]]))

    rows = await db.fetchall(
        "SELECT s.user_id, u.first_name, u.username FROM chat_stats s "
        "LEFT JOIN users u ON u.user_id = s.user_id "
        "WHERE s.chat_id=? ORDER BY s.last_seen DESC", (chat_id,))

    done, missing = [], []
    for r in rows:
        p = await db.fetchone("SELECT * FROM profiles WHERE user_id=?",
                              (r["user_id"],))
        cnt = _filled_count(p) if p else 0
        if p and (p["filled"] or cnt >= 3):
            done.append((r, cnt))
        else:
            missing.append((r, cnt))

    chat = await db.fetchone("SELECT title FROM chats WHERE chat_id=?", (chat_id,))
    head = (f"📝 <b>Описания участников</b>\n"
            f"💬 {html.escape((chat['title'] if chat else '') or str(chat_id))}\n\n"
            f"✅ Заполнили: <b>{len(done)}</b>\n"
            f"❌ Без описания: <b>{len(missing)}</b>\n")

    per = 12
    total = len(done) + len(missing)
    combined = [("❌", r, c) for r, c in missing] + [("✅", r, c) for r, c in done]
    chunk = combined[page * per:(page + 1) * per]

    lines = [head]
    for mark, r, cnt in chunk:
        name = html.escape((r["first_name"] or str(r["user_id"]))[:22])
        uname = f" @{r['username']}" if r["username"] else ""
        extra = f" <i>({cnt}/7 полей)</i>" if mark == "❌" and cnt else ""
        lines.append(f"{mark} {mention_id(r['user_id'], name)}{uname}{extra}")

    if topic:
        lines.append(f"\n📌 Тема анкет: {_topic_link(chat_id, topic)}")

    kb_rows = []
    if missing:
        kb_rows.append([InlineKeyboardButton(
            text=f"✉️ Написать в ЛС всем без описания ({len(missing)})",
            callback_data="ap:remind")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️",
                                        callback_data=f"ap:desc:{page-1}"))
    nav.append(InlineKeyboardButton(
        text=f"{page+1}/{max(1, (total + per - 1) // per)}",
        callback_data="ap:noop"))
    if (page + 1) * per < total:
        nav.append(InlineKeyboardButton(text="▶️",
                                        callback_data=f"ap:desc:{page+1}"))
    kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton(text="🔄 Обновить",
                                         callback_data=f"ap:desc:{page}")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ В панель",
                                         callback_data="ap:main"),
                    InlineKeyboardButton(text="🏠 В меню",
                                         callback_data="nav:home")])
    return "\n".join(lines)[:3800], InlineKeyboardMarkup(inline_keyboard=kb_rows)


# ═══════════════ ГЛАВНОЕ МЕНЮ ═══════════════
def panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Логи модерации", callback_data="ap:log:0")],
        [InlineKeyboardButton(text="🔇 Мут-лист", callback_data="ap:list:mute:0"),
         InlineKeyboardButton(text="🔨 Бан-лист", callback_data="ap:list:ban:0")],
        [InlineKeyboardButton(text="⚠️ Варн-лист", callback_data="ap:list:warn:0")],
        [InlineKeyboardButton(text="🤖 Автомодерация", callback_data="ap:auto:0")],
        [InlineKeyboardButton(text="📝 Описания участников", callback_data="ap:desc:0")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="ap:stat")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="ap:main"),
         InlineKeyboardButton(text="🏠 В меню", callback_data="nav:home")],
    ])


async def panel_text(uid: int) -> str:
    r = await top_rank(uid)
    total = await db.fetchone("SELECT COUNT(*) c FROM mod_log")
    today = await db.fetchone(
        "SELECT COUNT(*) c FROM mod_log WHERE ts > ?", (int(time.time()) - 86400,))
    auto = await db.fetchone(
        "SELECT COUNT(*) c FROM mod_log WHERE source='автомодерация'")
    return (f"🛡 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
            f"Ваш ранг: <b>{rank_label(r)}</b>\n\n"
            f"📋 Всего наказаний: <b>{total['c']}</b>\n"
            f"📅 За сутки: <b>{today['c']}</b>\n"
            f"🤖 Из них автоматом: <b>{auto['c']}</b>\n\n"
            f"<i>Выберите раздел ниже.</i>")


@router.message(Cmd("админ", "admin", "админка", "панель", "админ панель",
                    section=S, usage="админ", desc="🛡 Админ-панель (в личке бота)"))
async def cmd_panel(message: Message, **kw):
    uid = message.from_user.id
    if not await is_staff(uid):
        return await message.answer(
            "🔒 Панель доступна только администрации.\n"
            f"Нужен ранг <b>{rank_label(MIN_RANK)}</b> или выше.")
    await message.answer(await panel_text(uid), reply_markup=panel_kb())


# ═══════════════ ЛОГИ ═══════════════
async def log_page(page: int) -> tuple[str, InlineKeyboardMarkup]:
    total = await db.fetchone("SELECT COUNT(*) c FROM mod_log")
    rows = await db.fetchall(
        "SELECT * FROM mod_log ORDER BY id DESC LIMIT ? OFFSET ?",
        (PAGE, page * PAGE))
    if not rows:
        return ("📋 <b>Логи модерации</b>\n\nЗаписей нет.",
                InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="⬅️ Назад", callback_data="ap:main"),
                    InlineKeyboardButton(text="🏠 В меню",
                                         callback_data="nav:home")]]))

    out = [f"📋 <b>Логи модерации</b> — всего {total['c']}\n"]
    buttons = []
    for r in rows:
        icon = KIND_EMOJI.get(r["kind"], "•")
        when = time.strftime("%d.%m %H:%M", time.localtime(r["ts"]))
        src = "🤖" if r["source"] == "автомодерация" else "👮"
        flag = " ✅" if r["reviewed"] else ""
        # отметка ИИ, если он проверял это наказание
        ai_mark = ""
        try:
            import core_ai as _ai
            v = r["ai_verdict"] if "ai_verdict" in r.keys() else None
            if v and v != "ok":
                ai_mark = f"\n   🧠 {_ai.VERDICT_ICON.get(v,'')} {_ai.VERDICT_TEXT.get(v,v)}"
        except Exception:
            pass
        out.append(
            f"<code>#{r['id']}</code> {icon} <b>{KIND_NAMES.get(r['kind'], r['kind'])}</b>{flag}\n"
            f"   👤 {html.escape(r['target_name'] or '')}\n"
            f"   {src} {html.escape(r['by_name'] or '')}\n"
            f"   📝 {html.escape((r['reason'] or '—')[:60])}\n"
            f"   🕒 {when}{ai_mark}")
        buttons.append([InlineKeyboardButton(
            text=f"{icon} #{r['id']} · {r['target_name'][:14]}",
            callback_data=f"ap:item:{r['id']}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"ap:log:{page-1}"))
    nav.append(InlineKeyboardButton(
        text=f"{page+1}/{max(1, (total['c'] + PAGE - 1) // PAGE)}",
        callback_data="ap:noop"))
    if (page + 1) * PAGE < total["c"]:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"ap:log:{page+1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="⬅️ В панель", callback_data="ap:main"),
                              InlineKeyboardButton(text="🏠 В меню", callback_data="nav:home")])
    return "\n".join(out)[:3800], InlineKeyboardMarkup(inline_keyboard=buttons)


async def item_view(log_id: int) -> tuple[str, InlineKeyboardMarkup]:
    r = await db.fetchone("SELECT * FROM mod_log WHERE id=?", (log_id,))
    if not r:
        return ("Запись не найдена.",
                InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="⬅️ К логам", callback_data="ap:log:0")]]))

    icon = KIND_EMOJI.get(r["kind"], "•")
    src = "🤖 автомодерация" if r["source"] == "автомодерация" else "👮 админ"
    dur = human_period(r["seconds"]) if r["seconds"] else "—"
    chat = await db.fetchone("SELECT title FROM chats WHERE chat_id=?", (r["chat_id"],))

    text = (
        f"{icon} <b>Наказание #{r['id']}</b>\n\n"
        f"Тип: <b>{KIND_NAMES.get(r['kind'], r['kind'])}</b>\n"
        f"⏱ Срок: {dur}\n"
        f"💬 Чат: {html.escape((chat['title'] if chat else '') or str(r['chat_id']))}\n"
        f"🕒 {time.strftime('%d.%m.%Y %H:%M', time.localtime(r['ts']))}\n\n"
        f"👤 <b>Кому:</b> {mention_id(r['target_id'], r['target_name'])}\n"
        f"{src}: <b>{html.escape(r['by_name'] or '')}</b>\n"
        f"📝 <b>Причина:</b> {html.escape(r['reason'] or '—')}\n")

    if r["context"]:
        text += (f"\n💬 <b>Переписка:</b>\n<pre>"
                 f"{html.escape(r['context'][:700])}</pre>")

    rows = []
    # наказать выдавшего — только если это живой админ, а не бот
    if r["by_id"]:
        rows.append([InlineKeyboardButton(
            text="⚖️ Наказать выдавшего", callback_data=f"ap:pun:{r['id']}")])
    rows.append([InlineKeyboardButton(
        text="↩️ Отменить наказание", callback_data=f"ap:undo:{r['id']}")])
    if not r["reviewed"]:
        rows.append([InlineKeyboardButton(
            text="✅ Отметить проверенным", callback_data=f"ap:ok:{r['id']}")])
    rows.append([InlineKeyboardButton(text="⬅️ К логам", callback_data="ap:log:0")])
    return text[:3900], InlineKeyboardMarkup(inline_keyboard=rows)


def punish_kb(log_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ Варн", callback_data=f"ap:do:warn:{log_id}:0")],
        [InlineKeyboardButton(text="🔇 Мут 1ч", callback_data=f"ap:do:mute:{log_id}:3600"),
         InlineKeyboardButton(text="🔇 Мут 12ч", callback_data=f"ap:do:mute:{log_id}:43200")],
        [InlineKeyboardButton(text="🔇 Мут 24ч", callback_data=f"ap:do:mute:{log_id}:86400"),
         InlineKeyboardButton(text="🔨 Бан", callback_data=f"ap:do:ban:{log_id}:0")],
        [InlineKeyboardButton(text="⬇️ Понизить ранг", callback_data=f"ap:do:demote:{log_id}:0")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"ap:item:{log_id}")],
    ])


# ═══════════════ ОБРАБОТКА КНОПОК ═══════════════
@router.callback_query(F.data.startswith("ap:"))
async def cb_panel(call: CallbackQuery, bot: Bot):
    uid = call.from_user.id
    if not await is_staff(uid):
        return await call.answer("Панель только для администрации", show_alert=True)

    parts = call.data.split(":")
    act = parts[1]

    if act == "noop":
        return await call.answer()

    if act == "main":
        await call.message.edit_text(await panel_text(uid), reply_markup=panel_kb())
        return await call.answer()

    if act == "log":
        text, kb = await log_page(int(parts[2]))
        await call.message.edit_text(text, reply_markup=kb)
        return await call.answer()

    if act == "item":
        text, kb = await item_view(int(parts[2]))
        await call.message.edit_text(text, reply_markup=kb)
        return await call.answer()

    if act == "ok":
        await db.execute("UPDATE mod_log SET reviewed=1 WHERE id=?", (int(parts[2]),))
        text, kb = await item_view(int(parts[2]))
        await call.message.edit_text(text, reply_markup=kb)
        return await call.answer("✅ Отмечено")

    if act == "pun":
        log_id = int(parts[2])
        r = await db.fetchone("SELECT * FROM mod_log WHERE id=?", (log_id,))
        if not r or not r["by_id"]:
            return await call.answer("Наказание выдал бот — некого наказывать",
                                     show_alert=True)
        my = await top_rank(uid)
        his = await top_rank(r["by_id"])
        if his >= my and my < MAX_RANK:
            return await call.answer(
                f"⛔️ У него ранг {his}, у вас {my} — нельзя наказать "
                f"равного или старшего", show_alert=True)
        await call.message.edit_text(
            f"⚖️ <b>Наказать за неправильное наказание</b>\n\n"
            f"Кого: <b>{html.escape(r['by_name'] or '')}</b>\n"
            f"За что: {KIND_NAMES.get(r['kind'], r['kind'])} "
            f"«{html.escape((r['reason'] or '')[:50])}»\n"
            f"Пострадал: {html.escape(r['target_name'] or '')}\n\n"
            f"Выберите наказание:", reply_markup=punish_kb(log_id))
        return await call.answer()

    if act == "undo":
        log_id = int(parts[2])
        r = await db.fetchone("SELECT * FROM mod_log WHERE id=?", (log_id,))
        if not r:
            return await call.answer("Не найдено", show_alert=True)
        done = []
        try:
            if r["kind"] == "mute":
                from h_mod_bans import MUTE_ON
                await bot.restrict_chat_member(r["chat_id"], r["target_id"], MUTE_ON)
                await db.execute("DELETE FROM mutes WHERE chat_id=? AND user_id=?",
                                 (r["chat_id"], r["target_id"]))
                done.append("мут снят")
            elif r["kind"] == "ban":
                await bot.unban_chat_member(r["chat_id"], r["target_id"],
                                            only_if_banned=True)
                await db.execute("DELETE FROM bans WHERE chat_id=? AND user_id=?",
                                 (r["chat_id"], r["target_id"]))
                done.append("бан снят")
            elif r["kind"] == "warn":
                await db.execute(
                    "DELETE FROM warns WHERE id=(SELECT id FROM warns WHERE chat_id=? "
                    "AND user_id=? ORDER BY id DESC LIMIT 1)",
                    (r["chat_id"], r["target_id"]))
                done.append("варн снят")
        except Exception as e:
            return await call.answer(f"Не удалось: {str(e)[:150]}", show_alert=True)
        if r["punish_id"]:
            await db.execute(
                "UPDATE punishments SET active=0, lifted_by=?, lifted_ts=? WHERE id=?",
                (uid, int(time.time()), r["punish_id"]))
        await db.execute("UPDATE mod_log SET reviewed=1 WHERE id=?", (log_id,))
        try:
            await bot.send_message(
                r["chat_id"],
                f"↩️ Наказание <code>#{log_id}</code> для "
                f"{mention_id(r['target_id'], r['target_name'])} отменено "
                f"администрацией.")
        except Exception:
            pass
        text, kb = await item_view(log_id)
        await call.message.edit_text(text, reply_markup=kb)
        return await call.answer("↩️ " + (", ".join(done) or "отменено"))

    if act == "do":
        kind, log_id, secs = parts[2], int(parts[3]), int(parts[4])
        r = await db.fetchone("SELECT * FROM mod_log WHERE id=?", (log_id,))
        if not r or not r["by_id"]:
            return await call.answer("Не найдено", show_alert=True)
        target = r["by_id"]
        tname = r["by_name"] or str(target)
        chat_id = r["chat_id"]
        reason = (f"неправомерное наказание #{log_id} "
                  f"({KIND_NAMES.get(r['kind'], r['kind'])} для {r['target_name']})")

        try:
            if kind == "warn":
                await db.execute(
                    "INSERT INTO warns (chat_id,user_id,admin_id,reason,ts) "
                    "VALUES (?,?,?,?,?)",
                    (chat_id, target, uid, reason, int(time.time())))
                label = "⚠️ предупреждение"
            elif kind == "mute":
                until = datetime.now(timezone.utc) + timedelta(seconds=secs)
                await bot.restrict_chat_member(chat_id, target, MUTE_OFF,
                                               until_date=until)
                label = f"🔇 мут на {human_period(secs)}"
            elif kind == "ban":
                await bot.ban_chat_member(chat_id, target)
                label = "🔨 бан"
            elif kind == "demote":
                from core_ranks import get_rank, set_rank
                cur = await get_rank(chat_id, target)
                if cur <= 0:
                    return await call.answer("У него нет ранга", show_alert=True)
                await set_rank(chat_id, target, cur - 1, uid)
                label = f"⬇️ понижен до ранга {cur - 1}"
            else:
                return await call.answer("Неизвестное действие", show_alert=True)
        except Exception as e:
            return await call.answer(f"Не удалось: {str(e)[:160]}", show_alert=True)

        pid = await log_punish(chat_id, target,
                               kind if kind != "demote" else "warn",
                               reason, secs, uid)
        import core_modlog as modlog
        await modlog.write(chat_id, pid, target, tname, uid,
                           call.from_user.first_name or "админ",
                           kind if kind != "demote" else "warn",
                           reason, secs, "разбор", r["context"] or "", bot=bot)
        await db.execute("UPDATE mod_log SET reviewed=1 WHERE id=?", (log_id,))

        try:
            await bot.send_message(
                chat_id,
                f"⚖️ <b>Разбор наказания #{log_id}</b>\n\n"
                f"👮 {mention_id(target, tname)} получает {label}\n"
                f"📝 Причина: неправомерное наказание участника\n"
                f"👤 Решение: {mention_id(uid, call.from_user.first_name)}")
        except Exception:
            pass

        await call.message.edit_text(
            f"✅ <b>Наказание применено</b>\n\n"
            f"👮 {html.escape(tname)} → {label}\n"
            f"📋 Запись <code>#{log_id}</code> отмечена проверенной",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⬅️ К логам", callback_data="ap:log:0")]]))
        return await call.answer("Готово")

    if act == "list":
        kind, page = parts[2], int(parts[3])
        titles = {"mute": "🔇 Мут-лист", "ban": "🔨 Бан-лист",
                  "warn": "⚠️ Варн-лист"}
        rows = await db.fetchall(
            "SELECT p.*, u.first_name, c.title FROM punishments p "
            "LEFT JOIN users u ON u.user_id=p.user_id "
            "LEFT JOIN chats c ON c.chat_id=p.chat_id "
            "WHERE p.kind=? AND p.active=1 ORDER BY p.id DESC LIMIT ? OFFSET ?",
            (kind, PAGE, page * PAGE))
        cnt = await db.fetchone(
            "SELECT COUNT(*) c FROM punishments WHERE kind=? AND active=1", (kind,))
        if not rows:
            text = f"{titles.get(kind, kind)}\n\nСписок пуст."
        else:
            out = [f"{titles.get(kind, kind)} — активных: {cnt['c']}\n"]
            for r in rows:
                left = ""
                if r["seconds"]:
                    rem = r["ts"] + r["seconds"] - int(time.time())
                    left = (f" · ещё {human_period(rem)}" if rem > 0 else " · истёк")
                byname = "🤖 автомодерация"
                if r["by_id"]:
                    by = await db.get_user(r["by_id"])
                    byname = (by["first_name"] or f"id{r['by_id']}") if by \
                        else f"id{r['by_id']}"
                out.append(
                    f"<code>#{r['id']}</code> {mention_id(r['user_id'], r['first_name'])}"
                    f"{left}\n"
                    f"   📝 {html.escape((r['reason'] or '—')[:60])}\n"
                    f"   👮 {html.escape(str(byname))} · "
                    f"{time.strftime('%d.%m %H:%M', time.localtime(r['ts']))}")
            text = "\n".join(out)[:3800]
        # кнопки быстрого снятия
        quick = []
        for r in rows:
            nm = (r["first_name"] or str(r["user_id"]))[:14]
            quick.append([InlineKeyboardButton(
                text=f"↩️ Снять #{r['id']} · {nm}",
                callback_data=f"ap:lift:{kind}:{r['id']}:{page}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                text="◀️", callback_data=f"ap:list:{kind}:{page-1}"))
        nav.append(InlineKeyboardButton(
            text=f"{page+1}/{max(1, (cnt['c'] + PAGE - 1) // PAGE)}",
            callback_data="ap:noop"))
        if (page + 1) * PAGE < cnt["c"]:
            nav.append(InlineKeyboardButton(
                text="▶️", callback_data=f"ap:list:{kind}:{page+1}"))
        kb = InlineKeyboardMarkup(inline_keyboard=[
            *quick, nav,
            [InlineKeyboardButton(text="⬅️ В панель", callback_data="ap:main"),
                              InlineKeyboardButton(text="🏠 В меню", callback_data="nav:home")]])
        await call.message.edit_text(text, reply_markup=kb)
        return await call.answer()

    if act == "auto":
        rows = await db.fetchall(
            "SELECT * FROM mod_log WHERE source='автомодерация' "
            "ORDER BY id DESC LIMIT ?", (PAGE,))
        if not rows:
            text = "🤖 <b>Автомодерация</b>\n\nСрабатываний не было."
            kb_rows = []
        else:
            out = ["🤖 <b>Срабатывания автомодерации</b>\n"]
            kb_rows = []
            for r in rows:
                out.append(
                    f"<code>#{r['id']}</code> {html.escape(r['target_name'] or '')}\n"
                    f"   📝 {html.escape((r['reason'] or '')[:50])}\n"
                    f"   🕒 {time.strftime('%d.%m %H:%M', time.localtime(r['ts']))}")
                kb_rows.append([InlineKeyboardButton(
                    text=f"#{r['id']} · {(r['target_name'] or '')[:16]}",
                    callback_data=f"ap:item:{r['id']}")])
            text = "\n".join(out)[:3800]
        kb_rows.append([InlineKeyboardButton(text="⬅️ В панель",
                                             callback_data="ap:main"),
                        InlineKeyboardButton(text="🏠 В меню",
                                             callback_data="nav:home")])
        await call.message.edit_text(
            text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
        return await call.answer()

    if act == "desc":
        page = int(parts[2]) if len(parts) > 2 else 0
        text, kb = await desc_page(page)
        await call.message.edit_text(text, reply_markup=kb,
                                     disable_web_page_preview=True)
        return await call.answer()

    if act == "remind":
        # рассылка тем, кто не заполнил
        chat_id, topic = await _form_chat_topic()
        rows = await _no_desc_users(chat_id)
        if not rows:
            return await call.answer("Все уже заполнили 🎉", show_alert=True)
        link = _topic_link(chat_id, topic) if topic else ""
        sent = blocked = 0
        for r in rows:
            try:
                await bot.send_message(
                    r["user_id"],
                    f"📝 <b>Напоминание</b>\n\n"
                    f"Вы ещё не заполнили описание в чате.\n"
                    f"Пока его нет, писать в других темах нельзя.\n\n"
                    + (f"✍️ Заполнить здесь:\n{link}\n\n" if link else "")
                    + f"Скопируйте и отправьте, подставив свои данные:\n\n"
                    f"<code>{_TEMPLATE}</code>",
                    disable_web_page_preview=True)
                sent += 1
            except Exception:
                blocked += 1
        await call.answer(
            f"✅ Отправлено: {sent}\n🚫 Не доставлено: {blocked}", show_alert=True)
        text, kb = await desc_page(0)
        await call.message.edit_text(text, reply_markup=kb,
                                     disable_web_page_preview=True)
        return

    if act == "lift":
        kind, pid, page = parts[2], int(parts[3]), int(parts[4])
        r = await db.fetchone("SELECT * FROM punishments WHERE id=?", (pid,))
        if not r:
            return await call.answer("Наказание не найдено", show_alert=True)
        try:
            if kind == "mute":
                from h_mod_bans import MUTE_ON
                await bot.restrict_chat_member(r["chat_id"], r["user_id"], MUTE_ON)
                await db.execute("DELETE FROM mutes WHERE chat_id=? AND user_id=?",
                                 (r["chat_id"], r["user_id"]))
                word = "Мут снят"
            elif kind == "ban":
                await bot.unban_chat_member(r["chat_id"], r["user_id"],
                                            only_if_banned=True)
                await db.execute("DELETE FROM bans WHERE chat_id=? AND user_id=?",
                                 (r["chat_id"], r["user_id"]))
                word = "Бан снят"
            else:
                await db.execute(
                    "DELETE FROM warns WHERE id=(SELECT id FROM warns WHERE chat_id=? "
                    "AND user_id=? ORDER BY id DESC LIMIT 1)",
                    (r["chat_id"], r["user_id"]))
                word = "Варн снят"
        except Exception as e:
            return await call.answer(f"Не удалось: {str(e)[:150]}", show_alert=True)

        await db.execute(
            "UPDATE punishments SET active=0, lifted_by=?, lifted_ts=? WHERE id=?",
            (uid, int(time.time()), pid))
        await db.execute(
            "UPDATE mod_log SET reviewed=1 WHERE punish_id=?", (pid,))

        u = await db.get_user(r["user_id"])
        try:
            await bot.send_message(
                r["chat_id"],
                f"↩️ <b>{word}</b>\n"
                f"👤 {mention_id(r['user_id'], u['first_name'])}\n"
                f"👮 Снял: {mention_id(uid, call.from_user.first_name)}\n"
                f"<i>Наказание было выдано неправомерно.</i>")
        except Exception:
            pass

        call.data = f"ap:list:{kind}:{page}"
        await cb_panel(call, bot)
        return

    if act == "stat":
        rows = await db.fetchall(
            "SELECT by_id, by_name, COUNT(*) c FROM mod_log WHERE by_id<>0 "
            "GROUP BY by_id ORDER BY c DESC LIMIT 10")
        auto = await db.fetchone(
            "SELECT COUNT(*) c FROM mod_log WHERE source='автомодерация'")
        rev = await db.fetchone("SELECT COUNT(*) c FROM mod_log WHERE reviewed=1")
        out = ["📊 <b>Статистика модерации</b>\n",
               f"🤖 Автоматических: <b>{auto['c']}</b>",
               f"✅ Разобрано: <b>{rev['c']}</b>\n",
               "<b>Кто сколько выдал:</b>"]
        for i, r in enumerate(rows, 1):
            out.append(f"{i}. {html.escape(r['by_name'] or '')} — <b>{r['c']}</b>")
        await call.message.edit_text(
            "\n".join(out)[:3800],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⬅️ В панель", callback_data="ap:main"),
                InlineKeyboardButton(text="🏠 В меню", callback_data="nav:home")]]))
        return await call.answer()

    await call.answer()
