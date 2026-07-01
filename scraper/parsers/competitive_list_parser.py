"""Парсер страницы конкурсного списка epk25 (/competitive-list/view?code=...).

Таблица приходит с uppercase-тегами; BeautifulSoup нормализует регистр.
Строки абитуриентов опознаются по первой ячейке-числу (позиция).
"""
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

# Индексы колонок (стабильный порядок экспорта МПГУ).
C_POS, C_CODE, C_CONSENT, C_PZ, C_OVP, C_VPP, C_BVI = 0, 1, 2, 3, 4, 5, 6
C_TOTAL, C_VI_SUM, C_VI1, C_VI2, C_VI3, C_ID, C_PP, C_STATUS, C_REJECT = 7, 8, 9, 10, 11, 12, 13, 14, 15
MIN_CELLS = 15


def _int(s: str) -> Optional[int]:
    s = (s or "").strip()
    return int(s) if s.lstrip("-").isdigit() else None


def _cell(cells: List[str], i: int) -> str:
    return cells[i].strip() if i < len(cells) else ""


def parse_view(html: str) -> List[Dict]:
    soup = BeautifulSoup(html or "", "lxml")
    rows: List[Dict] = []
    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) < MIN_CELLS:
            continue
        pos = _int(_cell(cells, C_POS))
        code = _cell(cells, C_CODE)
        if pos is None or not code.isdigit():
            continue  # заголовки/служебные строки
        rows.append({
            "position": pos,
            "unique_code": code,
            "consent": bool(_cell(cells, C_CONSENT)),
            "priority_pz": _int(_cell(cells, C_PZ)),
            "priority_ovp": _int(_cell(cells, C_OVP)),
            "priority_vpp": _int(_cell(cells, C_VPP)),
            "bvi": bool(_cell(cells, C_BVI)),
            "score_total": _int(_cell(cells, C_TOTAL)),
            "score_vi": _int(_cell(cells, C_VI_SUM)),
            "id_points": _int(_cell(cells, C_ID)),
            "status": _cell(cells, C_STATUS),
            "reject_reason": _cell(cells, C_REJECT),
        })
    return rows
