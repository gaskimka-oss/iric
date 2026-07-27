"""Постоянное меню внизу экрана (reply-клавиатура).

Кнопки всегда на виду, командами пользоваться не обязательно.
Клавиатура появляется сразу после капчи и держится всё время.
У администрации первой строкой — кнопка админ-панели.
"""
from __future__ import annotations

from aiogram.types import (KeyboardButton, ReplyKeyboardMarkup,
                           ReplyKeyboardRemove)

# Тексты кнопок = существующие команды бота, поэтому нажатие
# обрабатывается обычными хэндлерами, ничего дублировать не нужно.
BTN_ADMIN = "🛡 Админ-панель"
BTN_MENU = "📋 Меню"
BTN_BALANCE = "🍬 Баланс"
BTN_BONUS = "🎁 Бонус"
BTN_GRAMS = "💊 Граммы"
BTN_GAMES = "🎮 Игры"
BTN_PROFILE = "📝 Описание"
BTN_HELP = "📖 Команды"

# что реально выполняется при нажатии
ALIASES: dict[str, str] = {
    BTN_ADMIN: "админ",
    BTN_MENU: "меню",
    BTN_BALANCE: "баланс",
    BTN_BONUS: "бонус",
    BTN_GRAMS: "б",
    BTN_GAMES: "игры",
    BTN_PROFILE: "описание",
    BTN_HELP: "команды",
}


def resolve(text: str) -> str | None:
    """Текст нажатой кнопки -> команда. None, если это не кнопка."""
    return ALIASES.get((text or "").strip())


async def main_menu(uid: int = 0) -> ReplyKeyboardMarkup:
    """Постоянная клавиатура. Админ-кнопка видна только администрации."""
    rows = [
        [KeyboardButton(text=BTN_MENU), KeyboardButton(text=BTN_HELP)],
        [KeyboardButton(text=BTN_BALANCE), KeyboardButton(text=BTN_BONUS)],
        [KeyboardButton(text=BTN_GRAMS), KeyboardButton(text=BTN_GAMES)],
        [KeyboardButton(text=BTN_PROFILE)],
    ]
    if uid:
        try:
            from h_adminpanel import is_staff
            if await is_staff(uid):
                rows.insert(0, [KeyboardButton(text=BTN_ADMIN)])
        except Exception:
            pass
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,                 # не прячется после нажатия
        input_field_placeholder="Выберите кнопку или напишите команду")


def hide() -> ReplyKeyboardRemove:
    """Убрать клавиатуру — на время капчи."""
    return ReplyKeyboardRemove()
