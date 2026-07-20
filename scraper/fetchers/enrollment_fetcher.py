"""Обход страниц «Сведения о зачислении» МПГУ (2022+) → проходные баллы.

С 2021 года МПГУ перестал публиковать сводные таблицы «Конкурс и проходной
балл»; вместо них — пофамильные списки зачисленных (PDF). Проходной по каждой
программе восстанавливаем как минимум суммы баллов среди зачисленных на
основные (общие конкурсные) бюджетные места основной волны.

Страницы основной волны нерегулярны по слагам — фиксируем явно, как HUBS в
history_fetcher. Страница 2024 на живом сайте удалена — берём из веб-архива
(снимок 09.2024 с основной волной 08.08.2024).
"""
import re
import urllib.parse
from typing import Dict, List

from scraper.fetchers.history_fetcher import _get, _UA
from scraper.parsers.enrollment_parser import parse_text

_ARCH = "https://web.archive.org"

# {год: URL страницы зачисления на основные бюджетные места (базовый бакалавриат)}
PAGES: Dict[int, str] = {
    2022: ("https://mpgu.su/postuplenie/priemnaya-komissiya/"
           "priemnyie-kampanii-20hh-2014-godov/priemnaja-kampanija-2022/"
           "svedenija-o-zachislenii/zachislennyh-bakalavriata-obuchenija/"),
    2023: ("https://mpgu.su/postuplenie/priemnaya-komissiya/"
           "priemnyie-kampanii-20hh-2014-godov/priemnaja-kampanija-2023/"
           "svedenija-o-zachislenii/zachislenie-08-08-2023-budget/"),
    2024: (_ARCH + "/web/20240912171659id_/https://mpgu.su/postuplenie/"
           "svedenija-o-zachislenii-2024/zachislenie-08-08-2024-budget/"),
    2025: ("https://mpgu.su/postuplenie/priemnaya-komissiya/"
           "priemnyie-kampanii-20hh-2014-godov/priemnaja-kampanija-2025/"
           "svedenija-o-zachislenii/zachislenie-07-08-2025-budget/"),
}


def _abs_url(href: str, page: str) -> str:
    """Абсолютный URL PDF; для веб-архива — с суффиксом id_ (без тулбара)."""
    if href.startswith("http") and "web.archive.org" not in href:
        return href
    if _ARCH in page:                       # ссылки внутри архивной страницы
        href = href if href.startswith("http") else _ARCH + href
        return re.sub(r"/web/(\d+)(?:id_)?/", r"/web/\1id_/", href)
    return href if href.startswith("http") else "https://mpgu.su" + href


def _pdf_links(html: str) -> List[str]:
    return list(dict.fromkeys(re.findall(r'href="([^"]+\.pdf)"', html, re.I)))


def _download_text(url: str) -> str:
    import io
    import fitz
    import requests
    r = requests.get(url, headers=_UA, timeout=90)
    r.raise_for_status()
    with fitz.open(stream=io.BytesIO(r.content), filetype="pdf") as d:
        return "\n".join(p.get_text() for p in d)


def collect_rows(years=None) -> List[dict]:
    """[{year, code, form, program, passing, competition:None}] по всем PDF годов."""
    rows: List[dict] = []
    for year, page in PAGES.items():
        if years and year not in years:
            continue
        try:
            html = _get(page)
        except Exception as e:  # noqa: BLE001
            print(f"{year}: страница недоступна ({e})")
            continue
        pdfs = _pdf_links(html)
        print(f"{year}: PDF-файлов {len(pdfs)}")
        year_rows = 0
        for href in pdfs:
            url = _abs_url(href, page)
            try:
                txt = _download_text(url)
            except Exception as e:  # noqa: BLE001
                print(f"  ! {urllib.parse.unquote(url.split('/')[-1])[:40]}: {e}")
                continue
            for (code, form, prog), passing in parse_text(txt).items():
                rows.append({"year": year, "code": code, "form": form,
                             "program": prog, "passing": passing,
                             "competition": None})
                year_rows += 1
        print(f"{year}: программ с проходным {year_rows}")
    return rows


if __name__ == "__main__":
    import json
    rows = collect_rows()
    print(json.dumps(rows[:5], ensure_ascii=False, indent=1))
    print("всего строк:", len(rows))
