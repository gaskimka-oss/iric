"""Выбор каталога для базы: ищем место, которое переживает перезапуск.

На хостингах папка приложения (/app) чаще всего пересоздаётся при каждом
деплое, а «постоянное»/«общее» хранилище монтируется в отдельный путь
(/data, /storage, /mnt/data …). Модуль сам перебирает кандидатов, выбирает
лучший и оставляет метку, по которой на следующем запуске видно —
пережил каталог перезапуск или нет.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

DB_NAME = "iris.db"
MARKER = ".iris_storage.json"

BASE_DIR = Path(__file__).resolve().parent

# Порядок важен: сначала пути, которые на хостингах обычно смонтированы
# как постоянный диск, потом уже папка самого приложения.
_ENV_KEYS = ("DB_DIR", "STORAGE_DIR", "PERSIST_DIR", "VOLUME_PATH", "DATA_DIR")
# Порядок важен — первым идёт то, что реально монтируется хостингом.
# У Bothost постоянное хранилище это /app/data: папка исключена из Git
# и переживает пересборку контейнера (подтверждено их документацией).
_FIXED = (
    "/app/data",
    "/data", "/storage", "/persist", "/persistent",
    "/mnt/data", "/mnt/storage", "/mnt/volume", "/var/data",
    "/app/storage", "/home/data",
)


def _candidates() -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: str | os.PathLike | None) -> None:
        if not p:
            return
        try:
            q = Path(p).expanduser()
        except Exception:
            return
        k = str(q)
        if k not in seen:
            seen.add(k)
            out.append(q)

    for k in _ENV_KEYS:
        add(os.getenv(k))
    for p in _FIXED:
        add(p)
    add(BASE_DIR / "data")
    return out


def _writable(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".iris_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def _read_marker(p: Path) -> dict:
    try:
        return json.loads((p / MARKER).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_marker(p: Path, mk: dict) -> dict:
    mk = {
        "boots": int(mk.get("boots", 0)) + 1,
        "first_seen": mk.get("first_seen") or int(time.time()),
        "last_boot": int(time.time()),
    }
    try:
        (p / MARKER).write_text(json.dumps(mk, ensure_ascii=False),
                                encoding="utf-8")
    except Exception:
        pass
    return mk


def _score(p: Path, mk: dict) -> tuple:
    """Чем больше — тем надёжнее папка.

    Главный признак — метка пережила предыдущий запуск: значит хостинг
    эту папку не стирает. Дальше смотрим, сколько запусков она пережила
    и лежит ли там база.
    """
    db = p / DB_NAME
    has_db = 1 if db.exists() and db.stat().st_size > 0 else 0
    survived = 1 if mk.get("boots", 0) >= 1 else 0
    boots = int(mk.get("boots", 0))
    # /app/data — штатное постоянное хранилище Bothost, ему приоритет
    preferred = 1 if str(p) in ("/app/data", os.getenv("DATA_DIR", "")) else 0
    return (survived, boots, has_db, preferred)


def choose() -> tuple[Path, dict]:
    cands = [p for p in _candidates() if _writable(p)]
    if not cands:
        p = BASE_DIR / "data"
        p.mkdir(parents=True, exist_ok=True)
        cands = [p]

    # метки читаем ДО записи, иначе все папки будут выглядеть «пережившими»
    before = {p: _read_marker(p) for p in cands}
    # и ставим метку в каждую: на следующем запуске будет видно,
    # какие папки хостинг стирает, а какие нет
    after = {p: _write_marker(p, before[p]) for p in cands}

    best = max(cands, key=lambda p: _score(p, before[p]))

    # если база лежит в другой доступной папке, а в выбранной её нет —
    # переносим, чтобы ничего не потерять
    if not (best / DB_NAME).exists():
        for p in sorted(cands, key=lambda q: _score(q, before[q]), reverse=True):
            src = p / DB_NAME
            if p != best and src.exists() and src.stat().st_size > 0:
                try:
                    shutil.copy2(src, best / DB_NAME)
                    for suf in ("-wal", "-shm"):
                        s2 = Path(str(src) + suf)
                        if s2.exists():
                            shutil.copy2(s2, Path(str(best / DB_NAME) + suf))
                except Exception:
                    pass
                break

    mk = before[best]
    info = {
        "dir": str(best),
        "persistent": bool(mk.get("boots")),   # папка была и до этого запуска
        "boots": int(after[best]["boots"]),
        "first_seen": after[best]["first_seen"],
        "last_boot": after[best]["last_boot"],
        "db_existed": (best / DB_NAME).exists(),
        "candidates": [str(p) for p in cands],
    }
    return best, info


DATA_DIR, INFO = choose()
DB_FILE = DATA_DIR / DB_NAME


def report() -> str:
    """Человеческий отчёт для команды «хранилище»."""
    size = 0
    try:
        size = DB_FILE.stat().st_size
    except Exception:
        pass
    ok = "✅ данные сохраняются" if INFO["persistent"] else "⚠️ данные могут стираться"
    return (
        f"🗄 <b>Хранилище</b>\n\n"
        f"Папка: <code>{INFO['dir']}</code>\n"
        f"База: <code>{DB_FILE.name}</code> ({size / 1024:.0f} КБ)\n"
        f"Запусков с этой папкой: <b>{INFO['boots']}</b>\n"
        f"База была на месте при старте: "
        f"<b>{'да' if INFO['db_existed'] else 'нет'}</b>\n"
        f"Итог: {ok}"
    )
