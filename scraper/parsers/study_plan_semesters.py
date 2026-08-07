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
# План свёрстан как дерево, и в самой левой колонке стоит значок раскрытия узла.
# В названия он попадал буквально: «+ История России» у КАЖДОЙ дисциплины.
_TREE_MARKS = {"+", "-", "–", "—", "±"}
# Насколько далеко от своей строки-индекса может лежать строка-продолжение —
# в долях типичного расстояния МЕЖДУ дисциплинами. Фиксированный порог не
# годится: у разных планов свой кегль и своя высота строки, а высота клетки
# зависит от длины названия. При жёстком пороге в 5pt у «Технологии
# культурно-досуговой деятельности (театральная педагогика, кинопедагогика,
# арт-педагогика, музейная педагогика, библиотечная педагогика)» — пять строк,
# индекс на третьей — отвалились первая и последняя, и от названия осталась
# середина, начинающаяся со скобки.
_CELL_SPAN = 0.75
# Запасной зазор, когда на странице всего одна дисциплина и шаг измерить не по чему.
_CELL_GAP_FALLBACK = 12.0


def _is_name_token(w: tuple, band_lo: float) -> bool:
    """Слово относится к названию дисциплины (а не к индексу, значку или числам)."""
    text = w[4]
    return (30 < w[0] < band_lo and text not in _TREE_MARKS
            and not _INDEX_RE.match(text))


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
    """Список слов страницы плана → дисциплины с семестрами.

    Строка плана — это КЛЕТКА, а не одна строка текста. Длинное название
    переносится на 2–3 строки, а индекс стоит по центру клетки, то есть на
    средней из них. Если считать строкой каждый уровень y по отдельности,
    у такой дисциплины на «строке индекса» не окажется ни одного слова
    названия, а сами слова окажутся на строках без индекса и пропадут.
    Так терялись целые предметы: «Нормативно-правовые основы
    профессиональной деятельности» (Б1.О.01.05) и «Возрастная анатомия,
    физиология и культура здоровья» (Б1.О.03.01) выводились как пустые.
    Поэтому строки без индекса приклеиваем к ближайшей строке С индексом.
    """
    centers = _column_centers(words)
    if not centers:
        return []
    band_lo, band_hi = min(centers) - 7, max(centers) + 7
    lines: Dict[float, list] = defaultdict(list)
    for w in words:
        lines[round(w[1], 2)].append(w)

    anchors = [y for y in sorted(lines)
               if any(_INDEX_RE.match(w[4]) for w in lines[y])]
    if not anchors:
        return []
    # Клетка: строка с индексом плюс её строки-продолжения. Каждую строку без
    # индекса отдаём БЛИЖАЙШЕЙ дисциплине — так строку нельзя увести у соседа,
    # к которому она ближе. Порог считаем от реального шага между дисциплинами
    # на этой странице, а не берём константой (см. _CELL_SPAN).
    cells: Dict[float, list] = {y: list(lines[y]) for y in anchors}
    gaps = sorted(b - a for a, b in zip(anchors, anchors[1:]))
    step = gaps[len(gaps) // 2] if gaps else _CELL_GAP_FALLBACK
    max_gap = max(step * _CELL_SPAN, _CELL_GAP_FALLBACK * _CELL_SPAN)
    for y in sorted(lines):
        if y in cells:
            continue
        nearest = min(anchors, key=lambda a: abs(a - y))
        if abs(nearest - y) <= max_gap:
            cells[nearest].extend(lines[y])

    out = []
    for y in anchors:
        row = sorted(cells[y], key=lambda w: (w[1], w[0]))
        idx = next((w[4] for w in row if _INDEX_RE.match(w[4])), None)
        name = " ".join(w[4] for w in row if _is_name_token(w, band_lo)).strip()
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
