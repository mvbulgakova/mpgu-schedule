"""Разбор приказа о зачислении по конкурсным группам, со строками и баллами.

В отличие от enrollment_order.parse_order_pdf_codes (тот достаёт только коды,
чтобы исключить зачисленных из симуляции), здесь нужен полный разбор: кто в
какую группу зачислен и с каким баллом. Это даёт настоящий проходной —
минимальный балл среди РЕАЛЬНО зачисленных, а не оценку по отметкам ВПП.

Читаем ПО КООРДИНАТАМ, а не по плоскому тексту. У зачисленных по БВИ ячейки
с баллами пустые, а у части — заполнена только графа ИД (2026-08-03, отдельная
квота: код 938857 без единого балла, код 1291212 с суммой 10 при пустых ВИ).
В плоском тексте пустые ячейки схлопываются, и баллы уезжают в чужие колонки.

parse_groups(words_by_page) — чистая, принимает списки слов pymupdf
get_text('words') постранично.
"""
import re
from collections import defaultdict
from typing import Dict, List, Optional

_FIELDS = (
    ("unit", "Учебное структурное подразделение:"),
    ("direction", "Направление подготовки:"),
    ("profile", "Направленность:"),
    ("form", "Форма обучения:"),
    ("admission", "Особенности приема:"),
    ("basis", "Основание поступления:"),
)
_CODE_RE = re.compile(r"^\d{6,8}$")
_NUM_RE = re.compile(r"^\d{1,3}$")
_ROWNO_RE = re.compile(r"^\d{1,3}\.$")

# Границы колонок берём из ШАПКИ ТАБЛИЦЫ, а не по всей странице: слова
# «вступительные» и «испытания» встречаются ещё и в преамбуле приказа
# («успешно прошедшие вступительные испытания»), и якорь по всей странице
# уезжал на 60pt влево — колонка «баллов за ВИ» начинала читать сумму.
# Шапка опознаётся по слову «Уникальный»; на страницах-продолжениях её нет,
# тогда действуют границы последней виденной.
_HEADER_WORD = "Уникальный"


def _lines(words: List[tuple]) -> Dict[float, list]:
    out: Dict[float, list] = defaultdict(list)
    for w in words:
        out[round(w[1])].append(w)
    return out


def _columns(words: List[tuple]) -> Optional[dict]:
    """Границы колонок по шапке таблицы; None, если шапки на странице нет."""
    heads = [w for w in words if w[4] == _HEADER_WORD]
    if not heads:
        return None
    band = [w for w in words if abs(w[1] - heads[0][1]) <= 30]

    def cx(word):
        xs = [(w[0] + w[2]) / 2 for w in band if w[4] == word]
        return sum(xs) / len(xs) if xs else None

    code, total = cx(_HEADER_WORD), cx("конкурсных")
    vi = sorted((w[0] + w[2]) / 2 for w in band if w[4] == "ВИ")
    ident = cx("индивидуальные")
    if code is None or total is None or len(vi) < 3 or ident is None:
        return None
    # Колонку «баллов за ВИ» вычисляем как промежуток между суммой и ВИ 1:
    # её собственный заголовок («Количество баллов за вступительные
    # испытания») разнесён по четырём строкам и центр даёт неверно.
    return {"code": (code - 45, code + 45),
            "total": (total - 40, total + 40),
            "vi_total": (total + 40, vi[0] - 25),
            "vi": [(x - 20, x + 20) for x in vi[:3]],
            "id": (ident - 45, ident + 45)}


def _cell(row: List[tuple], bounds) -> Optional[int]:
    lo, hi = bounds
    for w in row:
        cx = (w[0] + w[2]) / 2
        if lo <= cx < hi and _NUM_RE.match(w[4]):
            return int(w[4])
    return None


def parse_groups(words_by_page: List[List[tuple]]) -> List[dict]:
    """[{unit, direction, profile, form, admission, basis, rows:[...]}].

    Группа продолжается на следующих страницах, пока не встретится новая шапка
    «Учебное структурное подразделение» — иначе длинные конкурсы (сотни строк)
    развалились бы на куски и проходной считался бы по обрывку.
    """
    groups: List[dict] = []
    cols = None
    for words in words_by_page:
        cols = _columns(words) or cols
        lines = _lines(words)
        pending: Dict[str, str] = {}
        for y in sorted(lines):
            row = sorted(lines[y], key=lambda w: w[0])
            text = " ".join(w[4] for w in row)
            hit = False
            for key, label in _FIELDS:
                if text.startswith(label):
                    value = text[len(label):].strip()
                    if key == "unit":
                        pending = {"unit": value}      # новая группа началась
                    else:
                        pending[key] = value
                    hit = True
                    break
            if hit:
                continue
            # продолжение длинного названия — приклеиваем к последнему полю
            if pending and not _ROWNO_RE.match(row[0][4] if row else ""):
                last = list(pending)[-1]
                if last in ("unit", "direction", "profile") and text.strip() \
                        and not text.startswith(("№", "Сумма", "Количество",
                                                 "ВИ", "баллов", "испытания",
                                                 "достижения", "Особое")):
                    pending[last] = f"{pending[last]} {text}".strip()
                    continue
            if pending.get("unit") and pending.get("form"):
                groups.append({**pending, "rows": []})
                pending = {}
            if not groups or not cols:
                continue
            lo, hi = cols["code"]
            code = next((w[4] for w in row if _CODE_RE.match(w[4])
                         and lo <= (w[0] + w[2]) / 2 <= hi), None)
            if not code:
                continue
            groups[-1]["rows"].append({
                "code": code,
                "total": _cell(row, cols["total"]),
                "vi_total": _cell(row, cols["vi_total"]),
                "vi": [_cell(row, b) for b in cols["vi"]],
                "id": _cell(row, cols["id"]),
            })
    return groups


def parse_pdf_bytes(data: bytes) -> List[dict]:
    import fitz
    with fitz.open(stream=data, filetype="pdf") as d:
        return parse_groups([pg.get_text("words") for pg in d])


def is_bvi_row(row: dict) -> bool:
    """Зачислен без вступительных испытаний: экзаменационных баллов нет.

    У таких в приказе пустые ВИ, а сумма либо пустая, либо равна одним лишь
    баллам за индивидуальные достижения. Считать их в проходной нельзя: они
    прошли вне конкурса и утянули бы порог к нулю.
    """
    if any(v is not None for v in (row.get("vi") or [])):
        return False
    return not row.get("vi_total")
