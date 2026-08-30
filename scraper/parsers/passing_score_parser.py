"""Парсер архивных страниц «Конкурс и проходной балл в YYYY году» (mpgu.su).

Структура (проверена на 2019): HTML-таблицы, строки-факультеты без чисел,
строки-программы: [код+направление, программа+форма, конкурс, проходной].
"""
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

_CODE_RE = re.compile(r"\d{2}\.\d{2}\.\d{2}")
_FORM_RE = re.compile(r"(очно-заочная|очная|заочная)", re.I)


def _int_score(s: str) -> Optional[int]:
    for m in re.finditer(r"\b(\d{2,3})\b", s or ""):
        v = int(m.group(1))
        if 60 <= v <= 310:  # сумма трёх ВИ (+ИД); отсекаем годы/номера
            return v
    return None


def _float_comp(s: str) -> Optional[float]:
    m = re.search(r"\b(\d{1,3}(?:[.,]\d)?)\b", (s or "").replace(",", "."))
    return float(m.group(1)) if m else None


def _budget_final_col(soup) -> Optional[int]:
    """Формат 2015–2016: индекс ПОСЛЕДНЕГО бюджетного столбца «Проходной балл на N августа».

    Подшапка (строка с датами) относится к столбцам данных, начиная со 2-го
    (первые два — «Код и наименование» и «Форма» объединены по вертикали, rowspan).
    Возвращает индекс столбца в строке данных или None, если это иной формат.
    """
    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        date_cols = [i for i, c in enumerate(cells)
                     if "проходной" in c.lower() and re.search(r"авгус", c.lower())]
        if date_cols:
            return 2 + date_cols[-1]
    return None


def parse_score_table(html: str, year: int) -> List[Dict]:
    soup = BeautifulSoup(html or "", "lxml")
    budget_col = _budget_final_col(soup)
    if budget_col is not None:
        return _parse_wide(soup, year, budget_col)
    rows: List[Dict] = []
    for tr in soup.find_all("tr"):
        cells = [td.get_text("\n", strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) < 3:
            continue
        mcode = _CODE_RE.search(cells[0])
        if not mcode:
            continue
        prog_cell = cells[1]
        mform = _FORM_RE.search(prog_cell)
        form = mform.group(1).lower() if mform else "очная"
        program = prog_cell
        if mform:
            program = prog_cell[:mform.start()]
        program = re.sub(r"\s+", " ", program).strip(" ,;\n")
        passing = _int_score(cells[-1])
        if passing is None:
            continue
        competition = _float_comp(cells[-2]) if len(cells) >= 4 else None
        rows.append({"year": year, "code": mcode.group(), "program": program,
                     "form": form, "passing": passing, "competition": competition})
    return rows


def _parse_wide(soup, year: int, budget_col: int) -> List[Dict]:
    """Формат 2015–2016: код+название в cells[0], проходной — из бюджетного столбца."""
    rows: List[Dict] = []
    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) <= budget_col:
            continue
        mcode = _CODE_RE.search(cells[0])
        if not mcode:
            continue
        name = re.sub(r"\s+", " ", cells[0][mcode.end():]).strip(" ,;.\n")
        mform = _FORM_RE.search(cells[1])
        form = mform.group(1).lower() if mform else "очная"
        passing = _int_score(cells[budget_col])  # «—» → None, строку пропустим
        if passing is None:
            continue
        rows.append({"year": year, "code": mcode.group(), "program": name,
                     "form": form, "passing": passing, "competition": None})
    return rows
