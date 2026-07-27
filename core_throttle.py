"""Антифлуд: защита бота от перегрузки в больших чатах."""
from __future__ import annotations

import time
from collections import defaultdict

# user_id -> список меток времени команд
_hits: dict[int, list[float]] = defaultdict(list)
_warned: dict[int, float] = {}

LIMIT = 5          # команд
WINDOW = 6.0       # за столько секунд
COOLDOWN = 10.0    # молчать столько после срабатывания


def check(user_id: int) -> bool:
    """True — можно выполнять, False — флуд."""
    now = time.monotonic()
    hits = _hits[user_id]
    # оставляем только свежие
    hits[:] = [t for t in hits if now - t < WINDOW]
    if len(hits) >= LIMIT:
        return False
    hits.append(now)
    return True


def should_warn(user_id: int) -> bool:
    """Предупреждать не чаще раза в COOLDOWN секунд."""
    now = time.monotonic()
    if now - _warned.get(user_id, 0) > COOLDOWN:
        _warned[user_id] = now
        return True
    return False


def cleanup() -> None:
    """Периодическая чистка, чтобы словарь не рос."""
    now = time.monotonic()
    for uid in list(_hits):
        if not _hits[uid] or now - _hits[uid][-1] > 300:
            _hits.pop(uid, None)
    for uid in list(_warned):
        if now - _warned[uid] > 300:
            _warned.pop(uid, None)
