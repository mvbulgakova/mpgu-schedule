"""Обход официальных приказов о зачислении 2026 (квоты + БВИ) на mpgu.su.

Возвращает только множество кодов упомянутых абитуриентов — для исключения
их из общего конкурса при симуляции (scraper.build_lists_index): человек,
зачисленный приказом (квота или без экзаменов), больше не претендует на
общий конкурс, а конкурсные списки epk25 сами по себе этого не показывают.

Сеть; в тестах не вызывается (см. parse_order_pdf_codes — чистая функция).
"""
import re
from html import unescape
from typing import List, Set

from scraper.parsers.enrollment_order import parse_order_pdf_codes

BASE = "https://mpgu.su"
INDEX_PAGE = f"{BASE}/postuplenie/svedenija-zachislenii-2026/"
_UA = {"User-Agent": "MPGU-Abitur-Bot/1.0 (+https://mpgu.su)"}


def _get(url: str) -> str:
    import requests
    r = requests.get(url, headers=_UA, timeout=30)
    r.raise_for_status()
    return r.text


def _get_pdf_text(url: str) -> str:
    import io
    import fitz
    import requests
    r = requests.get(url, headers=_UA, timeout=90)
    r.raise_for_status()
    with fitz.open(stream=io.BytesIO(r.content), filetype="pdf") as d:
        return "\n".join(p.get_text() for p in d)


def order_subpage_links(html: str) -> List[str]:
    hrefs = re.findall(
        r'href="([^"]*svedenija-zachislenii-2026/zachislenie-[^"]+)"', html or "")
    seen, out = set(), []
    for h in hrefs:
        h = unescape(h)
        url = h if h.startswith("http") else BASE + h
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def pdf_links(html: str) -> List[str]:
    return list(dict.fromkeys(re.findall(r'href="([^"]+\.pdf)"', html or "", re.I)))


def collect_enrolled_codes() -> Set[str]:
    """Коды абитуриентов из всех опубликованных приказов (все даты, квоты+бви).

    Лучший результат из возможного: страница/PDF, который не удалось
    скачать, просто пропускается — публикацию индекса это не блокирует
    (см. main() в build_lists_index.py).
    """
    codes: Set[str] = set()
    try:
        index_html = _get(INDEX_PAGE)
    except Exception:
        return codes
    for sub in order_subpage_links(index_html):
        try:
            sub_html = _get(sub)
        except Exception:
            continue
        for pdf_url in pdf_links(sub_html):
            try:
                text = _get_pdf_text(pdf_url)
            except Exception:
                continue
            codes.update(parse_order_pdf_codes(text))
    return codes
