"""ИИ-слой бота: анализ чата и проверка справедливости наказаний.

Две задачи:
  1) смотреть за чатом — оценивать сообщения тоньше словаря;
  2) проверять каждое наказание — правомерно оно или нет,
     и сообщать владельцу, если модератор перегнул.

Работает через любой OpenAI-совместимый API (OpenAI, DeepSeek,
OpenRouter, Groq и т. п.). Ключ берётся из переменной AI_API_KEY.
Без ключа бот работает как раньше — на словаре.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import urllib.request

log = logging.getLogger("irisbot.ai")

KEY = (os.getenv("AI_API_KEY") or "").strip()


def _guess() -> tuple[str, str]:
    """Определяем сервис и модель по виду ключа.

    Чтобы на хостинге хватило ОДНОЙ переменной AI_API_KEY —
    остальное бот подставит сам. Заданные вручную AI_API_URL
    и AI_MODEL всегда важнее догадки.
    """
    if KEY.startswith("sk-or-"):        # OpenRouter
        return ("https://openrouter.ai/api/v1/chat/completions",
                "google/gemma-4-31b-it:free")
    if KEY.startswith("gsk_"):          # Groq
        return ("https://api.groq.com/openai/v1/chat/completions",
                "llama-3.3-70b-versatile")
    if KEY.startswith("sk-proj-") or KEY.startswith("sk-svcacct-"):
        return ("https://api.openai.com/v1/chat/completions", "gpt-4o-mini")
    if KEY.startswith("sk-"):           # DeepSeek и OpenAI-совместимые
        return ("https://api.deepseek.com/v1/chat/completions",
                "deepseek-chat")
    return ("https://api.openai.com/v1/chat/completions", "gpt-4o-mini")


_URL_GUESS, _MODEL_GUESS = _guess()

URL = (os.getenv("AI_API_URL") or _URL_GUESS).strip()
MODEL = (os.getenv("AI_MODEL") or _MODEL_GUESS).strip()

TIMEOUT = int(os.getenv("AI_TIMEOUT", "20") or 20)

# Запасные модели: бесплатные тарифы часто перегружены (ошибка 429),
# поэтому просим сервис перебрать несколько по очереди.
# Работает у OpenRouter; другие сервисы поле просто игнорируют.
FALLBACKS = [m.strip() for m in (os.getenv("AI_FALLBACKS") or
    "google/gemma-4-26b-a4b-it:free,"
    "openrouter/free").split(",") if m.strip()]

MAX_MODELS = 3          # ограничение OpenRouter: не больше трёх в списке


def _models() -> list[str]:
    """Основная модель + запасные, без повторов."""
    out = [MODEL]
    if "openrouter" in URL.lower():
        for m in FALLBACKS:
            if m not in out and len(out) < MAX_MODELS:
                out.append(m)
    return out


def available() -> bool:
    return bool(KEY)


def provider() -> str:
    """Понятное имя сервиса — для команды «ии»."""
    u = URL.lower()
    for host, name in (("openai", "OpenAI"), ("deepseek", "DeepSeek"),
                       ("openrouter", "OpenRouter"), ("groq", "Groq"),
                       ("mistral", "Mistral"), ("anthropic", "Anthropic"),
                       ("gigachat", "GigaChat"), ("yandex", "YandexGPT")):
        if host in u:
            return name
    return "свой сервер"


def _ask(system: str, user: str, max_tokens: int = 220) -> dict | None:
    """Синхронный запрос. None — если ИИ недоступен или ответ битый."""
    if not KEY:
        return None
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user[:3500]}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    alts = _models()
    if len(alts) > 1:
        payload["models"] = alts        # сервис сам возьмёт доступную
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        URL, body,
        {"Content-Type": "application/json",
         "Authorization": f"Bearer {KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.load(r)
        if "error" in data and "choices" not in data:
            log.warning("ИИ вернул ошибку: %s", str(data["error"])[:160])
            return None
        content = (data["choices"][0]["message"].get("content") or "").strip()
        if not content:
            log.warning("ИИ вернул пустой ответ (модель «думала» слишком долго)")
            return None
        content = re.sub(r"^```(?:json)?|```$", "", content).strip()
        # иногда модель добавляет текст вокруг JSON — вырезаем сам объект
        if not content.startswith("{"):
            m = re.search(r"\{.*\}", content, re.S)
            if m:
                content = m.group(0)
        return json.loads(content)
    except Exception as e:
        log.warning("ИИ недоступен: %s", str(e)[:160])
        return None


async def ask(system: str, user: str, max_tokens: int = 220) -> dict | None:
    """Асинхронная обёртка — не блокирует бота.

    Бесплатные модели иногда возвращают пустой ответ или упираются
    в лимит провайдера, поэтому делаем вторую попытку.
    """
    for attempt in (1, 2):
        try:
            res = await asyncio.to_thread(_ask, system, user, max_tokens)
        except Exception:
            res = None
        if res is not None:
            return res
        if attempt == 1:
            await asyncio.sleep(1.5)
    return None


# ══════════════════ 1. НАДЗОР ЗА НАКАЗАНИЯМИ ══════════════════
REVIEW_PROMPT = (
    "Ты — независимый арбитр в русскоязычном игровом чате. "
    "Модератор выдал наказание. По переписке реши, справедливо ли оно.\n\n"
    "Правила чата:\n"
    "• мат «в воздух» («бля», «пиздец», «заебался») — НЕ нарушение\n"
    "• дружеские подколы между своими — НЕ нарушение\n"
    "• спор и несогласие без перехода на личности — НЕ нарушение\n"
    "• адресное оскорбление («ты дебил», «иди нахуй») — нарушение\n"
    "• травля, угрозы, спам, реклама — нарушение\n\n"
    "Оцени соразмерность: за лёгкую грубость сутки мута — перебор, "
    "за травлю час — мягко, но допустимо.\n\n"
    "Ответь СТРОГО в JSON:\n"
    '{"verdict": "ok|soft|harsh|wrong", "score": 0-10, '
    '"reason": "одно предложение", "advice": "что стоило сделать"}\n\n'
    "ok — наказание справедливо и соразмерно\n"
    "soft — нарушение было, но наказание слишком мягкое\n"
    "harsh — нарушение было, но наказание слишком суровое\n"
    "wrong — нарушения не было, наказание несправедливо\n"
    "score — насколько уверен в вердикте, 10 = полностью"
)

VERDICT_ICON = {"ok": "✅", "soft": "🟡", "harsh": "🟠", "wrong": "🔴"}
VERDICT_TEXT = {
    "ok": "справедливо",
    "soft": "слишком мягко",
    "harsh": "слишком сурово",
    "wrong": "несправедливо",
}


async def review_punishment(kind: str, reason: str, seconds: int,
                            target: str, moderator: str,
                            context: str) -> dict | None:
    """Проверяет наказание. -> {verdict, score, reason, advice} или None."""
    if not KEY:
        return None
    from core_resolve import human_period
    term = human_period(seconds) if seconds else "бессрочно"
    kinds = {"mute": "мут", "ban": "бан", "warn": "предупреждение",
             "kick": "кик"}
    q = (f"Наказание: {kinds.get(kind, kind)} на {term}\n"
         f"Кого: {target}\n"
         f"Кто выдал: {moderator}\n"
         f"Указанная причина: {reason or '(не указана)'}\n\n"
         f"Переписка перед наказанием:\n{context or '(нет данных)'}")
    res = await ask(REVIEW_PROMPT, q, max_tokens=220)
    if not isinstance(res, dict):
        return None
    v = str(res.get("verdict", "")).lower()
    if v not in VERDICT_ICON:
        return None
    try:
        score = max(0, min(int(res.get("score", 5)), 10))
    except Exception:
        score = 5
    return {"verdict": v, "score": score,
            "reason": str(res.get("reason", ""))[:200],
            "advice": str(res.get("advice", ""))[:200]}


def render_review(r: dict, kind: str, target: str, moderator: str,
                  term: str) -> str:
    """Красивый текст отчёта для владельца."""
    icon = VERDICT_ICON.get(r["verdict"], "•")
    what = VERDICT_TEXT.get(r["verdict"], r["verdict"])
    out = [f"🧠 <b>ИИ проверил наказание</b>\n",
           f"{icon} Вердикт: <b>{what}</b> (уверенность {r['score']}/10)\n",
           f"⚖️ {kind} · {term}",
           f"👤 Кому: {target}",
           f"👮 Выдал: {moderator}\n",
           f"💬 {r['reason']}"]
    if r.get("advice") and r["verdict"] != "ok":
        out.append(f"💡 {r['advice']}")
    return "\n".join(out)


# ══════════════════ 2. НАБЛЮДЕНИЕ ЗА ЧАТОМ ══════════════════
WATCH_PROMPT = (
    "Ты модератор русскоязычного игрового чата. Оцени ПОСЛЕДНЕЕ сообщение "
    "с учётом переписки вокруг него.\n\n"
    "Шкала:\n"
    "0 — нормально: общение, шутки между своими, мат «в воздух», спор по делу\n"
    "1 — грубость, хамство, капс, провокация\n"
    "2 — прямое оскорбление участника\n"
    "3 — мат в адрес человека, угрозы, травля, разжигание\n\n"
    "Важно: смотри на КОНТЕКСТ. Если люди дружески подкалывают друг друга — "
    "это 0. Если человек огрызается в ответ на травлю — снижай оценку ему "
    "и отметь зачинщика.\n\n"
    'Ответь СТРОГО в JSON: {"level": 0-3, "reason": "кратко", '
    '"instigator": "ник зачинщика или пусто"}'
)


async def watch_message(text: str, context: str = "") -> dict | None:
    """Оценка сообщения с учётом переписки."""
    if not KEY:
        return None
    q = (f"Переписка:\n{context}\n\nПоследнее сообщение: {text[:600]}"
         if context else text[:600])
    res = await ask(WATCH_PROMPT, q, max_tokens=200)
    if not isinstance(res, dict):
        return None
    try:
        lvl = max(0, min(int(res.get("level", 0)), 3))
    except Exception:
        return None
    return {"level": lvl,
            "reason": str(res.get("reason", ""))[:120],
            "instigator": str(res.get("instigator", ""))[:64]}


# ══════════════════ 3. СВОДКА ПО ЧАТУ ══════════════════
SUMMARY_PROMPT = (
    "Ты аналитик чата. По переписке сделай короткую сводку для владельца.\n"
    'Ответь СТРОГО в JSON: {"mood": "спокойно|оживлённо|напряжённо|конфликт", '
    '"summary": "2-3 предложения о чём говорят", '
    '"problems": "проблемы и кто их создаёт, или пусто", '
    '"advice": "что стоит сделать владельцу, или пусто"}'
)

MOOD_ICON = {"спокойно": "😌", "оживлённо": "🙂",
             "напряжённо": "😬", "конфликт": "🔥"}


async def chat_summary(context: str) -> dict | None:
    if not KEY:
        return None
    res = await ask(SUMMARY_PROMPT, context[:3500], max_tokens=320)
    return res if isinstance(res, dict) else None
