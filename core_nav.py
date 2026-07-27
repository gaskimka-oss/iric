"""Единая навигация: кнопка «В меню» в любом инлайн-меню бота.

Чтобы человек никогда не оказывался в тупике, все меню получают
кнопку возврата. Добавляется одной функцией — новые меню тоже
не забудутся.
"""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup)

HOME = "🏠 В меню"
BACK = "⬅️ Назад"

HOME_CB = "nav:home"


def home_btn() -> InlineKeyboardButton:
    return InlineKeyboardButton(text=HOME, callback_data=HOME_CB)


def back_btn(cb: str, text: str = BACK) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb)


router = Router(name="nav")


@router.callback_query(F.data == HOME_CB)
async def cb_home(call: CallbackQuery, bot: Bot):
    """Возврат в меню. В личке — главное меню бота,
    в группе — список разделов команд (там личного меню нет)."""
    try:
        if call.message.chat.type == "private":
            import db
            from h_start import main_kb, main_text
            u = await db.get_user(call.from_user.id)
            await call.message.edit_text(
                await main_text(call.from_user.first_name, u),
                reply_markup=await main_kb(call.from_user.id))
        else:
            from h_helpmenu import _menu_kb, _menu_text
            await call.message.edit_text(_menu_text(), reply_markup=_menu_kb(0))
    except Exception:
        pass
    await call.answer()


def _has(rows: list[list[InlineKeyboardButton]], cb: str) -> bool:
    return any(getattr(b, "callback_data", None) == cb for r in rows for b in r)


def with_home(kb: InlineKeyboardMarkup | None = None, *,
              back: str | None = None,
              back_text: str = BACK) -> InlineKeyboardMarkup:
    """Добавляет к меню строку возврата.

    back — callback «на шаг назад» (если есть куда). Кнопка «В меню»
    ставится всегда, кроме случая, когда она уже есть.
    """
    rows: list[list[InlineKeyboardButton]] = []
    if kb is not None and kb.inline_keyboard:
        rows = [list(r) for r in kb.inline_keyboard]

    line: list[InlineKeyboardButton] = []
    if back and not _has(rows, back):
        line.append(back_btn(back, back_text))
    if not _has(rows, HOME_CB):
        line.append(home_btn())
    if line:
        rows.append(line)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def only_home(back: str | None = None,
              back_text: str = BACK) -> InlineKeyboardMarkup:
    """Клавиатура из одной строки возврата — для простых ответов."""
    return with_home(None, back=back, back_text=back_text)
