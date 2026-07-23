"""Извлечение «дисциплина → семестры» из учебного плана МПГУ (.plx → PDF).

Ключ (подсказан приёмной комиссией): в первых столбцах формы контроля
(Экзамен/Зачёт/Зачёт с оц./КР) после названия записаны НОМЕРА семестров, в
которых предмет идёт. Цифра = семестр 1–9, буквы А/В/С = семестры 10/11/12.
Например «1234» в столбце = предмет идёт первые 4 семестра.

Пустые ячейки в плоском тексте PDF схлопываются (нельзя отличить семестр «4»
от «4 з.е.»), поэтому читаем ПО КООРДИНАТАМ: берём токены под четырьмя
столбцами контроля (их x-центры находим по заголовкам) — только там семестры.

parse_words(words) — чистая, принимает список кортежей pymupdf get_text('words')
(x0,y0,x1,y1,text,...) → [{"index","name","semesters"}] по дисциплинам-листьям.
"""
import re
from collections import defaultdict
from typing import Dict, List, Optional

_SEM = {str(i): i for i in range(1, 10)}
_SEM.update({"А": 10, "В": 11, "С": 12, "A": 10, "B": 11, "C": 12})
_CODE_RE = re.compile(r"^[0-9АВСABC]+$")
_INDEX_RE = re.compile(r"^Б\d")
# лист-дисциплина: индекс с ≥3 сегментами (Б1.О.01.01), а не модуль (Б1.О.01)
_LEAF_RE = re.compile(r"^Б\d+\.[^.\s]+\.\d+\.\d+")


def decode_codes(tokens: List[str]) -> List[int]:
    """Токены столбцов контроля → отсортированное множество семестров."""
    return sorted({_SEM[c] for tok in tokens for c in tok if c in _SEM})


def _column_centers(words: List[tuple]) -> Optional[List[float]]:
    """x-центры четырёх столбцов контроля по заголовкам Экза/Зачет/оц./КР."""
    def cx(pred):
        xs = [(w[0] + w[2]) / 2 for w in words if pred(w[4])]
        return sum(xs) / len(xs) if xs else None
    exam = cx(lambda s: s.startswith("Экза"))
    kr = cx(lambda s: s == "КР")
    zach = [((w[0] + w[2]) / 2) for w in words if w[4] == "Зачет"]
    if exam is None or kr is None or len(zach) < 2:
        return None
    zach.sort()
    return sorted([exam, zach[0], zach[1], kr])


def parse_words(words: List[tuple], leaves_only: bool = True) -> List[dict]:
    """Список слов страницы плана → дисциплины с семестрами."""
    centers = _column_centers(words)
    if not centers:
        return []
    band_lo, band_hi = min(centers) - 7, max(centers) + 7
    lines: Dict[int, list] = defaultdict(list)
    for w in words:
        lines[round(w[1])].append(w)
    out = []
    for y in sorted(lines):
        row = sorted(lines[y], key=lambda w: w[0])
        idx = next((w[4] for w in row if _INDEX_RE.match(w[4])), None)
        if not idx:
            continue
        name = " ".join(w[4] for w in row
                         if 30 < w[0] < band_lo and not _INDEX_RE.match(w[4])).strip()
        codes = [w[4] for w in row
                 if band_lo <= ((w[0] + w[2]) / 2) <= band_hi and _CODE_RE.match(w[4])]
        sems = decode_codes(codes)
        if not name or not sems:
            continue
        if leaves_only and not _LEAF_RE.match(idx):
            continue
        out.append({"index": idx, "name": name, "semesters": sems})
    return out


def parse_pdf_bytes(data: bytes) -> List[dict]:
    """PDF учебного плана (байты) → дисциплины с семестрами (все страницы плана)."""
    import fitz
    seen, out = set(), []
    with fitz.open(stream=data, filetype="pdf") as d:
        for pg in d:
            words = pg.get_text("words")
            if not any(w[4] == "Наименование" for w in words):
                continue
            for row in parse_words(words):
                key = (row["index"], row["name"])
                if key in seen:
                    continue
                seen.add(key)
                out.append(row)
    return out


def by_semester(rows: List[dict]) -> Dict[int, List[str]]:
    """{семестр: [названия дисциплин]} из результата parse_*."""
    res: Dict[int, List[str]] = defaultdict(list)
    for r in rows:
        for s in r["semesters"]:
            res[s].append(r["name"])
    return dict(sorted(res.items()))
