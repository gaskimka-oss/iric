"""ДК — «Доступ команд»: гибкая настройка прав на каждую команду.

Логика проверки для команды `key` в чате:
  1. если команда отключена (enabled=0) — молча игнорируем;
  2. если задан личный доступ (cmd_personal) — пользователю можно всегда;
  3. если задан свой ранг (cmd_access.rank) — сравниваем с ним;
  4. иначе — базовый ранг команды из реестра.
"""
from __future__ import annotations

from typing import Optional

import db
from core_ranks import effective_rank, rank_label

# кэш настроек: {chat_id: {cmd: (rank, enabled)}}
_cache: dict[int, dict[str, tuple[int, int]]] = {}
_personal: dict[int, dict[tuple[str, int], str]] = {}


def invalidate(chat_id: int) -> None:
    _cache.pop(chat_id, None)
    _personal.pop(chat_id, None)


async def _load(chat_id: int) -> dict[str, tuple[int, int]]:
    if chat_id not in _cache:
        rows = await db.fetchall(
            "SELECT cmd, rank, enabled FROM cmd_access WHERE chat_id=?", (chat_id,))
        _cache[chat_id] = {r["cmd"]: (int(r["rank"]), int(r["enabled"])) for r in rows}
    return _cache[chat_id]


async def _load_personal(chat_id: int) -> dict[tuple[str, int], str]:
    if chat_id not in _personal:
        rows = await db.fetchall(
            "SELECT cmd, user_id, mode FROM cmd_personal WHERE chat_id=?", (chat_id,))
        _personal[chat_id] = {(r["cmd"], r["user_id"]): (r["mode"] or "allow") for r in rows}
    return _personal[chat_id]


async def required_rank(chat_id: int, key: str, base: int) -> tuple[int, bool]:
    """-> (нужный_ранг, включена_ли_команда)"""
    conf = await _load(chat_id)
    if key in conf:
        rank, enabled = conf[key]
        return rank, bool(enabled)
    return base, True


async def check(message, bot, key: str, base_rank: int,
                had_prefix: bool = True) -> Optional[str]:
    """None — можно выполнять. Иначе текст отказа ('' = молча проигнорировать)."""
    chat = message.chat
    if chat.type == "private":
        return None

    need, enabled = await required_rank(chat.id, key, base_rank)
    if not enabled:
        return ""  # команда выключена в этом чате — тихо игнорируем

    uid = message.from_user.id if message.from_user else 0
    pers = await _load_personal(chat.id)
    mode = pers.get((key, uid)) if uid else None

    # −ЛДК: команда отобрана лично у человека
    if mode == "deny":
        from core_registry import MAX_RANK
        have = await effective_rank(message, bot)
        if have < MAX_RANK:      # у лидера отобрать нельзя
            quiet = await db.get_setting(chat.id, "dk_silent", "0") == "1"
            return "" if quiet else (
                "🔒 У вас <b>отобран</b> доступ к этой команде.\n"
                "Вернуть может админ: <code>+лдк @вы команда</code>")

    if mode == "allow":
        return None              # +ЛДК: выдан личный доступ

    if need <= 0:
        return None

    have = await effective_rank(message, bot)
    if have >= need:
        return None

    quiet = await db.get_setting(chat.id, "dk_silent", "0") == "1"
    if quiet:
        return ""

    # Человек написал обычную фразу без префикса («всем привет»,
    # «сбор в 5»), а она случайно совпала с командой. Ругаться на это
    # нельзя — просто молчим, будто ничего не было.
    if not had_prefix:
        return ""

    return (f"⛔️ Недостаточно прав для этой команды.\n"
            f"Нужен ранг: <b>{rank_label(need)}</b>\n"
            f"Ваш ранг: <b>{rank_label(have) if have else 'Участник'}</b>")


ALLOWED_WITHOUT_FORM = {
    "описание", "+описание", "шаблон", "анкета", "инфа", "команды", "ид",
    "мой ранг", "правила", "меню", "найти", "справка",
}


async def form_gate(message, bot) -> bool:
    """True — сообщение пропускаем. False — участник не заполнил анкету."""
    chat = message.chat
    if chat.type == "private":
        return True
    if not message.from_user or message.from_user.is_bot:
        return True

    from h_userinfo import needs_form
    if not await needs_form(chat.id, message.from_user.id):
        return True

    # модерация не блокируется
    from core_ranks import effective_rank
    if await effective_rank(message, bot) >= 1:
        return True
    return False


async def access_middleware(handler, event, data: dict):
    """Применяет ДК и антифлуд до вызова хэндлера."""
    key = data.get("cmd_key")
    if key:
        # антифлуд: защита от перегрузки в больших чатах
        import core_throttle as throttle
        uid = event.from_user.id if event.from_user else 0
        if uid and not throttle.check(uid):
            if throttle.should_warn(uid):
                try:
                    await event.reply("⏳ Слишком много команд подряд. "
                                      "Подождите несколько секунд.")
                except Exception:
                    pass
            return
        bot = data.get("bot")
        verdict = await check(event, bot, key, int(data.get("cmd_rank") or 0),
                              bool(data.get("had_prefix", True)))
        if verdict is not None:
            if verdict:
                try:
                    await event.reply(verdict)
                except Exception:
                    pass
            return
        # незаполнившим анкету доступны только базовые команды
        if key not in ALLOWED_WITHOUT_FORM:
            bot = data.get("bot")
            if not await form_gate(event, bot):
                from h_userinfo import (get_form_topic, topic_id,
                                               topic_link)
                ft = await get_form_topic(event.chat.id)
                if ft and topic_id(event) != ft:
                    msg = ("📝 Сначала заполните описание в теме:\n"
                           + topic_link(event.chat.id, ft))
                else:
                    msg = "📝 Сначала заполните описание — команда <code>шаблон</code>"
                try:
                    await event.reply(msg, disable_web_page_preview=True)
                except Exception:
                    pass
                return

        # тема описаний — только для незаполнивших: остальным там тихо
        if key not in {"описание", "+описание", "шаблон", "тема описания",
                       "анкета обязательна"}:
            try:
                from h_userinfo import (get_form_topic, needs_form,
                                               topic_id)
                ft = await get_form_topic(event.chat.id)
                if ft and topic_id(event) == ft and event.from_user:
                    if not await needs_form(event.chat.id, event.from_user.id):
                        from core_ranks import effective_rank
                        if await effective_rank(event, data.get("bot")) < 1:
                            return
            except Exception:
                pass

        # доступ разрешён на уровне ДК — внутренние require() не должны спорить
        try:
            object.__setattr__(event, "_dk_ok", True)
        except Exception:
            pass
    return await handler(event, data)
