"""Конфигурация бота. Все секреты берутся из .env, в коде их нет."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _int_list(raw: str) -> list[int]:
    out = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.append(int(part))
    return out


# --- Основное -------------------------------------------------------------
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID: int = int(os.getenv("OWNER_ID", "0") or 0)
ADMINS: list[int] = list({OWNER_ID, *_int_list(os.getenv("ADMINS", ""))} - {0})

DB_PATH: Path = Path(os.getenv("DB_PATH", BASE_DIR / "data" / "iris.db"))

# --- Экономика ------------------------------------------------------------
CURRENCY = os.getenv("CURRENCY", "🪙")          # символ валюты
CURRENCY_NAME = os.getenv("CURRENCY_NAME", "монет")
START_BALANCE = int(os.getenv("START_BALANCE", "1000"))

DAILY_BONUS = (500, 2500)        # диапазон ежедневного бонуса
DAILY_COOLDOWN = 24 * 3600       # сек
WORK_REWARD = (150, 900)
WORK_COOLDOWN = 60 * 60          # 1 час
CRIME_REWARD = (400, 3000)
CRIME_FINE = (200, 1500)
CRIME_COOLDOWN = 90 * 60
CRIME_SUCCESS_CHANCE = 0.55

MIN_BET = 50
MAX_BET = 500_000
TRANSFER_FEE = 0.03              # 3% комиссия за перевод
BANK_RATE = 0.02                 # 2% в сутки по вкладу

# --- Соц. система ---------------------------------------------------------
XP_PER_MESSAGE = 3
MSG_REWARD = 2                   # монет за сообщение
MSG_REWARD_COOLDOWN = 20         # антифлуд, сек
REP_COOLDOWN = 12 * 3600
WARN_LIMIT = 3                   # варнов до мута
WARN_MUTE_HOURS = 12

LEVELS = [
    (0, "Новичок"), (500, "Бродяга"), (1500, "Работяга"), (4000, "Делец"),
    (9000, "Бизнесмен"), (20000, "Магнат"), (45000, "Олигарх"),
    (100000, "Легенда"), (250000, "Император"),
]


def validate() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "❌ BOT_TOKEN не задан.\n"
            "• Локально: создайте файл .env и впишите BOT_TOKEN=...\n"
            "• На хостинге: добавьте переменную окружения BOT_TOKEN\n"
            "Токен берётся у @BotFather."
        )
    if not OWNER_ID:
        raise SystemExit(
            "❌ OWNER_ID не задан.\n"
            "• Локально: впишите OWNER_ID=... в .env\n"
            "• На хостинге: добавьте переменную окружения OWNER_ID\n"
            "Свой ID узнайте у @userinfobot."
        )
