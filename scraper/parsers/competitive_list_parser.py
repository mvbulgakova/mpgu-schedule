"""Парсер страницы конкурсного списка epk25 (/competitive-list/view?code=...).

Теги приходят в ВЕРХНЕМ регистре; BeautifulSoup нормализует регистр.

Раскладка колонок различается по типу списка (бюджет: «Наличие согласия…»; платный:
«Заключен договор» + «Оплачено» — на колонку больше). Поэтому колонки резолвятся ПО
ЗАГОЛОВКАМ, а не по фиксированным индексам. Строки абитуриентов — по первой ячейке-числу.
"""
from typing import Dict, List, Optional

from bs4 import BeautifulSoup


def _int(s: str) -> Optional[int]:
    s = (s or "").strip()
    return int(s) if s.lstrip("-").isdigit() else None


def _header_colmap(header_tr) -> Dict[int, str]:
    """Разворачивает первую строку заголовка в {leaf_index -> label} с учётом colspan."""
    cols: Dict[int, str] = {}
    idx = 0
    for td in header_tr.find_all("td"):
        label = td.get_text(" ", strip=True).lower()
        try:
            span = int(td.get("colspan", 1))
        except (TypeError, ValueError):
            span = 1
        for _ in range(max(1, span)):
            cols[idx] = label
            idx += 1
    return cols


def _find(cols: Dict[int, str], *, contains=None, equals=None) -> Optional[int]:
    for i, label in cols.items():
        if equals is not None and label == equals:
            return i
        if contains is not None and all(c in label for c in contains):
            return i
    return None


def parse_view(html: str) -> List[Dict]:
    soup = BeautifulSoup(html or "", "lxml")
    trs = soup.find_all("tr")

    # найти строку-заголовок (содержит «уникальный код»)
    header_tr = None
    for tr in trs:
        if any("уникальный код" in td.get_text(" ", strip=True).lower()
               for td in tr.find_all("td")):
            header_tr = tr
            break
    if header_tr is None:
        return []

    cols = _header_colmap(header_tr)
    idx = {
        "code": _find(cols, contains=["уникальный", "код"]),
        "consent": _find(cols, contains=["согласи"]),
        "pz": _find(cols, equals="пз"),
        "ovp": _find(cols, equals="овп"),
        "vpp": _find(cols, equals="впп"),
        "bvi": _find(cols, contains=["основание", "бви"]),
        "total": _find(cols, contains=["сумма", "конкурсных"]),
        "vi_sum": _find(cols, contains=["сумма", "за ви"]),
        "id": _find(cols, equals="ид"),
        "status": _find(cols, contains=["информация", "рассмотрен"]),
        "reject": _find(cols, contains=["причина", "отказа"]),
    }
    if idx["code"] is None:
        return []

    def cell(cells, key):
        i = idx[key]
        return cells[i].strip() if i is not None and i < len(cells) else ""

    rows: List[Dict] = []
    for tr in trs:
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if not cells:
            continue
        pos = _int(cells[0])
        code = cell(cells, "code")
        if pos is None or not code.isdigit():
            continue
        rows.append({
            "position": pos,
            "unique_code": code,
            "consent": bool(cell(cells, "consent")),
            "priority_pz": _int(cell(cells, "pz")),
            # ОВП/ВПП — отметка «✓» или пусто (см. epk_602.html: ни разу число на
            # реальной странице), не число — раньше это шло через _int() и
            # галочка молча превращалась в None, а не в True.
            "ovp": bool(cell(cells, "ovp")),
            "vpp": bool(cell(cells, "vpp")),
            "bvi": bool(cell(cells, "bvi")),
            "score_total": _int(cell(cells, "total")),
            "score_vi": _int(cell(cells, "vi_sum")),
            "id_points": _int(cell(cells, "id")),
            "status": cell(cells, "status"),
            "reject_reason": cell(cells, "reject"),
        })
    return rows
