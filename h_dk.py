"""Раздел 4: ДК — «Доступ команд». Гибкая настройка прав на каждую команду."""
from __future__ import annotations

import html
import time

from aiogram import Bot, F, Router
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

import db
import core_access as access
from core_ranks import effective_rank, rank_label, require
from core_registry import (MAX_RANK, RANK_NAMES, REGISTRY, SECTION_EMOJI,
                           SECTIONS, Cmd, registry_by_section, stars)
from core_resolve import resolve_target
from utils import mention_id

router = Router(name="dk")
S = 4


def _find_cmd(name: str):
    """Ищет команду реестра по любому её синониму."""
    n = (name or "").strip().lower().replace("ё", "е")
    if not n:
        return None
    for c in REGISTRY:
        if any(n == x.lower().replace("ё", "е") for x in c.names):
            return c
    for c in REGISTRY:
        if any(x.lower().replace("ё", "е").startswith(n) for x in c.names):
            return c
    return None


async def _log(chat_id: int, cmd: str, rank: int, enabled: int, by: int) -> None:
    await db.execute(
        "INSERT INTO access_log (chat_id,cmd,rank,enabled,by_id,ts) VALUES (?,?,?,?,?,?)",
        (chat_id, cmd, rank, enabled, by, int(time.time())))
    access.invalidate(chat_id)


def _kb_main() -> InlineKeyboardMarkup:
    by = registry_by_section()
    rows, buf = [], []
    for n in sorted(SECTIONS):
        if not by.get(n):
            continue
        buf.append(InlineKeyboardButton(
            text=f"{SECTION_EMOJI.get(n,'•')} {SECTIONS[n][:18]}", callback_data=f"dk:s:{n}:0"))
        if len(buf) == 2:
            rows.append(buf); buf = []
    if buf:
        rows.append(buf)
    return InlineKeyboardMarkup(inline_keyboard=rows[:14])


async def _section_view(chat_id: int, num: int) -> tuple[str, InlineKeyboardMarkup]:
    cmds = registry_by_section().get(num, [])
    lines = [f"{SECTION_EMOJI.get(num,'•')} <b>ДК — {SECTIONS[num]}</b>\n",
             "Нажмите команду, чтобы изменить нужный ранг.\n"]
    rows = []
    for c in cmds[:20]:
        need, enabled = await access.required_rank(chat_id, c.key, c.base_rank)
        mark = "" if enabled else "🚫 "
        lines.append(f"{mark}<code>{html.escape(c.names[0])}</code> — "
                     f"{stars(need) or 'все'} {RANK_NAMES.get(need,'')}".rstrip())
        rows.append([InlineKeyboardButton(
            text=f"{mark}{c.names[0][:22]} · {need}", callback_data=f"dk:c:{num}:{c.key[:40]}")])
    rows.append([InlineKeyboardButton(text="⬅️ Разделы", callback_data="dk:m")])
    return "\n".join(lines)[:3800], InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Cmd("дк", "доступ команд", "доступ", "настройка команд", section=S,
                    rank=4, usage="ДК", desc="Доступ команд: гибкая настройка прав"))
async def cmd_dk(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 4):
        return
    a = (args or "").strip()

    # «ДК» без аргументов — меню
    if not a:
        rows = await db.fetchall(
            "SELECT cmd, rank, enabled FROM cmd_access WHERE chat_id=?", (message.chat.id,))
        changed = "\n".join(
            f"• <code>{html.escape(r['cmd'])}</code> → "
            f"{stars(r['rank']) or 'все'} {RANK_NAMES.get(r['rank'],'')}"
            + ("" if r["enabled"] else " <i>(выключена)</i>") for r in rows[:15])
        return await message.reply(
            "🔐 <b>ДК — Доступ команд</b>\n\n"
            "Гибкая настройка прав: какой ранг нужен для каждой команды.\n\n"
            "<b>Как пользоваться:</b>\n"
            "<code>ДК бан 3</code> — команда «бан» с 3 ранга\n"
            "<code>ДК казино выкл</code> — отключить команду\n"
            "<code>ДК казино вкл</code> — включить обратно\n"
            "<code>ДК бан</code> — узнать текущий доступ\n"
            "<code>ДК сброс</code> — вернуть настройки по умолчанию\n"
            "<code>ДК список</code> — все изменённые команды\n"
            "<code>ДК личный @user бан</code> — доступ конкретному человеку\n\n"
            + (f"<b>Изменено сейчас:</b>\n{changed}" if rows else
               "<i>Пока всё по умолчанию.</i>"),
            reply_markup=_kb_main())

    low = a.lower()

    # ДК сброс
    if low in {"сброс", "reset", "сбросить"}:
        await db.execute("DELETE FROM cmd_access WHERE chat_id=?", (message.chat.id,))
        await db.execute("DELETE FROM cmd_personal WHERE chat_id=?", (message.chat.id,))
        access.invalidate(message.chat.id)
        return await message.reply("♻️ Настройки доступа сброшены к значениям по умолчанию.")

    # ДК список
    if low in {"список", "лист", "list"}:
        rows = await db.fetchall(
            "SELECT cmd, rank, enabled FROM cmd_access WHERE chat_id=? ORDER BY cmd",
            (message.chat.id,))
        if not rows:
            return await message.reply("Все команды работают с настройками по умолчанию.")
        lines = [f"• <code>{html.escape(r['cmd'])}</code> → "
                 f"{stars(r['rank']) or 'все'} {RANK_NAMES.get(r['rank'],'')}"
                 + ("" if r["enabled"] else " <i>(выключена)</i>") for r in rows]
        return await message.reply("🔐 <b>Изменённые команды</b>\n" + "\n".join(lines)[:3800])

    # ДК тихо вкл/выкл — не ругаться на нехватку прав
    if low.startswith(("тихо", "молча")):
        val = "1" if low.split()[-1] in {"вкл", "on", "да"} else "0"
        await db.set_setting(message.chat.id, "dk_silent", val)
        return await message.reply(
            "🔕 Отказы о правах отключены." if val == "1" else "🔔 Отказы о правах включены.")

    # ДК личный @user команда
    if low.startswith(("личный", "персональный", "личка")):
        rest = a.split(maxsplit=1)[1] if len(a.split()) > 1 else ""
        # команду ищем ПЕРЕД разбором пользователя: она всегда последнее слово
        words = rest.split()
        cmd = None
        for take in range(1, min(4, len(words)) + 1):
            cand = " ".join(words[-take:])
            found = _find_cmd(cand)
            if found:
                cmd, rest = found, " ".join(words[:-take])
                break
        uid, name, _ = await resolve_target(message, rest, bot)
        if not uid and rest.strip().isdigit():
            uid = int(rest.strip())
            row = await db.fetchone("SELECT first_name FROM users WHERE user_id=?", (uid,))
            name = row["first_name"] if row else str(uid)
        if not uid or not cmd:
            return await message.reply(
                "Формат: <code>ДК личный @user бан</code>\n"
                "Можно реплаем или по id: <code>ДК личный 123456789 бан</code>")
        await db.execute(
            "INSERT OR REPLACE INTO cmd_personal (chat_id,cmd,user_id,by_id,ts) "
            "VALUES (?,?,?,?,?)", (message.chat.id, cmd.key, uid,
                                   message.from_user.id, int(time.time())))
        access.invalidate(message.chat.id)
        return await message.reply(
            f"🔑 {mention_id(uid, name)} получил личный доступ к "
            f"<code>{html.escape(cmd.names[0])}</code>")

    if low.startswith(("снять личный", "убрать личный")):
        rest = " ".join(a.split()[2:])
        words = rest.split()
        cmd = None
        for take in range(1, min(4, len(words)) + 1):
            found = _find_cmd(" ".join(words[-take:]))
            if found:
                cmd, rest = found, " ".join(words[:-take])
                break
        uid, name, _ = await resolve_target(message, rest, bot)
        if not uid and rest.strip().isdigit():
            uid = int(rest.strip())
            name = str(uid)
        if uid and cmd:
            await db.execute("DELETE FROM cmd_personal WHERE chat_id=? AND cmd=? AND user_id=?",
                             (message.chat.id, cmd.key, uid))
            access.invalidate(message.chat.id)
            return await message.reply(f"🔒 Личный доступ снят у {mention_id(uid, name)}")
        return await message.reply("Формат: <code>ДК снять личный @user бан</code>")

    # ДК <команда> [ранг|вкл|выкл]
    parts = a.split()
    val = parts[-1].lower() if len(parts) > 1 else ""
    name_part = " ".join(parts[:-1]) if val else a

    if val in {"выкл", "off", "выключить", "0н"}:
        cmd = _find_cmd(name_part)
        if not cmd:
            return await message.reply(f"Команда «{html.escape(name_part)}» не найдена.")
        await db.execute(
            "INSERT INTO cmd_access (chat_id,cmd,rank,enabled) VALUES (?,?,?,0) "
            "ON CONFLICT(chat_id,cmd) DO UPDATE SET enabled=0",
            (message.chat.id, cmd.key, cmd.base_rank))
        await _log(message.chat.id, cmd.key, cmd.base_rank, 0, message.from_user.id)
        return await message.reply(f"🚫 Команда <code>{html.escape(cmd.names[0])}</code> "
                                   f"отключена в этом чате.")

    if val in {"вкл", "on", "включить"}:
        cmd = _find_cmd(name_part)
        if not cmd:
            return await message.reply(f"Команда «{html.escape(name_part)}» не найдена.")
        await db.execute(
            "INSERT INTO cmd_access (chat_id,cmd,rank,enabled) VALUES (?,?,?,1) "
            "ON CONFLICT(chat_id,cmd) DO UPDATE SET enabled=1",
            (message.chat.id, cmd.key, cmd.base_rank))
        await _log(message.chat.id, cmd.key, cmd.base_rank, 1, message.from_user.id)
        return await message.reply(f"✅ Команда <code>{html.escape(cmd.names[0])}</code> включена.")

    if val.isdigit():
        rank = max(0, min(int(val), MAX_RANK))
        cmd = _find_cmd(name_part)
        if not cmd:
            return await message.reply(f"Команда «{html.escape(name_part)}» не найдена.\n"
                                       f"Посмотреть список: <code>ДК</code>")
        me = await effective_rank(message, bot)
        if rank > me:
            return await message.reply(
                f"⛔️ Нельзя установить ранг выше своего.\nВаш ранг: <b>{rank_label(me)}</b>")
        await db.execute(
            "INSERT INTO cmd_access (chat_id,cmd,rank,enabled) VALUES (?,?,?,1) "
            "ON CONFLICT(chat_id,cmd) DO UPDATE SET rank=excluded.rank, enabled=1",
            (message.chat.id, cmd.key, rank))
        await _log(message.chat.id, cmd.key, rank, 1, message.from_user.id)
        lbl = f"{stars(rank)} {RANK_NAMES.get(rank)}" if rank else "всем участникам"
        return await message.reply(
            f"🔐 <code>{html.escape(cmd.names[0])}</code> теперь доступна: <b>{lbl}</b>")

    # ДК <команда> — показать текущий доступ
    cmd = _find_cmd(a)
    if not cmd:
        return await message.reply(f"Команда «{html.escape(a)}» не найдена.\n"
                                   f"Открыть меню: <code>ДК</code>")
    need, enabled = await access.required_rank(message.chat.id, cmd.key, cmd.base_rank)
    pers = await db.fetchall(
        "SELECT p.user_id, u.first_name FROM cmd_personal p LEFT JOIN users u "
        "ON u.user_id=p.user_id WHERE p.chat_id=? AND p.cmd=?", (message.chat.id, cmd.key))
    extra = ""
    if pers:
        extra = "\n🔑 Личный доступ: " + ", ".join(
            mention_id(p["user_id"], p["first_name"]) for p in pers)
    await message.reply(
        f"🔐 <b>{html.escape(cmd.usage)}</b>\n"
        f"{html.escape(cmd.desc)}\n\n"
        f"Раздел: {SECTIONS.get(cmd.section,'')}\n"
        f"Нужный ранг: <b>{stars(need) or '—'} {RANK_NAMES.get(need,'Участник')}</b>\n"
        f"Состояние: {'✅ включена' if enabled else '🚫 выключена'}\n"
        f"Синонимы: {html.escape(', '.join(cmd.names[:5]))}{extra}\n\n"
        f"Изменить: <code>ДК {cmd.names[0]} 3</code>")


@router.callback_query(F.data.startswith("dk:"))
async def cb_dk(call: CallbackQuery, bot: Bot):
    r = await effective_rank(call.message, bot) if call.message else 0
    # ранг проверяем по нажавшему
    from core_ranks import get_rank
    from config import ADMINS, OWNER_ID
    uid = call.from_user.id
    have = MAX_RANK if (uid == OWNER_ID or uid in ADMINS) else \
        await get_rank(call.message.chat.id, uid)
    if have < 4:
        return await call.answer("Нужен ранг ⭐⭐⭐⭐ Старший админ", show_alert=True)

    parts = call.data.split(":")
    if parts[1] == "m":
        rows = await db.fetchall("SELECT cmd, rank, enabled FROM cmd_access WHERE chat_id=?",
                                 (call.message.chat.id,))
        changed = "\n".join(
            f"• <code>{html.escape(x['cmd'])}</code> → {stars(x['rank']) or 'все'}"
            for x in rows[:15])
        await call.message.edit_text(
            "🔐 <b>ДК — Доступ команд</b>\n\nВыберите раздел:\n\n"
            + (changed if rows else "<i>Всё по умолчанию.</i>"), reply_markup=_kb_main())
        return await call.answer()

    if parts[1] == "s":
        text, kb = await _section_view(call.message.chat.id, int(parts[2]))
        await call.message.edit_text(text, reply_markup=kb)
        return await call.answer()

    if parts[1] == "c":
        num, key = int(parts[2]), parts[3]
        cmd = next((c for c in REGISTRY if c.key[:40] == key), None)
        if not cmd:
            return await call.answer("Команда не найдена", show_alert=True)
        need, enabled = await access.required_rank(call.message.chat.id, cmd.key, cmd.base_rank)
        rows, buf = [], []
        for rk in range(0, MAX_RANK + 1):
            mark = "✅ " if rk == need else ""
            buf.append(InlineKeyboardButton(text=f"{mark}{rk}",
                                            callback_data=f"dk:r:{num}:{key}:{rk}"))
            if len(buf) == 4:
                rows.append(buf); buf = []
        if buf:
            rows.append(buf)
        rows.append([InlineKeyboardButton(
            text="🚫 Выключить" if enabled else "✅ Включить",
            callback_data=f"dk:t:{num}:{key}")])
        rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dk:s:{num}:0")])
        await call.message.edit_text(
            f"🔐 <b>{html.escape(cmd.usage)}</b>\n{html.escape(cmd.desc)}\n\n"
            f"Сейчас: <b>{stars(need) or '—'} {RANK_NAMES.get(need,'Участник')}</b>"
            f" · {'включена' if enabled else 'выключена'}\n\n"
            f"Выберите минимальный ранг:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        return await call.answer()

    if parts[1] == "r":
        num, key, rk = int(parts[2]), parts[3], int(parts[4])
        cmd = next((c for c in REGISTRY if c.key[:40] == key), None)
        if not cmd:
            return await call.answer("Не найдено", show_alert=True)
        if rk > have:
            return await call.answer("Нельзя выставить ранг выше своего", show_alert=True)
        await db.execute(
            "INSERT INTO cmd_access (chat_id,cmd,rank,enabled) VALUES (?,?,?,1) "
            "ON CONFLICT(chat_id,cmd) DO UPDATE SET rank=excluded.rank, enabled=1",
            (call.message.chat.id, cmd.key, rk))
        await _log(call.message.chat.id, cmd.key, rk, 1, uid)
        text, kb = await _section_view(call.message.chat.id, num)
        await call.message.edit_text(text, reply_markup=kb)
        return await call.answer(f"✅ {cmd.names[0]} → ранг {rk}")

    if parts[1] == "t":
        num, key = int(parts[2]), parts[3]
        cmd = next((c for c in REGISTRY if c.key[:40] == key), None)
        if not cmd:
            return await call.answer("Не найдено", show_alert=True)
        need, enabled = await access.required_rank(call.message.chat.id, cmd.key, cmd.base_rank)
        new = 0 if enabled else 1
        await db.execute(
            "INSERT INTO cmd_access (chat_id,cmd,rank,enabled) VALUES (?,?,?,?) "
            "ON CONFLICT(chat_id,cmd) DO UPDATE SET enabled=excluded.enabled",
            (call.message.chat.id, cmd.key, need, new))
        await _log(call.message.chat.id, cmd.key, need, new, uid)
        text, kb = await _section_view(call.message.chat.id, num)
        await call.message.edit_text(text, reply_markup=kb)
        return await call.answer("✅ Включена" if new else "🚫 Выключена")

    await call.answer()


@router.message(Cmd("лог дк", "лог доступа", section=S, rank=4,
                    usage="лог ДК [{команда}|от @юзер]",
                    desc="История изменений доступа команд"))
async def cmd_dk_log(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 4):
        return
    a = (args or "").strip()

    # лог дк от @юзер
    if a.lower().startswith("от"):
        rest = a[2:].strip()
        uid, uname, _ = await resolve_target(message, rest, bot)
        if not uid and rest.strip().isdigit():
            uid = int(rest.strip()); uname = rest.strip()
        if not uid:
            return await message.reply("Формат: <code>лог дк от @юзер</code>")
        rows = await db.fetchall(
            "SELECT * FROM access_log WHERE chat_id=? AND by_id=? "
            "ORDER BY id DESC LIMIT 15", (message.chat.id, uid))
        head = f"📜 <b>Изменения ДК от</b> {mention_id(uid, uname)}"
    # лог дк {команда}
    elif a:
        cmd = _find_cmd(a)
        if not cmd:
            return await message.reply(f"Команда «{html.escape(a)}» не найдена.")
        rows = await db.fetchall(
            "SELECT * FROM access_log WHERE chat_id=? AND cmd=? "
            "ORDER BY id DESC LIMIT 15", (message.chat.id, cmd.key))
        head = f"📜 <b>Изменения ДК:</b> <code>{html.escape(cmd.names[0])}</code>"
    else:
        rows = await db.fetchall(
            "SELECT * FROM access_log WHERE chat_id=? ORDER BY id DESC LIMIT 15",
            (message.chat.id,))
        head = "📜 <b>Лог изменений доступа команд</b>"

    if not rows:
        return await message.reply(head + "\n\nЗаписей нет.")
    lines = [head, ""]
    for r in rows:
        u = await db.get_user(r["by_id"]) if r["by_id"] else None
        who = mention_id(r["by_id"], u["first_name"]) if u else "система"
        state = "🚫 выключена" if not r["enabled"] else (
            f"ранг {r['rank']}" if r["rank"] else "всем")
        lines.append(f"• <code>{html.escape(r['cmd'])}</code> → {state}\n"
                     f"   {who} · {time.strftime('%d.%m %H:%M', time.localtime(r['ts']))}")
    await message.reply("\n".join(lines)[:3800], disable_web_page_preview=True)



# ================= ЛДК — Личный доступ команд =================
def _split_cmd(rest: str):
    """Из хвоста строки вытаскивает команду реестра (может быть из 2-3 слов)."""
    words = rest.split()
    for take in range(min(4, len(words)), 0, -1):
        found = _find_cmd(" ".join(words[-take:]))
        if found:
            return found, " ".join(words[:-take])
    return None, rest


async def _ldk_apply(message: Message, bot: Bot, args: str, mode: str):
    """mode='allow' (+ЛДК) или 'deny' (−ЛДК)."""
    if not await require(message, bot, 4):
        return
    cmd, rest = _split_cmd((args or "").strip())
    uid, name, _ = await resolve_target(message, rest, bot)
    if not uid and rest.strip().isdigit():
        uid = int(rest.strip())
        row = await db.fetchone("SELECT first_name FROM users WHERE user_id=?", (uid,))
        name = row["first_name"] if row else str(uid)
    if not uid or not cmd:
        verb = "выдать" if mode == "allow" else "забрать"
        return await message.reply(
            f"❗️ Формат: <code>{'+' if mode == 'allow' else '-'}лдк @юзер команда</code>\n\n"
            f"Примеры:\n"
            f"<code>{'+' if mode == 'allow' else '-'}лдк @user мут</code>\n"
            f"<code>{'+' if mode == 'allow' else '-'}лдк бан</code> <i>(реплаем)</i>\n\n"
            f"Так можно {verb} доступ к конкретной команде отдельному человеку.")

    # у Лидера клана ничего не отобрать
    from core_ranks import get_rank
    from core_registry import MAX_RANK, RANK_NAMES
    if mode == "deny" and await get_rank(message.chat.id, uid) >= MAX_RANK:
        return await message.reply(f"👑 У <b>{RANK_NAMES[MAX_RANK]}</b> нельзя "
                                   f"отобрать команды.")
    me_rank = await effective_rank(message, bot)
    tgt_rank = await get_rank(message.chat.id, uid)
    if tgt_rank >= me_rank and me_rank < MAX_RANK:
        return await message.reply("⛔️ Нельзя менять доступ равному или старшему по рангу.")

    await db.execute(
        "INSERT INTO cmd_personal (chat_id,cmd,user_id,mode,by_id,ts) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(chat_id,cmd,user_id) DO UPDATE SET mode=excluded.mode, "
        "by_id=excluded.by_id, ts=excluded.ts",
        (message.chat.id, cmd.key, uid, mode, message.from_user.id, int(time.time())))
    access.invalidate(message.chat.id)
    if mode == "allow":
        await message.reply(
            f"🔑 <b>Доступ выдан</b>\n"
            f"👤 {mention_id(uid, name)}\n"
            f"⚙️ Команда: <code>{html.escape(cmd.names[0])}</code>\n"
            f"<i>Теперь доступна независимо от ранга.</i>")
    else:
        await message.reply(
            f"🔒 <b>Доступ отобран</b>\n"
            f"👤 {mention_id(uid, name)}\n"
            f"⚙️ Команда: <code>{html.escape(cmd.names[0])}</code>\n"
            f"<i>Вернуть: </i><code>+лдк @юзер {html.escape(cmd.names[0])}</code>")


@router.message(Cmd("+лдк", "+ лдк", "плюс лдк", "выдать команду", section=S, rank=4,
                    usage="+ЛДК {ссылка} {команда}",
                    desc="Выдать личный доступ к команде"))
async def cmd_ldk_add(message: Message, bot: Bot, args: str = "", **kw):
    await _ldk_apply(message, bot, args, "allow")


@router.message(Cmd("-лдк", "- лдк", "минус лдк", "забрать команду", section=S, rank=4,
                    usage="-ЛДК {ссылка} {команда}",
                    desc="Забрать доступ к команде у человека"))
async def cmd_ldk_del(message: Message, bot: Bot, args: str = "", **kw):
    await _ldk_apply(message, bot, args, "deny")


@router.message(Cmd("лдк", "личный доступ", section=S, rank=4, usage="ЛДК [{ссылка}]",
                    desc="Список личных доступов"))
async def cmd_ldk_list(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 4):
        return
    uid, name, _ = await resolve_target(message, args or "", bot)
    if uid:
        rows = await db.fetchall(
            "SELECT cmd, mode FROM cmd_personal WHERE chat_id=? AND user_id=?",
            (message.chat.id, uid))
        if not rows:
            return await message.reply(f"У {mention_id(uid, name)} нет личных настроек.")
        plus = [r["cmd"] for r in rows if r["mode"] == "allow"]
        minus = [r["cmd"] for r in rows if r["mode"] == "deny"]
        out = [f"🔑 <b>Личный доступ</b> {mention_id(uid, name)}\n"]
        if plus:
            out.append("✅ <b>Выдано:</b> " + ", ".join(f"<code>{html.escape(c)}</code>"
                                                        for c in plus))
        if minus:
            out.append("🔒 <b>Отобрано:</b> " + ", ".join(f"<code>{html.escape(c)}</code>"
                                                          for c in minus))
        return await message.reply("\n".join(out))

    rows = await db.fetchall(
        "SELECT p.cmd, p.user_id, p.mode, u.first_name FROM cmd_personal p "
        "LEFT JOIN users u ON u.user_id=p.user_id WHERE p.chat_id=? ORDER BY p.mode, p.cmd",
        (message.chat.id,))
    if not rows:
        return await message.reply(
            "🔑 <b>ЛДК — Личный доступ команд</b>\n\n"
            "Персональные права поверх рангов.\n\n"
            "<code>+лдк @user мут</code> — выдать команду человеку\n"
            "<code>-лдк @user бан</code> — забрать команду\n"
            "<code>лдк @user</code> — что настроено у человека\n\n"
            "<i>Пока настроек нет.</i>")
    out = ["🔑 <b>Личные доступы чата</b>\n"]
    for r in rows[:30]:
        icon = "✅" if r["mode"] == "allow" else "🔒"
        out.append(f"{icon} {mention_id(r['user_id'], r['first_name'])} — "
                   f"<code>{html.escape(r['cmd'])}</code>")
    await message.reply("\n".join(out)[:3800])


# ================= ЗАМЕТКА «ДК» =================
DK_NOTE = """🗓 <b>Заметка «дк»</b>

⚙️ Доступ ко всем командам можно настроить по рангам, открыть для всех
или отключить. Истинный владелец чата всегда может изменять ДК,
не имея ранга.

✅ <b>Просмотр доступа команд</b>
• <code>Доступ команд</code> — список доступности команд.
• <code>Мой доступ команд</code> — персональный список доступности.
• <code>ДК 1</code> … <code>ДК 7</code> — что доступно указанному рангу.

✅ <b>Настройка доступа команд</b>
• <code>Дк {код} 0</code> — включит команду всем.
   Пример: <code>!Дк пинг 0</code>
• <code>Дк {код} 8</code> — отключит команду всем.
   Пример: <code>!Дк казино 8</code>
• <code>Дк {код} {ранг}</code> — ограничит команду до ранга.
   Пример: <code>!Дк бан 2</code>

✅ Команды <code>+Дк {раздел}</code> и <code>-Дк {раздел}</code>
включают и отключают целый раздел.

✅ <b>Доступ команд по сетке</b>
• <code>Сетка +дк {код}</code> — включит ДК в каждом чате сетки.
• <code>Сетка -дк {код}</code> — выключит ДК в каждом чате сетки.
• <code>Сетка дк {код} {ранг}</code> — установит ранг во всех чатах.

✅ <b>Настройка ДК в ЛС</b>
• <code>+Дк в лс</code> / <code>-Дк в лс</code> — разрешит / запретит
   редактирование доступа команд чата через личку бота.
💬 Команда доступна только владельцу чата.

✅ <b>Логи изменения ДК</b>
• <code>Лог дк</code> — общий список последних изменений.
• <code>Лог дк {название}</code> — изменения указанной команды.
• <code>Лог дк от @юзер</code> — изменения от пользователя.

✅ <b>Оповещения о доступности</b>
• <code>+Команды</code> / <code>-Команды</code> — включит / выключит
   оповещения о нехватке прав."""


@router.message(Cmd("заметка дк", "дк заметка", "дк помощь", "справка дк",
                    section=S, usage="заметка ДК", desc="Полная справка по ДК"))
async def cmd_dk_note(message: Message, **kw):
    await message.reply(DK_NOTE, disable_web_page_preview=True)


# ================= ДК {РАНГ} — что доступно рангу =================
@router.message(Cmd("дк 0", "дк 1", "дк 2", "дк 3", "дк 4", "дк 5", "дк 6", "дк 7", "дк 8",
                    section=S, usage="ДК {ранг}",
                    desc="Какие команды доступны указанному рангу"))
async def cmd_dk_rank(message: Message, bot: Bot, cmd_name: str = "", **kw):
    """Показывает ТОЛЬКО админские команды ранга — без общедоступных."""
    try:
        rank = int(cmd_name.split()[-1])
    except (ValueError, IndexError):
        return

    by_sec = registry_by_section()
    avail: dict[int, list[tuple[str, int]]] = {}
    total = 0
    base_total = 0     # сколько команд доступно всем (ранг 0)

    for num in sorted(by_sec):
        for c in by_sec[num]:
            need, enabled = await access.required_rank(message.chat.id, c.key,
                                                       c.base_rank)
            if not enabled:
                continue
            if need <= 0:
                base_total += 1        # общая команда — в список не пишем
                continue
            if need <= rank:
                avail.setdefault(num, []).append((c.names[0], need))
                total += 1

    head = (f"{stars(rank) or '▫️'} <b>Ранг {rank} — "
            f"{RANK_NAMES.get(rank, 'Участник')}</b>\n"
            f"🔧 Админ-команд: <b>{total}</b>\n"
            f"👥 Общих команд (есть у всех): <b>{base_total}</b>\n")

    if rank <= 0:
        return await message.reply(
            head + f"\nУ обычных участников <b>нет админских команд</b> — "
            f"только {base_total} общих: игры, экономика, профиль, РП.\n\n"
            f"Посмотреть права модерации: <code>ДК 1</code> … <code>ДК {MAX_RANK}</code>")

    if not avail:
        return await message.reply(head + "\nАдминских команд не назначено.")

    out = [head, f"<i>Ниже — только то, чего нет у обычных участников.</i>"]
    for num in sorted(avail):
        items = avail[num]
        out.append(f"\n{SECTION_EMOJI.get(num,'•')} <b>{SECTIONS[num]}</b> ({len(items)})")
        out.append("  " + ", ".join(
            f"<code>{html.escape(n)}</code><sub>{rk}</sub>" if False
            else f"<code>{html.escape(n)}</code>" for n, rk in items[:25]))

    # что добавилось именно на этом ранге
    fresh = [n for items in avail.values() for n, rk in items if rk == rank]
    if fresh:
        out.append(f"\n🆕 <b>Открылось на этом ранге:</b>\n  "
                   + ", ".join(f"<code>{html.escape(n)}</code>" for n in fresh[:20]))

    text = "\n".join(out)
    if len(text) > 3800:
        text = text[:3700].rsplit("\n", 1)[0] + "\n\n<i>…список сокращён</i>"
    await message.reply(text)


# ================= МОЙ ДОСТУП КОМАНД =================
@router.message(Cmd("мой доступ команд", "мой доступ", "мои команды", section=S,
                    usage="мой доступ команд",
                    desc="Персональный список доступных команд"))
async def cmd_my_access(message: Message, bot: Bot, **kw):
    have = await effective_rank(message, bot)
    uid = message.from_user.id
    pers = await db.fetchall(
        "SELECT cmd, mode FROM cmd_personal WHERE chat_id=? AND user_id=?",
        (message.chat.id, uid))
    allow = {r["cmd"] for r in pers if r["mode"] == "allow"}
    deny = {r["cmd"] for r in pers if r["mode"] == "deny"}

    by_sec = registry_by_section()
    ok = blocked = 0
    for num in by_sec:
        for c in by_sec[num]:
            need, enabled = await access.required_rank(message.chat.id, c.key,
                                                       c.base_rank)
            if c.key in deny or not enabled:
                blocked += 1
            elif c.key in allow or have >= need:
                ok += 1
            else:
                blocked += 1

    out = [f"🔑 <b>Ваш доступ команд</b>",
           f"Ранг: <b>{stars(have) or '▫️'} {RANK_NAMES.get(have,'Участник')}</b>\n",
           f"✅ Доступно: <b>{ok}</b>",
           f"🚫 Недоступно: <b>{blocked}</b>"]
    if allow:
        out.append("\n🔑 <b>Выдано лично:</b> " + ", ".join(
            f"<code>{html.escape(c)}</code>" for c in sorted(allow)))
    if deny:
        out.append("🔒 <b>Отобрано:</b> " + ", ".join(
            f"<code>{html.escape(c)}</code>" for c in sorted(deny)))
    out.append(f"\nСписок доступного: <code>ДК {have}</code>")
    await message.reply("\n".join(out))


# ================= +ДК / -ДК РАЗДЕЛ =================
def _find_section(text: str) -> int | None:
    t = (text or "").strip().lower().replace("ё", "е")
    if not t:
        return None
    if t.isdigit() and int(t) in SECTIONS:
        return int(t)
    for num, title in SECTIONS.items():
        low = title.lower().replace("ё", "е").replace("«", "").replace("»", "")
        if t in low or low.startswith(t):
            return num
    return None


async def _section_bulk(message: Message, bot: Bot, args: str, enable: bool):
    if not await require(message, bot, 4):
        return
    num = _find_section(args)
    if num is None:
        lines = [f"  <code>{n}</code> — {SECTIONS[n]}"
                 for n in sorted(SECTIONS) if registry_by_section().get(n)]
        return await message.reply(
            f"Укажите раздел: <code>{'+' if enable else '-'}ДК 14</code> "
            f"или <code>{'+' if enable else '-'}ДК развлекательные</code>\n\n"
            + "\n".join(lines)[:3500])
    cmds = registry_by_section().get(num, [])
    for c in cmds:
        await db.execute(
            "INSERT INTO cmd_access (chat_id,cmd,rank,enabled) VALUES (?,?,?,?) "
            "ON CONFLICT(chat_id,cmd) DO UPDATE SET enabled=excluded.enabled",
            (message.chat.id, c.key, c.base_rank, 1 if enable else 0))
        await _log(message.chat.id, c.key, c.base_rank, 1 if enable else 0,
                   message.from_user.id)
    access.invalidate(message.chat.id)
    await message.reply(
        f"{'✅' if enable else '🚫'} Раздел <b>{SECTION_EMOJI.get(num,'')} "
        f"{SECTIONS[num]}</b> ({len(cmds)} команд) "
        f"{'включён' if enable else 'отключён'} в этом чате.")


@router.message(Cmd("+дк", "+ дк", "плюс дк", section=S, rank=4,
                    usage="+ДК {раздел}", desc="Включить целый раздел команд"))
async def cmd_dk_sec_on(message: Message, bot: Bot, args: str = "", **kw):
    await _section_bulk(message, bot, args, True)


@router.message(Cmd("-дк", "- дк", "минус дк", section=S, rank=4,
                    usage="-ДК {раздел}", desc="Отключить целый раздел команд"))
async def cmd_dk_sec_off(message: Message, bot: Bot, args: str = "", **kw):
    await _section_bulk(message, bot, args, False)


# ================= СЕТКА ДК =================
@router.message(Cmd("сетка дк", "сетка +дк", "сетка -дк", section=S, rank=5,
                    usage="сетка дк {код} {ранг}",
                    desc="Применить ДК ко всем чатам сетки"))
async def cmd_net_dk(message: Message, bot: Bot, args: str = "",
                     cmd_name: str = "", **kw):
    if not await require(message, bot, 5):
        return
    chats = await db.fetchall("SELECT chat_id FROM net_chats WHERE net_id=?",
                              (message.from_user.id,))
    if not chats:
        return await message.reply(
            "🕸 Сетка пуста.\nДобавьте чаты: <code>сетка добавить</code> в каждом чате.")

    parts = (args or "").split()
    mode = cmd_name.replace("сетка", "").strip()
    rank = None
    if parts and parts[-1].isdigit():
        rank = int(parts[-1])
        parts = parts[:-1]
    cmd = _find_cmd(" ".join(parts))
    if not cmd:
        return await message.reply(
            "Формат:\n<code>сетка +дк бан</code> — включить во всех чатах\n"
            "<code>сетка -дк казино</code> — выключить\n"
            "<code>сетка дк бан 3</code> — ранг 3 во всех чатах")

    if mode == "+дк":
        rank_v, enabled = cmd.base_rank, 1
    elif mode == "-дк":
        rank_v, enabled = cmd.base_rank, 0
    else:
        if rank is None:
            return await message.reply("Укажите ранг: <code>сетка дк бан 3</code>")
        rank_v, enabled = max(0, min(rank, MAX_RANK)), 1

    for c in chats:
        await db.execute(
            "INSERT INTO cmd_access (chat_id,cmd,rank,enabled) VALUES (?,?,?,?) "
            "ON CONFLICT(chat_id,cmd) DO UPDATE SET rank=excluded.rank, "
            "enabled=excluded.enabled", (c["chat_id"], cmd.key, rank_v, enabled))
        await _log(c["chat_id"], cmd.key, rank_v, enabled, message.from_user.id)
        access.invalidate(c["chat_id"])

    state = ("включена" if enabled else "выключена") if mode in ("+дк", "-дк") \
        else f"→ ранг {rank_v}"
    await message.reply(f"🕸 <code>{html.escape(cmd.names[0])}</code> {state} "
                        f"в <b>{len(chats)}</b> чатах сетки.")


# ================= ДК В ЛС =================
@router.message(Cmd("+дк в лс", "-дк в лс", "дк в лс", section=S, rank=5,
                    usage="+ДК в лс", desc="Разрешить настройку ДК через личку"))
async def cmd_dk_pm(message: Message, bot: Bot, cmd_name: str = "", **kw):
    if not await require(message, bot, 5):
        return
    if cmd_name.startswith("+"):
        await db.set_setting(message.chat.id, "dk_pm", "1")
        return await message.reply("✅ Настройка ДК этого чата через личку бота "
                                   "<b>разрешена</b>.")
    if cmd_name.startswith("-"):
        await db.set_setting(message.chat.id, "dk_pm", "0")
        return await message.reply("🚫 Настройка ДК через личку <b>запрещена</b>.")
    cur = await db.get_setting(message.chat.id, "dk_pm", "0")
    await message.reply(f"ДК через личку: <b>{'разрешена' if cur=='1' else 'запрещена'}</b>\n"
                        f"Изменить: <code>+дк в лс</code> / <code>-дк в лс</code>")


# ================= ОПОВЕЩЕНИЯ =================
@router.message(Cmd("+команды", "-команды", section=S, rank=4,
                    usage="+команды", desc="Оповещения о нехватке прав"))
async def cmd_notify(message: Message, bot: Bot, cmd_name: str = "", **kw):
    if not await require(message, bot, 4):
        return
    if cmd_name.startswith("+"):
        await db.set_setting(message.chat.id, "dk_silent", "0")
        return await message.reply("🔔 Оповещения о доступности команд <b>включены</b>.")
    await db.set_setting(message.chat.id, "dk_silent", "1")
    await message.reply("🔕 Оповещения о доступности команд <b>выключены</b>.\n"
                        "Бот будет молча игнорировать команды без прав.")
