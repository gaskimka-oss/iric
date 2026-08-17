"""Собирает однофайловый bot.py для заливки на хостинг (Bothost).

Берёт исходники из корня репозитория (все *.py, кроме упакованного bot.py),
entrypoint = bot_source.py (внутрь пакета пишется как bot.py), плюс картинки
и rp_images.zip. Результат — новый упакованный bot.py в корне.

Запуск:  python tools/build_single.py
"""
from __future__ import annotations

import base64
import io
import sys
import textwrap
import uuid
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "bot.py"

# файлы верхнего уровня, которые попадают в пакет
SKIP = {"bot.py"}            # сам пакет не пакуем
EXCLUDE_PREFIXES = ("bot_source",)


def collect_files() -> dict[str, bytes]:
    """имя-в-пакете -> содержимое"""
    out: dict[str, bytes] = {}

    entry = ROOT / "bot_source.py"
    if not entry.is_file():
        raise SystemExit("❌ Не найден bot_source.py — точка входа")
    out["bot.py"] = entry.read_bytes()

    for p in sorted(ROOT.glob("*.py")):
        if p.name in SKIP or any(p.name.startswith(x) for x in EXCLUDE_PREFIXES):
            continue
        out[p.name] = p.read_bytes()

    for p in sorted(ROOT.glob("img_*.jpg")):
        out[p.name] = p.read_bytes()
    if (ROOT / "staff_example.txt").is_file():
        out["staff_example.txt"] = (ROOT / "staff_example.txt").read_bytes()

    # rp-картинки — одним архивом, как было в исходной сборке
    rp_dir = ROOT / "rp_images"
    images = sorted(p for p in rp_dir.glob("*") if p.is_file())
    if images:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for img in images:
                z.writestr(img.name, img.read_bytes())
        out["rp_images.zip"] = buf.getvalue()
    return out


TEMPLATE = '''#!/usr/bin/env python3
"""IRIC single-file deployment for Bothost.

Upload this ONE file as bot.py over the existing bot.py. It contains the full
updated application and all {images_count} RP images; no folders need to be uploaded.
Generated: {today}. Payload: {version}.
"""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path
import runpy
import shutil
import sys
import zipfile

_VERSION = "{version}"
_PAYLOAD = r"""
{payload}
"""


def _install() -> Path:
    root = Path(os.getenv("IRIC_RUNTIME_DIR", "/tmp")) / ("iric-" + _VERSION)
    marker = root / ".ready"
    if marker.is_file() and (root / "bot.py").is_file():
        return root

    temp = root.with_name(root.name + ".new")
    shutil.rmtree(temp, ignore_errors=True)
    temp.mkdir(parents=True, exist_ok=True)
    packed = base64.b85decode("".join(_PAYLOAD.split()).encode("ascii"))
    with zipfile.ZipFile(io.BytesIO(packed)) as archive:
        archive.extractall(temp)
    marker_tmp = temp / ".ready"
    marker_tmp.write_text(_VERSION, encoding="ascii")
    shutil.rmtree(root, ignore_errors=True)
    temp.replace(root)
    return root


_RUNTIME = _install()
if os.getenv("IRIC_EXTRACT_ONLY") == "1":
    print(_RUNTIME)
else:
    sys.path.insert(0, str(_RUNTIME))
    runpy.run_path(str(_RUNTIME / "bot.py"), run_name="__main__")
'''


def build() -> None:
    files = collect_files()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as z:
        for name, data in files.items():
            z.writestr(name, data)
    payload = base64.b85encode(buf.getvalue()).decode("ascii")
    payload = "\n".join(textwrap.wrap(payload, 100))
    version = uuid.uuid4().hex[:16]
    images = sorted((ROOT / "rp_images").glob("rp_*.jpg"))
    OUT.write_text(TEMPLATE.format(payload=payload, version=version,
                                   today=date.today().isoformat(),
                                   images_count=len(images)),
                   encoding="ascii")
    print(f"✅ Собран {OUT} ({OUT.stat().st_size:,} байт, payload {version})")
    print(f"   файлов внутри: {len(files)}")
    for name in files:
        print("   •", name)


if __name__ == "__main__":
    build()
    sys.exit(0)
