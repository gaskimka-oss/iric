"""Генератор карточек для РП-команд (не требуется на хостинге).

Иконки: Twemoji, CC-BY 4.0, https://github.com/jdecked/twemoji
Карточки сохраняются как оптимизированные JPEG и поставляются вместе с ботом.
"""
from __future__ import annotations

import ast
import colorsys
import hashlib
import random
import subprocess
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "h_rp.py"
OUT = ROOT / "rp_images"
CACHE = ROOT / "tools" / ".twemoji"
W, H = 960, 540


def read_actions() -> list[tuple[str, tuple[str, str]]]:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.AnnAssign)
                and getattr(node.target, "id", "") == "ACTIONS"):
            return list(ast.literal_eval(node.value).items())
    raise RuntimeError("ACTIONS не найден")


def emoji_code(emoji: str) -> str:
    # Twemoji не включает variation selector FE0F в имени обычной иконки.
    return "-".join(f"{ord(c):x}" for c in emoji if ord(c) != 0xFE0F)


def twemoji(emoji: str) -> Image.Image | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    code = emoji_code(emoji)
    svg = CACHE / f"{code}.svg"
    png = CACHE / f"{code}.png"
    try:
        if not svg.exists():
            url = ("https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/"
                   f"assets/svg/{code}.svg")
            urllib.request.urlretrieve(url, svg)
        if not png.exists():
            subprocess.run([
                "convert", "-density", "600", "-background", "none", str(svg),
                "-resize", "300x300", str(png),
            ], check=True, capture_output=True)
        return Image.open(png).convert("RGBA")
    except Exception as exc:
        print(f"warning: {emoji} ({code}): {exc}")
        return None


def palette(name: str, category: int) -> tuple[tuple[int, int, int], ...]:
    seed = int(hashlib.sha256(name.encode()).hexdigest()[:12], 16)
    hue = ((seed % 360) / 360 + (0.03, 0.46, 0.12, 0.65)[category]) % 1
    a = colorsys.hsv_to_rgb(hue, 0.69, 0.31)
    b = colorsys.hsv_to_rgb((hue + 0.12) % 1, 0.76, 0.66)
    c = colorsys.hsv_to_rgb((hue + 0.50) % 1, 0.54, 0.97)
    conv = lambda rgb: tuple(int(x * 255) for x in rgb)
    return conv(a), conv(b), conv(c)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    return ImageFont.truetype(path, size)


def fit_font(text: str, maximum: int = 63, minimum: int = 34) -> ImageFont.FreeTypeFont:
    for size in range(maximum, minimum - 1, -1):
        f = font(size, True)
        if f.getlength(text.upper()) <= 515:
            return f
    return font(minimum, True)


def make_card(index: int, action: str, emoji: str, category: int) -> Image.Image:
    dark, mid, accent = palette(action, category)
    small = Image.new("RGB", (240, 135), dark)
    px = small.load()
    # Двухмерный диагональный градиент строится в четверть размера.
    for y in range(135):
        for x in range(240):
            t = min(1, max(0, (x / 240) * 0.78 + (1 - y / 135) * 0.22))
            wave = 0.08 * ((x + y + index * 17) % 113) / 113
            px[x, y] = tuple(
                min(255, int(dark[k] * (1 - t) + mid[k] * t
                             + accent[k] * wave))
                for k in range(3))
    im = small.resize((W, H), Image.Resampling.BICUBIC)

    # Мягкие уникальные световые пятна.
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    rng = random.Random(index * 1009 + len(action))
    for _ in range(8):
        r = rng.randint(55, 170)
        x = rng.randint(-r, W + r)
        y = rng.randint(-r, H + r)
        alpha = rng.randint(12, 35)
        gd.ellipse((x-r, y-r, x+r, y+r), fill=(*accent, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(35))
    im = Image.alpha_composite(im.convert("RGBA"), glow)

    d = ImageDraw.Draw(im, "RGBA")
    # Стеклянная панель текста.
    d.rounded_rectangle((48, 54, 620, 486), radius=34,
                        fill=(8, 11, 25, 145), outline=(255, 255, 255, 38), width=2)
    d.rounded_rectangle((650, 86, 910, 454), radius=58,
                        fill=(255, 255, 255, 22), outline=(*accent, 115), width=3)

    labels = ("ТЁПЛОЕ ДЕЙСТВИЕ", "ИГРОВОЙ ХАОС", "ЗАБОТА И БЫТ", "МИР ПРИКЛЮЧЕНИЙ")
    d.text((86, 92), f"RP ACTION  •  {index:02d}", font=font(19, True),
           fill=(*accent, 235))
    d.text((86, 134), labels[category], font=font(17, True),
           fill=(255, 255, 255, 145))

    title = action.upper()
    tf = fit_font(title)
    # Для длинных названий переносим по словам.
    words = title.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        probe = (cur + " " + word).strip()
        if tf.getlength(probe) > 490 and cur:
            lines.append(cur)
            cur = word
        else:
            cur = probe
    if cur:
        lines.append(cur)
    line_h = tf.size + 9
    start_y = 246 - (len(lines) * line_h) // 2
    for n, line in enumerate(lines[:3]):
        d.text((84, start_y + n * line_h), line, font=tf,
               fill=(255, 255, 255, 248), stroke_width=1,
               stroke_fill=(0, 0, 0, 55))

    d.line((86, 405, 566, 405), fill=(255, 255, 255, 45), width=2)
    d.text((86, 426), "ZRG OBLIVION  •  ROLE PLAY", font=font(16, True),
           fill=(255, 255, 255, 125))

    icon = twemoji(emoji)
    if icon:
        icon.thumbnail((225, 225), Image.Resampling.LANCZOS)
        shadow = Image.new("RGBA", icon.size, (0, 0, 0, 0))
        shadow.alpha_composite(icon)
        alpha = shadow.getchannel("A").filter(ImageFilter.GaussianBlur(15))
        black = Image.new("RGBA", icon.size, (0, 0, 0, 150))
        black.putalpha(alpha)
        ix = 780 - icon.width // 2
        iy = 270 - icon.height // 2
        im.alpha_composite(black, (ix + 8, iy + 14))
        im.alpha_composite(icon, (ix, iy))
    else:
        d.ellipse((705, 170, 855, 320), fill=(*accent, 180))

    # Номер-композиционный штрих делает каждую карточку визуально уникальной.
    d.text((878, 478), f"{index:02d}", font=font(24, True),
           anchor="ra", fill=(255, 255, 255, 80))
    return im.convert("RGB")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    actions = read_actions()
    for i, (action, (emoji, _verb)) in enumerate(actions, 1):
        category = 0 if i <= 23 else 1 if i <= 40 else 2 if i <= 54 else 3
        card = make_card(i, action, emoji, category)
        path = OUT / f"rp_{i:02d}.jpg"
        card.save(path, "JPEG", quality=86, optimize=True, progressive=True)
        print(path.relative_to(ROOT))
    (OUT / "ATTRIBUTION.txt").write_text(
        "Emoji graphics: Twemoji by Twitter contributors, licensed under "
        "CC-BY 4.0.\nhttps://github.com/jdecked/twemoji\n",
        encoding="utf-8")


if __name__ == "__main__":
    main()
