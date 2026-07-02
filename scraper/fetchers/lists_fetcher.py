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


def crawl(levels: List[str] = None, pause: float = 0.3) -> Dict[str, str]:
    """Возвращает {code -> html страницы view}. Сеть; в тестах не вызывается."""
    levels = levels or LEVELS
    pages: Dict[str, str] = {}
    for lvl in levels:
        try:
            struct = _get(structural_url(lvl))
        except Exception:
            continue
        for dir_url in extract_direction_links(struct):
            time.sleep(pause)
            try:
                dhtml = _get(dir_url)
            except Exception:
                continue
            for code in extract_view_codes(dhtml):
                if code in pages:
                    continue
                time.sleep(pause)
                try:
                    pages[code] = _get(f"{BASE}/competitive-list/view?code={code}")
                except Exception:
                    continue
    return pages
