"""Расшифровка голосовых и кружков в текст.

Работает через Whisper-совместимый API. Поддерживаются:
  • Groq        — БЕСПЛАТНО, ключ вида gsk_...   (рекомендуется)
  • OpenAI      — платно, ключ sk-...
  • свой сервер — любой, совместимый с /audio/transcriptions

Ключ берётся из STT_API_KEY, а если её нет — из AI_API_KEY
(когда он подходит по формату). Без ключа расшифровка молча
выключена, бот работает как раньше.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request
import uuid

log = logging.getLogger("irisbot.stt")

# ── ключ и адрес ────────────────────────────────────────────────────
_STT_KEY = (os.getenv("STT_API_KEY") or "").strip()
_AI_KEY = (os.getenv("AI_API_KEY") or "").strip()

# ключ OpenRouter (sk-or-) для аудио не годится — на бесплатном тарифе
# аудио недоступно, поэтому берём его только если это Groq или OpenAI
KEY = _STT_KEY or (_AI_KEY if _AI_KEY.startswith(("gsk_", "sk-proj-"))
                   or (_AI_KEY.startswith("sk-") and not _AI_KEY.startswith("sk-or-"))
                   else "")


def _guess_url() -> tuple[str, str]:
    """Адрес и модель по виду ключа."""
    if KEY.startswith("gsk_"):
        return ("https://api.groq.com/openai/v1/audio/transcriptions",
                "whisper-large-v3-turbo")
    return ("https://api.openai.com/v1/audio/transcriptions", "whisper-1")


_URL_GUESS, _MODEL_GUESS = _guess_url()
URL = (os.getenv("STT_API_URL") or _URL_GUESS).strip()
MODEL = (os.getenv("STT_MODEL") or _MODEL_GUESS).strip()

# ограничения, чтобы не жечь лимиты и не тормозить чат
MAX_SECONDS = int(os.getenv("STT_MAX_SECONDS", "300") or 300)
MAX_BYTES = int(os.getenv("STT_MAX_BYTES", "20000000") or 20_000_000)
TIMEOUT = int(os.getenv("STT_TIMEOUT", "90") or 90)


def available() -> bool:
    return bool(KEY)


def provider() -> str:
    u = URL.lower()
    if "groq" in u:
        return "Groq Whisper"
    if "openai" in u:
        return "OpenAI Whisper"
    return "свой сервер"


# ── multipart-запрос без внешних библиотек ──────────────────────────
def _post_audio(audio: bytes, filename: str = "voice.ogg") -> str | None:
    if not KEY:
        return None
    boundary = "----iris" + uuid.uuid4().hex
    nl = b"\r\n"
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        parts.append(b"--" + boundary.encode() + nl)
        parts.append(f'Content-Disposition: form-data; name="{name}"'
                     .encode() + nl + nl)
        parts.append(value.encode() + nl)

    field("model", MODEL)
    field("response_format", "json")
    # язык не фиксируем: Whisper сам определит русский/казахский/английский
    field("temperature", "0")

    parts.append(b"--" + boundary.encode() + nl)
    parts.append(f'Content-Disposition: form-data; name="file"; '
                 f'filename="{filename}"'.encode() + nl)
    parts.append(b"Content-Type: application/octet-stream" + nl + nl)
    parts.append(audio + nl)
    parts.append(b"--" + boundary.encode() + b"--" + nl)
    body = b"".join(parts)

    req = urllib.request.Request(
        URL, body,
        {"Authorization": f"Bearer {KEY}",
         "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.load(r)
        text = (data.get("text") or "").strip()
        return text or None
    except Exception as e:
        log.warning("расшифровка не удалась: %s", str(e)[:200])
        return None


async def transcribe(audio: bytes, filename: str = "voice.ogg") -> str | None:
    """Голосовое -> текст. None, если не вышло."""
    if not KEY or not audio or len(audio) > MAX_BYTES:
        return None
    try:
        return await asyncio.to_thread(_post_audio, audio, filename)
    except Exception:
        return None


def status() -> str:
    """Текст для команды «расшифровка»."""
    if not available():
        return (
            "🎙 <b>Расшифровка голосовых</b>\n\n"
            "Состояние: <b>🔴 не подключена</b>\n\n"
            "Бот может слушать голосовые и кружочки и присылать "
            "текст того, что было сказано.\n\n"
            "<b>Как включить (бесплатно):</b>\n"
            "1. Зайдите на <code>console.groq.com</code>\n"
            "2. Войдите через Google\n"
            "3. API Keys → Create API Key → скопируйте\n"
            "4. На хостинге добавьте переменную:\n"
            "   <code>STT_API_KEY</code> = ваш ключ (gsk_...)\n"
            "5. Перезапустите бота\n\n"
            "<i>У Groq распознавание речи бесплатное.</i>")
    return (
        f"🎙 <b>Расшифровка голосовых</b>\n\n"
        f"Состояние: <b>🟢 работает</b>\n"
        f"Сервис: <b>{provider()}</b>\n"
        f"Модель: <code>{MODEL}</code>\n"
        f"Лимит длины: <b>{MAX_SECONDS // 60} мин</b>\n\n"
        f"Бот слушает голосовые и кружочки и присылает текст.\n"
        f"Сами сообщения остаются на месте.\n\n"
        f"<code>расшифровка выкл</code> — отключить в этом чате")
