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


# ══════════════════ ПРАВИЛА КЛАНА ══════════════════
# ══════════════════ ПРАВИЛА КЛАНА ══════════════════
CLAN_RULES = """
Обязательные правила игрового клана и беседы:
1. Клановая активность: обязательное участие в запланированных событиях (КВ, Турниры, Кастомки, Съёмки). При невозможности — предупредить за 24 часа.
2. Запрещены читы, софты, багоюз, создание помех и руин игр/съёмок.
3. Общение: вежливость и уважение. Запрещены травля, буллинг, адресные оскорбления и провокация конфликтов.
4. Запрещены спам, реклама сторонних каналов/ботов/ссылок, скам, мошенничество и обман.
5. Запрещены политические и религиозные дискуссии, материалы 18+, деанон и разглашение личных данных.
6. Лестница наказаний:
   • Лёгкие нарушения (капс, флуд, лёгкий оффтоп, мелкая грубость): 1-е — мут 15-60 мин, 2-е — мут 3-6 часов, 3-е — варн.
   • Грубые нарушения (оскорбления, токсичность, мат в адрес игрока, помехи на КВ/съёмках): 1-е — 1 варн, 2-е — 2-й варн, 3-е — мут 12-24 часа.
   • Критические (читы, реклама, спам, скам, 18+, деанон): перманентный бан / кик.
7. Обжалование наказаний доступно в боте @ZRGG_Oblivion_bot.
""".strip()


# ══════════════════ 1. НАДЗОР ЗА НАКАЗАНИЯМИ ══════════════════
REVIEW_PROMPT = (
    "Ты — независимый арбитр русскоязычного игрового клана. "
    "По переписке, причине и предоставленной истории реши, было ли нарушение "
    "и соответствует ли наказание правилам. Не считай обвинение доказанным "
    "только потому, что оно написано в причине.\n\n"
    + CLAN_RULES + "\n\n"
    "Ответь СТРОГО в JSON:\n"
    '{"verdict": "ok|soft|harsh|wrong", "score": 0-10, '
    '"reason": "одно предложение", "advice": "что стоило сделать"}\n\n'
    "ok — наказание справедливо и выдано строго по правилам (зелёный)\n"
    "soft — нарушение было, но наказание слишком мягкое (синий / сомнения)\n"
    "harsh — нарушение было, но наказание слишком суровое (синий / сомнения)\n"
    "wrong — нарушения не доказано или наказание несправедливо (красный / не согласен)\n"
    "При нехватке контекста снижай score; не выдумывай факты."
)

VERDICT_ICON = {"ok": "🟢", "soft": "🔵", "harsh": "🔵", "wrong": "🔴"}
VERDICT_TEXT = {
    "ok": "Правильно выдан (по правилам)",
    "soft": "Есть сомнения (слишком мягко)",
    "harsh": "Есть сомнения (слишком сурово)",
    "wrong": "Не согласен (ошибка / нарушение правил)",
}


async def review_punishment(kind: str, reason: str, seconds: int,
                            target: str, moderator: str,
                            context: str) -> dict | None:
    """Проверяет наказание. -> {verdict, score, reason, advice} или None."""
    if not KEY:
        return None
    from core_resolve import human_period
    if seconds:
        term = human_period(seconds)
    elif kind == "warn":
        term = "без срока"
    elif kind == "kick":
        term = "однократно"
    else:
        term = "бессрочно"
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
    """Красивый текст отчёта с цветной индикацией правильности и ссылкой на бота."""
    icon = VERDICT_ICON.get(r["verdict"], "🔵")
    what = VERDICT_TEXT.get(r["verdict"], r["verdict"])
    out = [
        f"🤖 <b>Экспертиза наказания</b>\n",
        f"{icon} <b>Оценка:</b> {what} (уверенность {r['score']}/10)\n",
        f"⚖️ <b>Тип:</b> {kind} · <b>Срок:</b> {term}",
        f"👤 <b>Кому:</b> {target}",
        f"👮 <b>Выдал:</b> {moderator}\n",
        f"📝 <b>Вердикт:</b> {r['reason']}"
    ]
    if r.get("advice") and r["verdict"] != "ok":
        out.append(f"💡 <b>Рекомендация:</b> {r['advice']}")
    out.append(f"\n📩 <i>Обжаловать наказание:</i> <b>@ZRGG_Oblivion_bot</b>")
    return "\n".join(out)


# ══════════════════ 2. НАБЛЮДЕНИЕ ЗА ЧАТОМ ══════════════════
WATCH_PROMPT = (
    "Ты модератор русскоязычного игрового клана. Проверь ПОСЛЕДНЕЕ сообщение "
    "по КАЖДОМУ правилу, учитывая переписку вокруг него.\n\n"
    + CLAN_RULES + "\n\n"
    "Шкала:\n"
    "0 — нарушения нет;\n"
    "1 — лёгкое: единичный капс/офтоп/грубость/флуд, нужен контекст или "
    "внимание модератора;\n"
    "2 — явное: спам, реклама/сторонняя ссылка, повторный флуд, политическая "
    "или религиозная дискуссия, адресное оскорбление, провокация, помехи;\n"
    "3 — грубое/опасное: угрозы, травля, мошенничество, читы, разглашение "
    "личных данных, материалы 18+.\n\n"
    "Не наказывай цитату правил, жалобу на нарушение, спокойное обжалование, "
    "дружеский подкол или мат без адресата. Не делай вывод о пропуске события "
    "или сроке 24 часа, если этого не доказывает контекст. Если человек "
    "защищается от травли, учитывай зачинщика.\n\n"
    'Ответь СТРОГО в JSON: {"level": 0-3, "category": "правило или норма", '
    '"reason": "кратко", "instigator": "ник зачинщика или пусто"}'
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
            "category": str(res.get("category", ""))[:80],
            "reason": str(res.get("reason", ""))[:120],
            "instigator": str(res.get("instigator", ""))[:64]}


# ══════════════════ 3. СВОДКА ПО ЧАТУ ══════════════════
SUMMARY_PROMPT = (
    "Ты аналитик русскоязычного игрового клана. Проверь переписку по всем "
    "правилам ниже и сделай короткую доказательную сводку для владельца. "
    "Не выдумывай нарушения и отличай обсуждение правила от его нарушения.\n\n"
    + CLAN_RULES + "\n\n"
    'Ответь СТРОГО в JSON: {"mood": "спокойно|оживлённо|напряжённо|конфликт", '
    '"summary": "2-3 предложения о чём говорят", '
    '"problems": "какие правила нарушены и кем, либо пусто", '
    '"advice": "что стоит сделать владельцу по лестнице наказаний, либо пусто"}'
)

MOOD_ICON = {"спокойно": "😌", "оживлённо": "🙂",
             "напряжённо": "😬", "конфликт": "🔥"}


async def chat_summary(context: str) -> dict | None:
    if not KEY:
        return None
    res = await ask(SUMMARY_PROMPT, context[:3500], max_tokens=320)
    return res if isinstance(res, dict) else None
