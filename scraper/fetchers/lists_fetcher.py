"""Обход конкурсных списков epk25: уровень → подразделение → направление → view.

Извлечение ссылок — чистые функции (тестируемы без сети). Сетевой обход — тонкий
слой на requests (honors HTTPS_PROXY), с вежливой паузой и ретраями.
"""
import re
import time
from html import unescape
from typing import Dict, List

BASE = "https://epk25.mpgu.su"
LEVELS = ["basic_higher_education", "specialist", "specialized_higher_education",
          "magistracy", "secondary_vocational_education"]

_UA = {"User-Agent": "MPGU-Abitur-Bot/1.0 (+https://mpgu.su)"}


def structural_url(level: str) -> str:
    return f"{BASE}/competitive-list/structural?educationLevel={level}"


def extract_direction_links(html: str) -> List[str]:
    hrefs = re.findall(r'href="(/competitive-list/direction\?[^"]*)"', html or "")
    return [BASE + unescape(h) for h in hrefs]


def extract_view_codes(html: str) -> List[str]:
    codes = re.findall(r'/competitive-list/view\?code=([0-9]+)', html or "")
    seen, out = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


def extract_view_links(html: str) -> List[tuple]:
    """[(code, title)] — код списка и текст ссылки (название направления)."""
    pairs = re.findall(
        r'<a[^>]*href="[^"]*/competitive-list/view\?code=([0-9]+)"[^>]*>(.*?)</a>',
        html or "", re.S | re.I)
    seen, out = set(), []
    for code, raw in pairs:
        if code in seen:
            continue
        seen.add(code)
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", unescape(raw))).strip()
        out.append((code, title))
    return out


def extract_view_entries(html: str) -> List[dict]:
    """[{code, direction, form, kind}] из карточек direction-страницы epk25.

    Структура: article.landing-competitive-direction__card → __head (направление),
    строки таблицы (форма обучения), ссылки-pills (Бюджет / Платные места).
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "lxml")
    out, seen = [], set()
    for card in soup.select("article.landing-competitive-direction__card"):
        head = card.select_one(".landing-competitive-direction__head")
        direction = re.sub(r"\s+", " ", head.get_text(" ", strip=True)) if head else ""
        for tr in card.select("tbody tr"):
            form_td = tr.select_one(".landing-competitive-direction__form")
            form_txt = (form_td.get_text(" ", strip=True) if form_td else "").lower()
            if "очно-заочная" in form_txt:
                form = "очно-заочная"
            elif "заочная" in form_txt:
                form = "заочная"
            else:
                form = "очная"
            for a in tr.select("a[href*='view?code=']"):
                m = re.search(r"code=([0-9]+)", a.get("href") or "")
                if not m or m.group(1) in seen:
                    continue
                seen.add(m.group(1))
                kind = "бюджет" if "бюджет" in a.get_text().lower() else "платное"
                out.append({"code": m.group(1), "direction": direction,
                            "form": form, "kind": kind})
    return out


def _get(url: str, retries: int = 3) -> str:
    import requests
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=_UA, timeout=30)
            if r.status_code == 200:
                return r.text
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def crawl(levels: List[str] = None, pause: float = 0.3, max_workers: int = None):
    """Возвращает (pages, meta, stats).

    pages: {code -> html}; meta: {code -> {direction, level, form, kind}};
    stats: сведения о полноте обхода для защиты от публикации неполного индекса
    (пропущенный из-за сетевого сбоя уровень/направление = молчаливая потеря данных).

    Два прохода: сначала уровни/направления — их немного, собираем последовательно
    с вежливой паузой, чтобы получить полный список кодов списков. Затем сами
    списки (view?code=...) — их сотни, и время между первым и последним снятым
    списком напрямую портит консистентность снимка (согласия успевают сдвинуться),
    поэтому их бьём все разом через пул потоков, а не по одному.

    Сеть; в тестах не вызывается напрямую (см. monkeypatch _get в тестах).
    """
    levels = levels or LEVELS
    pages: Dict[str, str] = {}
    meta: Dict[str, dict] = {}
    stats = {"levels_failed": [], "directions_total": 0, "directions_failed": 0,
             "views_total": 0, "views_failed": 0}

    entries: Dict[str, dict] = {}  # code -> {direction, level, form, kind}
    for lvl in levels:
        try:
            struct = _get(structural_url(lvl))
        except Exception:
            stats["levels_failed"].append(lvl)  # весь уровень не прочитан — критично
            continue
        for dir_url in extract_direction_links(struct):
            stats["directions_total"] += 1
            time.sleep(pause)
            try:
                dhtml = _get(dir_url)
            except Exception:
                stats["directions_failed"] += 1
                continue
            for entry in extract_view_entries(dhtml):
                code = entry["code"]
                if code in entries:
                    continue
                entries[code] = {"direction": entry["direction"], "level": lvl,
                                  "form": entry["form"], "kind": entry["kind"]}

    stats["views_total"] = len(entries)
    if not entries:
        return pages, meta, stats

    import concurrent.futures
    workers = max_workers or len(entries)

    def fetch_view(code: str) -> str:
        return _get(f"{BASE}/competitive-list/view?code={code}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_view, code): code for code in entries}
        for fut in concurrent.futures.as_completed(futures):
            code = futures[fut]
            try:
                pages[code] = fut.result()
                meta[code] = entries[code]
            except Exception:
                stats["views_failed"] += 1

    return pages, meta, stats
