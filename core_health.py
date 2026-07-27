"""Мини-HTTP-сервер для healthcheck хостинга.

Некоторые хостинги убивают контейнер (SIGTERM), если приложение не слушает
порт из переменной PORT. Отвечаем 200 OK на любой запрос — без зависимостей.
"""
from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger("irisbot.health")

BODY = b"ok"
RESPONSE = (b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"Content-Length: " + str(len(BODY)).encode() + b"\r\n"
            b"Connection: close\r\n\r\n" + BODY)


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        try:
            await asyncio.wait_for(reader.read(1024), timeout=3)
        except asyncio.TimeoutError:
            pass
        writer.write(RESPONSE)
        await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def start() -> asyncio.AbstractServer | None:
    raw = os.getenv("PORT") or os.getenv("HTTP_PORT") or "8080"
    try:
        port = int(str(raw).strip())
    except ValueError:
        port = 8080
    try:
        server = await asyncio.start_server(_handle, "0.0.0.0", port)
        log.info("healthcheck слушает порт %d", port)
        return server
    except Exception as e:
        log.warning("healthcheck не запущен (%s)", e)
        return None
