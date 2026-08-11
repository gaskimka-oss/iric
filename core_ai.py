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
CLAN_RULES = """
Обязательные правила игрового клана:
1. Участники участвуют в запланированных клановых событиях (сражениях,
   турнирах, кастомках, съёмках) либо предупреждают администрацию о
   невозможности участия минимум за 24 часа.
2. Запрещены читы, эксплуатация багов и умышленное создание помех другим
   игрокам на мероприятиях, в играх и при съёмках.
3. Общение должно быть вежливым и уважительным.
4. Запрещены спам, реклама и ссылки на сторонние ресурсы.
5. Запрещены адресные оскорбления, травля и намеренная провокация конфликта.
6. Запрещены мошенничество и обман участников.
7. Запрещено разглашать личную информацию; подозрительную активность нужно
   передавать администрации.
8. Запрещены политические и религиозные дискуссии, материалы 18+,
   злоупотребление КАПСОМ, офтоп, флуд и многочисленные повторы сообщений.
9. Администрация вправе удалять сообщения; её решения можно обжаловать через
   бота, но само спокойное несогласие без оскорблений не является нарушением.

Лестница наказаний из правил:
• грубые нарушения: первый случай — 1 предупреждение, второй — ещё 1
  предупреждение, третий — мут на 12 часов;
• лёгкие нарушения: первый случай — мут 15–60 минут, второй — мут 3–6 часов,
  третий — предупреждение.
Учитывай ступень только если в данных действительно дана история нарушений.
Не выдумывай прошлые проступки, намерения, факт кланового события или
непредупреждения за 24 часа. Мат «в воздух», дружеский подкол и предметный
спор без перехода на личности сами по себе не запрещены.
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
    "ok — наказание справедливо и соразмерно\n"
    "soft — нарушение было, но наказание слишком мягкое\n"
    "harsh — нарушение было, но наказание слишком суровое\n"
    "wrong — нарушения не доказано или наказание несправедливо\n"
    "При нехватке контекста снижай score; не выдумывай факты."
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
