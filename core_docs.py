"""Генератор справочника на telegra.ph с якорями на каждый раздел.

Кнопка в /команды -> ссылка вида https://telegra.ph/xxx#Раздел -> нужное место.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

import core_storage as storage
from core_registry import (RANK_NAMES, SECTION_EMOJI, SECTIONS, registry_by_section)

API = "https://api.telegra.ph/"
STATE = storage.DATA_DIR / "telegraph.json"


def _api(method: str, **params) -> dict:
    data = urllib.parse.urlencode(
        {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
         for k, v in params.items()}).encode()
    with urllib.request.urlopen(API + method, data, timeout=30) as r:
        return json.load(r)


def anchor_for(title: str) -> str:
    """Telegra.ph делает якорь из текста заголовка: пробелы -> дефисы."""
    return urllib.parse.quote(title.replace(" ", "-"))


SECTION_IMG = {
    **{n: "sec_moderation" for n in (1, 2, 3, 5, 12)},
    **{n: "sec_settings" for n in (4, 6, 7, 10, 11, 26, 28, 32)},
    **{n: "sec_economy" for n in (13, 27, 31)},
    **{n: "sec_games" for n in (14, 15, 16)},
    **{n: "sec_social" for n in (8, 9, 17, 18, 19, 20, 21, 22, 23, 24, 25, 30)},
}


def _images() -> dict:
    f = storage.DATA_DIR / "images.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return {}


def build_content() -> tuple[list, dict[int, str]]:
    """-> (content для telegra.ph, {номер_раздела: якорь})"""
    by_sec = registry_by_section()
    content: list = []
    anchors: dict[int, str] = {}
    imgs = _images()

    if imgs.get("banner_main"):
        content.append({"tag": "figure", "children": [
            {"tag": "img", "attrs": {"src": imgs["banner_main"]}}]})

    content.append({"tag": "p", "children": [
        "Полный список команд бота. Все команды работают с префиксами ",
        {"tag": "code", "children": ["!"]}, " ",
        {"tag": "code", "children": ["."]}, " ",
        {"tag": "code", "children": ["/"]}, " ",
        {"tag": "code", "children": ["Ирис"]},
        " и, в большинстве случаев, вообще без префикса.",
    ]})
    content.append({"tag": "p", "children": [
        {"tag": "b", "children": ["Обозначения: "]},
        "{ссылка} — реплай, @ник или id · {период} — например «2 часа», «30 минут», «7 дней»",
    ]})

    # Оглавление со ссылками-якорями
    toc_items = []
    for num in sorted(SECTIONS):
        if num not in by_sec:
            continue
        title = f"{num}. {SECTIONS[num]}"
        anchors[num] = anchor_for(title)
        toc_items.append({"tag": "li", "children": [
            {"tag": "a", "attrs": {"href": f"#{anchors[num]}"},
             "children": [f"{SECTION_EMOJI.get(num,'•')} {title}"]}]})
    content.append({"tag": "h3", "children": ["Оглавление"]})
    content.append({"tag": "ul", "children": toc_items})

    # Разделы
    for num in sorted(SECTIONS):
        cmds = by_sec.get(num)
        if not cmds:
            continue
        title = f"{num}. {SECTIONS[num]}"
        content.append({"tag": "h3", "children": [title]})
        key = SECTION_IMG.get(num)
        if key and imgs.get(key):
            content.append({"tag": "figure", "children": [
                {"tag": "img", "attrs": {"src": imgs[key]}}]})
        items = []
        for c in cmds:
            line: list = [{"tag": "code", "children": [c.usage]}]
            if c.desc:
                line.append(f" — {c.desc}")
            if c.rank:
                line.append({"tag": "i", "children": [
                    f"  [нужен ранг {c.rank}: {RANK_NAMES.get(c.rank,'')}]"]})
            if len(c.names) > 1:
                line.append({"tag": "br"})
                line.append({"tag": "i", "children": [
                    "синонимы: " + ", ".join(c.names[1:10])]})
            items.append({"tag": "li", "children": line})
        content.append({"tag": "ul", "children": items})
        content.append({"tag": "p", "children": [
            {"tag": "a", "attrs": {"href": "#Оглавление"}, "children": ["↑ к оглавлению"]}]})

    return content, anchors


def build_pages(max_bytes: int = 40000) -> list[tuple[str, list, dict[int, str]]]:
    """Разбивает справку на несколько страниц, чтобы влезть в лимит telegra.ph."""
    import json as _json
    by_sec = registry_by_section()
    imgs = _images()
    nums = [n for n in sorted(SECTIONS) if by_sec.get(n)]

    def sec_blocks(num: int) -> tuple[list, str]:
        title = f"{num}. {SECTIONS[num]}"
        blocks: list = [{"tag": "h3", "children": [title]}]
        key = SECTION_IMG.get(num)
        if key and imgs.get(key):
            blocks.append({"tag": "figure", "children": [
                {"tag": "img", "attrs": {"src": imgs[key]}}]})
        items = []
        for c in by_sec[num]:
            line: list = [{"tag": "code", "children": [c.usage]}]
            if c.desc:
                line.append(f" — {c.desc}")
            if c.rank:
                line.append({"tag": "i", "children": [
                    f"  [ранг {c.rank}: {RANK_NAMES.get(c.rank,'')}]"]})
            if len(c.names) > 1:
                line.append({"tag": "br"})
                line.append({"tag": "i", "children": [
                    "синонимы: " + ", ".join(c.names[1:10])]})
            items.append({"tag": "li", "children": line})
        blocks.append({"tag": "ul", "children": items})
        return blocks, anchor_for(title)

    pages: list[tuple[str, list, dict[int, str]]] = []
    cur: list = []
    cur_anchors: dict[int, str] = {}
    part = 1

    for num in nums:
        blocks, anc = sec_blocks(num)
        probe = cur + blocks
        if cur and len(_json.dumps(probe, ensure_ascii=False).encode()) > max_bytes:
            pages.append((f"📖 ZRGOblivion — команды, часть {part}", cur, cur_anchors))
            part += 1
            cur, cur_anchors = [], {}
        cur.extend(blocks)
        cur_anchors[num] = anc
    if cur:
        pages.append((f"📖 ZRGOblivion — команды, часть {part}", cur, cur_anchors))
    return pages


def publish(title: str = "📖 ZRGOblivion — команды") -> dict:
    """Создаёт/обновляет страницу. Возвращает {'url':..., 'anchors': {...}}."""
    STATE.parent.mkdir(parents=True, exist_ok=True)
    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text())
        except Exception:
            state = {}

    token = state.get("token")
    if not token:
        acc = _api("createAccount", short_name="ZRGOblivion", author_name="ZRGOblivion")
        token = acc["result"]["access_token"]
        state["token"] = token

    pages = build_pages()
    paths = state.get("paths") or []
    urls: list[str] = []
    anchors: dict[int, str] = {}
    page_of: dict[int, int] = {}

    for i, (ptitle, content, panchors) in enumerate(pages):
        head = [{"tag": "p", "children": [
            "Полный список команд. Работают префиксы ",
            {"tag": "code", "children": ["!"]}, " ",
            {"tag": "code", "children": ["."]}, " ",
            {"tag": "code", "children": ["/"]}, " ",
            {"tag": "code", "children": ["Ирис"]},
            " и без префикса. {ссылка} — реплай, @ник или id.",
        ]}]
        body = head + content
        res = None
        if i < len(paths):
            try:
                res = _api("editPage", access_token=token, path=paths[i],
                           title=ptitle, content=body, return_content="false")
            except Exception:
                res = None
        if not res or "result" not in res:
            res = _api("createPage", access_token=token, title=ptitle,
                       content=body, return_content="false")
        if "result" not in res:
            raise RuntimeError(res.get("error", "telegraph error"))
        url = res["result"]["url"]
        urls.append(url)
        if i < len(paths):
            paths[i] = res["result"]["path"]
        else:
            paths.append(res["result"]["path"])
        for num, anc in panchors.items():
            anchors[num] = anc
            page_of[num] = i

    state["paths"] = paths
    state["urls"] = urls
    state["url"] = urls[0] if urls else ""
    state["anchors"] = anchors
    state["page_of"] = page_of
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    return state


def cached() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {}


def section_url(num: int) -> str:
    st = cached()
    urls = st.get("urls") or ([st["url"]] if st.get("url") else [])
    if not urls:
        return ""
    page_of = st.get("page_of") or {}
    idx = page_of.get(str(num), page_of.get(num, 0))
    try:
        url = urls[int(idx)]
    except (IndexError, ValueError, TypeError):
        url = urls[0]
    anc = (st.get("anchors") or {}).get(str(num)) or (st.get("anchors") or {}).get(num)
    return f"{url}#{anc}" if anc else url


def all_urls() -> list[str]:
    st = cached()
    return st.get("urls") or ([st["url"]] if st.get("url") else [])
