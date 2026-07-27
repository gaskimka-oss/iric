"""Раздел 19: РП-команды — обнять, поцеловать, ударить и ещё 40+ действий."""
from __future__ import annotations

import time

from aiogram import Bot, Router
from aiogram.types import Message

import db
from core_registry import Cmd
from core_resolve import resolve_target
from utils import mention, mention_id

router = Router(name="rp")
S = 19

# команда: (эмодзи, глагол в 3-м лице, ответ-суффикс)
ACTIONS: dict[str, tuple[str, str]] = {
    # ласковые
    "обнять": ("🤗", "обнимает"),
    "поцеловать": ("😘", "целует"),
    "чмокнуть": ("💋", "чмокает"),
    "погладить": ("🖐", "гладит"),
    "приласкать": ("🥰", "ласкает"),
    "прижать": ("🫂", "прижимает к себе"),
    "взять за руку": ("🤝", "берёт за руку"),
    "потискать": ("🫰", "тискает"),
    "укрыть пледом": ("🛏", "укрывает пледом"),
    "спеть": ("🎤", "поёт песню для"),
    "станцевать": ("💃", "танцует с"),
    "сделать массаж": ("💆", "делает массаж"),
    "подарить цветы": ("💐", "дарит цветы"),
    "подарить подарок": ("🎁", "дарит подарок"),
    "признаться": ("❤️", "признаётся в чувствах"),
    "флиртовать": ("😏", "флиртует с"),
    "подмигнуть": ("😉", "подмигивает"),
    "улыбнуться": ("😊", "улыбается"),
    "похвалить": ("👏", "хвалит"),
    "поздравить": ("🎉", "поздравляет"),
    "поддержать": ("💪", "поддерживает"),
    "утешить": ("🫂", "утешает"),
    "защитить": ("🛡", "защищает"),
    # шуточно-агрессивные
    "ударить": ("👊", "бьёт"),
    "шлёпнуть": ("👋", "шлёпает"),
    "укусить": ("😬", "кусает"),
    "пнуть": ("🦵", "пинает"),
    "толкнуть": ("🫱", "толкает"),
    "щёлкнуть": ("🫰", "щёлкает по лбу"),
    "ущипнуть": ("🤏", "щипает"),
    "дать подзатыльник": ("🖐", "даёт подзатыльник"),
    "кинуть тапок": ("🥿", "кидает тапок в"),
    "облить водой": ("💦", "обливает водой"),
    "закидать снежками": ("❄️", "закидывает снежками"),
    "кинуть торт": ("🎂", "кидает торт в"),
    "связать": ("🪢", "связывает"),
    "похитить": ("🚗", "похищает"),
    "съесть": ("😋", "съедает"),
    "проклясть": ("🔮", "насылает проклятие на"),
    "загрызть": ("🐺", "загрызает"),
    # бытовые
    "покормить": ("🍕", "кормит"),
    "напоить чаем": ("🍵", "поит чаем"),
    "угостить кофе": ("☕️", "угощает кофе"),
    "налить сок": ("🧃", "наливает сок"),
    "дать конфету": ("🍬", "даёт конфету"),
    "испечь торт": ("🍰", "печёт торт для"),
    "разбудить": ("⏰", "будит"),
    "усыпить": ("😴", "укладывает спать"),
    "разбудить пинком": ("🦶", "будит пинком"),
    "помыть": ("🚿", "моет"),
    "постричь": ("✂️", "стрижёт"),
    "полечить": ("💊", "лечит"),
    "сфотографировать": ("📸", "фотографирует"),
    "нарисовать": ("🎨", "рисует портрет"),
    # игровые
    "дать пять": ("🙌", "даёт пять"),
    "сразиться": ("⚔️", "вызывает на бой"),
    "поиграть": ("🎮", "играет с"),
    "спрятаться": ("🙈", "прячется за"),
    "догнать": ("🏃", "догоняет"),
    "потанцевать": ("🕺", "зовёт танцевать"),
    "выпить": ("🥂", "выпивает с"),
    "покурить": ("💨", "идёт курить с"),
    "погулять": ("🚶", "идёт гулять с"),
    "пожать руку": ("🤝", "жмёт руку"),
    "отдать честь": ("🫡", "отдаёт честь"),
    "поклониться": ("🙇", "кланяется"),
    "помолиться": ("🙏", "молится за"),
    "телепортировать": ("🌀", "телепортирует"),
    "заморозить": ("🧊", "замораживает"),
    "поджечь": ("🔥", "поджигает"),
    "оживить": ("✨", "оживляет"),
}

# Список синонимов -> каноничное действие
ALIASES = {
    "обнимашки": "обнять", "обниму": "обнять", "хаг": "обнять",
    "поцелуй": "поцеловать", "кис": "поцеловать", "чмок": "чмокнуть",
    "бить": "ударить", "вдарить": "ударить", "пиздануть": "ударить",
    "кусь": "укусить", "гладить": "погладить", "глажу": "погладить",
    "кормить": "покормить", "чай": "напоить чаем", "кофе": "угостить кофе",
    "будить": "разбудить", "пять": "дать пять",
}


async def _do_action(message: Message, bot: Bot, args: str, action: str):
    uid, name, _ = await resolve_target(message, args, bot)
    emoji, verb = ACTIONS[action]
    if not uid:
        return await message.reply(
            f"{emoji} Кого {action}? Ответьте реплаем или укажите @ника.\n"
            f"Пример: <code>{action} @user</code>")
    if uid == message.from_user.id:
        return await message.reply(f"{emoji} Самого себя? Ну ладно 😄")
    me = await bot.me()
    if uid == me.id:
        return await message.reply(f"{emoji} Спасибо, приятно! 🤖")

    await db.execute(
        "INSERT OR REPLACE INTO relations (user_id,target_id,kind,ts) VALUES (?,?,?,?)",
        (message.from_user.id, uid, action, int(time.time())))
    cnt = await db.fetchone(
        "SELECT COUNT(*) c FROM relations WHERE user_id=? AND kind=?",
        (message.from_user.id, action))
    tail = f"\n<i>Всего раз: {cnt['c']}</i>" if cnt and cnt["c"] > 1 else ""
    await message.reply(f"{emoji} {mention(message.from_user)} {verb} "
                        f"{mention_id(uid, name)}!{tail}")


def _make(action: str):
    async def handler(message: Message, bot: Bot, args: str = "", **kw):
        await _do_action(message, bot, args, action)
    handler.__name__ = f"rp_{abs(hash(action))}"
    return handler


# Регистрируем по одной команде на действие (с синонимами)
_by_action: dict[str, list[str]] = {a: [a] for a in ACTIONS}
for alias, target in ALIASES.items():
    _by_action.setdefault(target, [target]).append(alias)

for _action, _names in _by_action.items():
    _emoji, _verb = ACTIONS[_action]
    router.message.register(
        _make(_action),
        Cmd(*_names, section=S, usage=_action + " {ссылка}",
            desc=f"{_emoji} {_verb.capitalize()} человека"))


@router.message(Cmd("рп", "рп команды", "действия", section=S, usage="РП",
                    desc="Список всех РП-команд"))
async def cmd_rp_list(message: Message, **kw):
    items = [f"{e} {a}" for a, (e, _) in ACTIONS.items()]
    half = (len(items) + 1) // 2
    col1, col2 = items[:half], items[half:]
    lines = ["🎭 <b>РП-команды</b> — всего " + str(len(ACTIONS)) + "\n",
             "Пишите реплаем или с @ником: <code>обнять @user</code>\n"]
    lines += ["  ·  ".join(x for x in pair if x)
              for pair in zip(col1, col2 + [""] * (len(col1) - len(col2)))]
    from h_helpmenu import _safe_cut
    await message.reply(_safe_cut("\n".join(lines), 3900))


@router.message(Cmd("отношения", "мои отношения", "статистика рп", section=S,
                    usage="отношения", desc="Статистика ваших РП-действий"))
async def cmd_rel_stats(message: Message, bot: Bot, args: str = "", **kw):
    uid, name, _ = await resolve_target(message, args, bot)
    if not uid:
        uid, name = message.from_user.id, message.from_user.first_name
    rows = await db.fetchall(
        "SELECT kind, COUNT(*) c FROM relations WHERE user_id=? GROUP BY kind "
        "ORDER BY c DESC LIMIT 15", (uid,))
    if not rows:
        return await message.reply(f"У {mention_id(uid, name)} пока нет РП-действий.\n"
                                   f"Список: <code>рп</code>")
    lines = [f"{ACTIONS.get(r['kind'], ('•',''))[0]} {r['kind']} — {r['c']}" for r in rows]
    await message.reply(f"🎭 <b>РП-статистика</b> {mention_id(uid, name)}\n\n"
                        + "\n".join(lines))
