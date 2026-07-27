"""Раздел 1: команды модерации — ранги 1–7, состав, созыв, импорт списка."""
from __future__ import annotations

import html
import re
import time

from aiogram import Bot, Router
from aiogram.types import Message

import db
from core_ranks import effective_rank, get_rank, rank_label, rank_name, require, set_rank
from core_registry import MAX_RANK, RANK_NAMES, RANK_TITLES, Cmd, stars
from core_resolve import resolve_target
from utils import mention_id

router = Router(name="mod_ranks")
S = 1

# «Ирис»-стиль: 🏐 в чате, ➖ вышел из чата
IN_CHAT, LEFT_CHAT = "🏐", "➖"


USERNAME_OK = re.compile(r"^[A-Za-z0-9_]{4,32}$")


def _link(username: str | None, name: str | None, user_id: int = 0) -> str:
    """Ссылка на профиль: по @нику или tg://user?id=. Без ника — просто имя."""
    label = html.escape(name or username or str(user_id) or "—")
    u = (username or "").lstrip("@")
    if u and USERNAME_OK.match(u):
        return f'<a href="https://telegram.me/{u}">{label}</a>'
    if user_id:
        return f'<a href="tg://user?id={user_id}">{label}</a>'
    return label


async def _staff_rows(chat_id: int) -> dict[int, list[tuple[str, bool]]]:
    """Собирает состав из таблицы ranks (живые) + staff (импортированные)."""
    out: dict[int, list[tuple[str, bool]]] = {}

    rows = await db.fetchall(
        "SELECT r.user_id, r.rank, u.first_name, u.username FROM ranks r "
        "LEFT JOIN users u ON u.user_id = r.user_id "
        "WHERE r.chat_id=? AND r.rank>0", (chat_id,))
    seen_ids = set()
    for r in rows:
        seen_ids.add(r["user_id"])
        out.setdefault(r["rank"], []).append(
            (_link(r["username"], r["first_name"], r["user_id"]), False))

    srows = await db.fetchall(
        "SELECT username, name, rank, user_id, left_chat FROM staff "
        "WHERE chat_id=? ORDER BY rank DESC, pos ASC, rowid ASC", (chat_id,))
    for r in srows:
        if r["user_id"] and r["user_id"] in seen_ids:
            continue
        out.setdefault(r["rank"], []).append(
            (_link(r["username"], r["name"], r["user_id"] or 0), bool(r["left_chat"])))
    return out


def _render_staff(groups: dict[int, list[tuple[str, bool]]], title: str) -> str:
    """Формат как в образце: ⭐⭐⭐⭐⭐ Создатели / 🏐 Имя / ➖ Вышедший."""
    if not groups:
        return ("👮 <b>Состав модерации</b>\n\nПока никого нет.\n"
                "Назначить: <code>+модер 3 @user</code>\n"
                "Импортировать список: <code>импорт состава</code> (реплаем на список)")
    parts = [f"👮 <b>{title}</b>\n"]
    for rank in sorted(groups, reverse=True):
        people = groups[rank]
        if not people:
            continue
        head = RANK_TITLES.get(rank, RANK_NAMES.get(rank, "")) if len(people) > 1 \
            else RANK_NAMES.get(rank, "")
        parts.append(f"<b>{stars(rank)} {head}</b>")
        for link, left in people:
            parts.append(f"{LEFT_CHAT if left else IN_CHAT} {link}")
        parts.append("")
    return "\n".join(parts).strip()


# ---------------- Назначение ----------------
async def _grant(message: Message, bot: Bot, args: str, rank: int):
    rank = max(1, min(rank, MAX_RANK))
    # назначать можно только ранг НИЖЕ своего (кроме владельца с 7)
    me = await effective_rank(message, bot)
    if me < min(rank + 1, MAX_RANK):
        return await message.reply(
            f"⛔️ Недостаточно прав.\nЧтобы выдать <b>{rank_label(rank)}</b>, "
            f"нужен ранг выше.\nВаш ранг: <b>{rank_label(me)}</b>")
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply(
            "Укажите пользователя: реплаем, @ником или id.\n"
            "Пример: <code>+модер 3 @user</code>")
    tgt_rank = await get_rank(message.chat.id, uid)
    if tgt_rank >= me and me < MAX_RANK:
        return await message.reply("⛔️ Нельзя менять ранг равного или старшего.")
    await set_rank(message.chat.id, uid, rank,
                   message.from_user.id if message.from_user else 0)
    await message.reply(
        f"✅ {mention_id(uid, name)} назначен:\n<b>{stars(rank)} {rank_name(rank)}</b>")


@router.message(Cmd("+модер", "+админ", "модер", section=S, rank=2,
                    usage="+модер {ссылка} [1-7]",
                    desc="Назначить ранг модератора (1–7)"))
async def cmd_promote_rank(message: Message, bot: Bot, args: str = "", **kw):
    parts = (args or "").split()
    rank = 1
    if parts and parts[0].isdigit() and 1 <= int(parts[0]) <= MAX_RANK:
        rank = int(parts[0])
        args = args[len(parts[0]):].strip()
    else:
        raw = (message.text or "").strip()
        bangs = len(raw) - len(raw.lstrip("!"))
        if bangs > 1:
            rank = min(bangs, MAX_RANK)
    await _grant(message, bot, args, rank)


@router.message(Cmd("повысить", "поднять", section=S, rank=2, usage="повысить {ссылка} [ранг]",
                    desc="Повысить на один ранг (или до указанного)"))
async def cmd_promote(message: Message, bot: Bot, args: str = "", **kw):
    parts = (args or "").split()
    if parts and parts[0].isdigit() and 1 <= int(parts[0]) <= MAX_RANK:
        rank = int(parts[0])
        return await _grant(message, bot, args[len(parts[0]):].strip(), rank)
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя: реплаем, @ником или id.")
    cur = await get_rank(message.chat.id, uid)
    if cur >= MAX_RANK:
        return await message.reply(f"У пользователя уже максимальный ранг "
                                   f"<b>{rank_label(MAX_RANK)}</b>.")
    await _grant(message, bot, args, cur + 1)


@router.message(Cmd("понизить", "разжаловать", "снизить", section=S, rank=2,
                    usage="понизить {ссылка}", desc="Понизить на один ранг"))
async def cmd_demote(message: Message, bot: Bot, args: str = "", **kw):
    me = await effective_rank(message, bot)
    if me < 2:
        return await message.reply(f"⛔️ Недостаточно прав. Ваш ранг: <b>{rank_label(me)}</b>")
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя.")
    cur = await get_rank(message.chat.id, uid)
    if cur <= 0:
        return await message.reply("У пользователя нет ранга.")
    if cur >= MAX_RANK:
        return await message.reply(
            f"👑 <b>{RANK_NAMES[MAX_RANK]}</b> неприкосновенен — его нельзя понизить.")
    if cur >= me and me < MAX_RANK:
        return await message.reply("⛔️ Нельзя понизить равного или старшего.")
    await set_rank(message.chat.id, uid, cur - 1, message.from_user.id)
    new = cur - 1
    txt = f"<b>{stars(new)} {rank_name(new)}</b>" if new else "<b>Участник</b> (ранг снят)"
    await message.reply(f"⬇️ {mention_id(uid, name)} понижен до {txt}")


@router.message(Cmd("снять всех", "разжаловать всех", section=S, rank=5,
                    usage="!снять всех", desc="Снять ранги со всех модераторов"))
async def cmd_demote_all(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 5):
        return
    await db.execute("DELETE FROM ranks WHERE chat_id=? AND rank < ?",
                     (message.chat.id, MAX_RANK))
    await db.execute("DELETE FROM staff WHERE chat_id=? AND rank < ?",
                     (message.chat.id, MAX_RANK))
    await message.reply(f"🧹 Все ранги сняты.\n"
                        f"👑 {RANK_NAMES[MAX_RANK]} сохраняет свой статус.")


@router.message(Cmd("снять вышедших", section=S, rank=4, usage="снять вышедших",
                    desc="Снять ранги с покинувших чат"))
async def cmd_demote_left(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 4):
        return
    rows = await db.fetchall("SELECT user_id FROM ranks WHERE chat_id=?", (message.chat.id,))
    removed = 0
    for r in rows:
        try:
            m = await bot.get_chat_member(message.chat.id, r["user_id"])
            if m.status in {"left", "kicked"}:
                await set_rank(message.chat.id, r["user_id"], 0, message.from_user.id)
                removed += 1
        except Exception:
            continue
    await db.execute("DELETE FROM staff WHERE chat_id=? AND left_chat=1", (message.chat.id,))
    await message.reply(f"🧹 Снято рангов с вышедших: <b>{removed}</b>")


@router.message(Cmd("снять", "разжаловать ранг", section=S, rank=2, usage="снять {ссылка}",
                    desc="Полностью снять ранг"))
async def cmd_remove_rank(message: Message, bot: Bot, args: str = "", **kw):
    me = await effective_rank(message, bot)
    if me < 2:
        return await message.reply(f"⛔️ Недостаточно прав. Ваш ранг: <b>{rank_label(me)}</b>")
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        return await message.reply("Укажите пользователя.")
    tgt = await get_rank(message.chat.id, uid)
    if tgt >= MAX_RANK:
        return await message.reply(
            f"👑 <b>{RANK_NAMES[MAX_RANK]}</b> неприкосновенен — с него нельзя снять ранг.")
    if tgt >= me and me < MAX_RANK:
        return await message.reply("⛔️ Нельзя снять равного или старшего.")
    await set_rank(message.chat.id, uid, 0, message.from_user.id)
    await db.execute("DELETE FROM staff WHERE chat_id=? AND user_id=?", (message.chat.id, uid))
    await message.reply(f"✅ {mention_id(uid, name)} снят с должности.")


# ---------------- Просмотр состава ----------------
@router.message(Cmd("кто админ", "кто админы", "админы", "кто модер", "кто модеры",
                    "модераторы", "состав", "модерация", "стафф", "персонал",
                    "список админов",
                    section=S, usage="!админы", group_only=True,
                    desc="Показать состав модерации со звёздами"))
async def cmd_staff(message: Message, bot: Bot, **kw):
    groups = await _staff_rows(message.chat.id)
    text = _render_staff(groups, "Состав модерации")

    # ТГ-администраторы, которых бот не может ограничивать
    try:
        admins = await bot.get_chat_administrators(message.chat.id)
        me = await bot.me()
        tg = []
        for m in admins:
            if not m.user or m.user.is_bot or m.user.id == me.id:
                continue
            mark = "👑" if m.status == "creator" else "🛡"
            tg.append(f"{mark} {_link(m.user.username, m.user.first_name, m.user.id)}")
        if tg:
            text += ("\n\n<b>🛡 Администраторы Telegram</b>\n"
                     + "\n".join(tg)
                     + "\n<i>Их бот не может мутить и банить —"
                       " таково ограничение Telegram.</i>")
    except Exception:
        pass

    await message.reply(text, disable_web_page_preview=True)


@router.message(Cmd("кто создатель", "создатели", "creator", section=S, group_only=True,
                    usage="кто создатель", desc="Показать создателей чата"))
async def cmd_creators(message: Message, **kw):
    groups = await _staff_rows(message.chat.id)
    top = {r: p for r, p in groups.items() if r >= 5}
    await message.reply(_render_staff(top, "Руководство чата"),
                        disable_web_page_preview=True)


@router.message(Cmd("ранги", "список рангов", "привилегии", section=S, usage="ранги",
                    desc="Все ранги и их права"))
async def cmd_ranks_help(message: Message, **kw):
    perms = {
        1: "мут, кик, варн, удаление сообщений, созыв",
        2: "бан, чистка, теги, розыгрыши, триггеры, −реп",
        3: "правила, приветствие, награды, лимит варнов",
        4: "доступ команд, автокик, антиспам, сетка",
        5: "снять всех, сброс настроек, полный контроль чата",
        6: "технический доступ: настройки бота, история наказаний",
        7: "заместитель лидера: почти все права, кроме смены лидера",
        8: "высший ранг: все команды без ограничений, неприкосновенен",
    }
    lines = ["🎖 <b>Ранги и привилегии</b>\n"]
    for r in range(MAX_RANK, 0, -1):
        lines.append(f"<b>{stars(r)} {RANK_NAMES[r]}</b> — ранг {r}\n   <i>{perms[r]}</i>")
    lines.append("\nНазначить: <code>+модер 4 @user</code>")
    lines.append("Повысить/понизить: <code>повысить @user</code> · "
                 "<code>понизить @user</code>")
    await message.reply("\n".join(lines))


@router.message(Cmd("лог рангов", "лог модерации", section=S, rank=3, group_only=True, usage="лог рангов",
                    desc="История изменений рангов"))
async def cmd_rank_log(message: Message, bot: Bot, **kw):
    if not await require(message, bot, 3):
        return
    rows = await db.fetchall(
        "SELECT l.*, u.first_name FROM rank_log l LEFT JOIN users u ON u.user_id=l.user_id "
        "WHERE l.chat_id=? ORDER BY l.id DESC LIMIT 15", (message.chat.id,))
    if not rows:
        return await message.reply("Лог пуст.")
    lines = []
    for r in rows:
        lbl = f"{stars(r['rank'])} {rank_name(r['rank'])}" if r["rank"] else "снят"
        lines.append(f"• {mention_id(r['user_id'], r['first_name'])} → {lbl} "
                     f"({time.strftime('%d.%m %H:%M', time.localtime(r['ts']))})")
    await message.reply("📜 <b>Лог изменений рангов</b>\n" + "\n".join(lines))


@router.message(Cmd("созыв", "созвать модерацию", section=S, rank=1, group_only=True, usage="созыв {причина}",
                    desc="Позвать модераторов в чат"))
async def cmd_call_mods(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 1):
        return
    rows = await db.fetchall(
        "SELECT r.user_id, u.first_name FROM ranks r LEFT JOIN users u ON u.user_id=r.user_id "
        "WHERE r.chat_id=? AND r.rank>=1", (message.chat.id,))
    if not rows:
        return await message.reply("Модераторов нет.")
    tags = " ".join(mention_id(r["user_id"], r["first_name"]) for r in rows[:30])
    await message.reply(f"📣 <b>Созыв модерации!</b>\n"
                        f"Причина: {html.escape(args) if args else 'требуется внимание'}\n\n{tags}")


@router.message(Cmd("мой ранг", "ранг", "моя привилегия", section=S, usage="мой ранг", group_only=True,
                    desc="Показать свой ранг"))
async def cmd_my_rank(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, _ = await resolve_target(message, args, bot)
    if uid:
        r = await get_rank(message.chat.id, uid)
        return await message.reply(
            f"{mention_id(uid, name)} — <b>{stars(r) or '—'} {rank_name(r)}</b> (ранг {r})")
    r = await effective_rank(message, bot)
    db_rank = await get_rank(message.chat.id, message.from_user.id)
    src = "выдан в этом чате"
    if message.from_user.id == __import__("config").OWNER_ID:
        src = "владелец бота"
    elif message.sender_chat:
        src = "анонимный админ"
    elif not db_rank:
        try:
            m = await bot.get_chat_member(message.chat.id, message.from_user.id)
            src = {"creator": "создатель чата в Telegram",
                   "administrator": "админ чата в Telegram"}.get(m.status, "участник")
        except Exception:
            src = "участник"
    await message.reply(
        f"Ваш ранг: <b>{stars(r) or '—'} {rank_name(r)}</b> ({r})\n"
        f"<i>Источник: {src}</i>\n"
        f"<i>Чат: <code>{message.chat.id}</code></i>")


# ---------------- Импорт готового списка ----------------
STAR_RE = re.compile(r"^\s*\**\s*(⭐+|\*+)\s*(.+?)\s*\**\s*$")
PERSON_RE = re.compile(
    r"^\s*(🏐|➖|•|·|-)?\s*(?:\[([^\]]+)\]\s*\(\s*<?(?:https?://)?(?:telegram\.me|t\.me)/"
    r"([A-Za-z0-9_]+)[^)]*\)|@([A-Za-z0-9_]{4,})|(.+?))\s*$")

TITLE_TO_RANK = {
    "лидер клана": 7, "лидеры клана": 7, "лидеры кланов": 7,
    "технический администратор": 6, "технические администраторы": 6, "тех админ": 6,
    "создатель": 5, "создатели": 5,
    "старший админ": 4, "старшие админы": 4, "старший администратор": 4,
    "старшие администраторы": 4,
    "младший админ": 3, "младшие админы": 3, "младший администратор": 3,
    "младшие администраторы": 3,
    "старший модератор": 2, "старшие модераторы": 2,
    "младший модератор": 1, "младшие модераторы": 1, "модератор": 1, "модераторы": 1,
}


def _rank_from_title(text: str, star_count: int) -> int:
    t = text.strip().lower().replace("ё", "е")
    for key in sorted(TITLE_TO_RANK, key=len, reverse=True):
        if key in t:
            return TITLE_TO_RANK[key]
    return star_count if 1 <= star_count <= MAX_RANK else 0


def parse_staff_list(text: str) -> list[tuple[str, str, int, bool]]:
    """Разбирает список вида «⭐⭐⭐⭐⭐ Создатели / 🏐 [Имя](ссылка)».

    -> [(username, отображаемое_имя, ранг, вышел_ли)]
    """
    out: list[tuple[str, str, int, bool]] = []
    cur_rank = 0
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        clean = line.replace("*", "").strip()
        stars_found = clean.count("⭐")
        if stars_found or any(k in clean.lower() for k in TITLE_TO_RANK):
            title = clean.replace("⭐", "").strip()
            if title and not title.startswith(("🏐", "➖")):
                r = _rank_from_title(title, stars_found)
                if r:
                    cur_rank = r
                    continue
        if not cur_rank:
            continue
        m = PERSON_RE.match(line)
        if not m:
            continue
        marker, md_name, md_user, at_user, plain = m.groups()
        left = marker == "➖"
        if md_user:
            out.append((md_user, (md_name or md_user).strip(), cur_rank, left))
        elif at_user:
            out.append((at_user, at_user, cur_rank, left))
        elif plain:
            name = plain.strip(" *_")
            if not name or name.lower().startswith(("http", "ирис")):
                continue
            if len(name) > 64:
                continue
            out.append(("", name, cur_rank, left))
    return out


@router.message(Cmd("импорт состава", "загрузить состав", "импорт модерации", section=S,
                    rank=5, usage="импорт состава (реплаем на список)",
                    desc="Загрузить готовый список модерации"))
async def cmd_import_staff(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 5):
        return
    src = args or ""
    if message.reply_to_message:
        src = (message.reply_to_message.text or message.reply_to_message.caption or "") or src
    if not src.strip():
        return await message.reply(
            "Ответьте этой командой на сообщение со списком, например:\n\n"
            "<code>⭐⭐⭐⭐⭐ Создатели\n🏐 [Simba](https://telegram.me/simba253)\n\n"
            "⭐⭐⭐⭐ Старшие админы\n🏐 [Филипп](https://telegram.me/fil1003)</code>")
    people = parse_staff_list(src)
    if not people:
        return await message.reply("Не удалось распознать список. "
                                   "Проверьте формат: строка со звёздами, ниже — люди.")
    now = int(time.time())
    added = 0
    await db.execute("DELETE FROM staff WHERE chat_id=?", (message.chat.id,))
    for pos, (username, name, rank, left) in enumerate(people):
        key = username or name
        uid = 0
        if username:
            row = await db.fetchone(
                "SELECT user_id FROM users WHERE lower(username)=lower(?)", (username,))
            if row:
                uid = row["user_id"]
                await set_rank(message.chat.id, uid, rank, message.from_user.id)
        await db.execute(
            "INSERT INTO staff (chat_id,username,name,rank,user_id,left_chat,ts,pos) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(chat_id,username) DO UPDATE SET "
            "name=excluded.name, rank=excluded.rank, user_id=excluded.user_id, "
            "left_chat=excluded.left_chat, pos=excluded.pos",
            (message.chat.id, key, name, rank, uid, int(left), now, pos))
        added += 1
    groups = await _staff_rows(message.chat.id)
    await message.reply(
        f"✅ Загружено записей: <b>{added}</b>\n\n" + _render_staff(groups, "Состав модерации"),
        disable_web_page_preview=True)


@router.message(Cmd("добавить в состав", section=S, rank=4,
                    usage="добавить в состав {ранг} @user Имя",
                    desc="Добавить человека в состав вручную"))
async def cmd_add_staff(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 4):
        return
    parts = (args or "").split()
    if not parts or not parts[0].isdigit():
        return await message.reply("Формат: <code>добавить в состав 4 @user Филипп</code>")
    rank = max(1, min(int(parts[0]), MAX_RANK))
    rest = " ".join(parts[1:])
    m = re.search(r"@([A-Za-z0-9_]{4,})", rest)
    username = m.group(1) if m else ""
    name = rest.replace(f"@{username}", "").strip() or username
    if not username and not name:
        return await message.reply("Укажите @ник или имя.")
    row = await db.fetchone("SELECT COALESCE(MAX(pos),0)+1 p FROM staff WHERE chat_id=?",
                            (message.chat.id,))
    await db.execute(
        "INSERT INTO staff (chat_id,username,name,rank,user_id,left_chat,ts,pos) "
        "VALUES (?,?,?,?,0,0,?,?) ON CONFLICT(chat_id,username) DO UPDATE SET "
        "name=excluded.name, rank=excluded.rank",
        (message.chat.id, username or name, name, rank, int(time.time()), row["p"]))
    await message.reply(f"✅ Добавлен в состав: <b>{stars(rank)} {html.escape(name)}</b>")


@router.message(Cmd("удалить из состава", section=S, rank=4,
                    usage="удалить из состава @user", desc="Убрать из состава"))
async def cmd_del_staff(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 4):
        return
    a = (args or "").strip().lstrip("@")
    if not a:
        return await message.reply("Формат: <code>удалить из состава @user</code>")
    await db.execute("DELETE FROM staff WHERE chat_id=? AND (lower(username)=lower(?) "
                     "OR lower(name)=lower(?))", (message.chat.id, a, a))
    await message.reply(f"🗑 Удалено из состава: <b>{html.escape(a)}</b>")


@router.message(Cmd("глобальные ранги", "единые ранги", section=S, rank=5,
                    usage="глобальные ранги вкл|выкл",
                    desc="Одно звание во всех чатах"))
async def cmd_global_ranks(message: Message, bot: Bot, args: str = "", **kw):
    if not await require(message, bot, 5):
        return
    a = (args or "").strip().lower()
    if a in {"вкл", "on", "да"}:
        await db.set_setting(message.chat.id, "global_ranks", "1")
        return await message.reply(
            "✅ <b>Глобальные ранги включены</b>\n\n"
            "Звание человека одинаково во всех чатах и темах: "
            "берётся его наивысший ранг.")
    if a in {"выкл", "off", "нет"}:
        await db.set_setting(message.chat.id, "global_ranks", "0")
        return await message.reply(
            "⚠️ <b>Глобальные ранги выключены</b>\n\n"
            "Теперь ранг действует только в том чате, где выдан.")
    cur = await db.get_setting(message.chat.id, "global_ranks", "1")
    await message.reply(
        f"🌐 Глобальные ранги: <b>{'включены' if cur == '1' else 'выключены'}</b>\n\n"
        f"<i>Включено — звание одинаково во всех чатах.</i>\n"
        f"Изменить: <code>глобальные ранги выкл</code>")
