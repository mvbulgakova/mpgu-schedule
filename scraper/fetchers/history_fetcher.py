"""Обход архива приёмных кампаний mpgu.su за прошлые годы.

URL-шаблоны НЕ угадываются (они нерегулярны) — идём по ссылкам из архивных хабов
и ищем страницы «Конкурс и проходной балл в YYYY году».
"""
import re
import time
from html import unescape
from typing import Dict, List

BASE = "https://mpgu.su"
_ARCHIVE_ROOT = (BASE + "/postuplenie/priemnaya-komissiya/"
                 "priemnyie-kampanii-20hh-2014-godov/")

# Известные хабы годов (нерегулярные слаги — фиксируем явно).
HUBS = [
    _ARCHIVE_ROOT + "priemnaya-kampaniya-2015-2016-goda/",
    _ARCHIVE_ROOT + "priemnaya-kompaniya-2017-2018-goda/",
    _ARCHIVE_ROOT + "priemnaya-kampaniya-2018-2019-gg/",
    _ARCHIVE_ROOT + "priemnaja-kampanija-2019-2020-gg/",
    _ARCHIVE_ROOT + "priemnaja-kampanija-2020-2021-gg/",
    _ARCHIVE_ROOT + "priemnaja-kampanija-2021-2022-gg/",
    _ARCHIVE_ROOT + "priemnaja-kampanija-2022/",
    _ARCHIVE_ROOT + "priemnaja-kampanija-2023/",
    _ARCHIVE_ROOT + "priemnaja-kampanija-2024/",
    _ARCHIVE_ROOT + "priemnaja-kampanija-2025/",
]

_UA = {"User-Agent": "MPGU-Abitur-Bot/1.0 (+https://mpgu.su)"}


def find_year_pages(hub_html: str) -> Dict[int, str]:
    """Из HTML хаба — {год: url страницы «Конкурс и проходной балл в YYYY году»}.

    Отбираем ссылки, в тексте которых есть «конкурс» и «проходн», без «филиал».
    """
    out: Dict[int, str] = {}
    for href, raw in re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                                hub_html or "", re.S | re.I):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", unescape(raw))).strip()
        low = text.lower()
        if "конкурс" not in low or "проходн" not in low or "филиал" in low:
            continue
        myear = re.search(r"\b(20\d\d)\b", text) or re.search(r"(20\d\d)", href)
        if not myear:
            continue
        year = int(myear.group(1))
        url = href if href.startswith("http") else BASE + href
        out.setdefault(year, url)
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


def collect_history_pages(pause: float = 0.4) -> Dict[int, str]:
    """{год: html страницы с таблицей}. Сеть; в юнит-тестах не вызывается."""
    year_urls: Dict[int, str] = {}
    for hub in HUBS:
        try:
            hub_html = _get(hub)
        except Exception:
            continue
        for year, url in find_year_pages(hub_html).items():
            year_urls.setdefault(year, url)
        time.sleep(pause)
    pages: Dict[int, str] = {}
    for year, url in sorted(year_urls.items()):
        try:
            pages[year] = _get(url)
        except Exception:
            continue
        time.sleep(pause)
    return pages
