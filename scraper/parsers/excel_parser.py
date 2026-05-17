"""Парсер Excel (.xlsx/.xls) расписаний."""
import re

import openpyxl
from openpyxl.utils import get_column_letter

from scraper.parsers.base import BaseParser, ParseResult
from scraper.normalizer.schedule_normalizer import (
    normalize_day, normalize_lesson_type, normalize_time,
    normalize_week_type, make_schedule_skeleton, lesson_obj,
)


class ExcelParser(BaseParser):
    def parse(self, source: str | bytes) -> ParseResult:
        path = source if isinstance(source, str) else _bytes_to_tmp(source, ".xlsx")
        try:
            wb = openpyxl.load_workbook(path, data_only=True)
            groups = []
            for sheet in wb.worksheets:
                groups.extend(_parse_sheet(sheet))
            confidence = _compute_confidence(groups)
            return ParseResult(groups=groups, parser_used="excel", confidence=confidence)
        except Exception as e:
            return ParseResult(groups=[], parser_used="excel", confidence=0.0,
                               warnings=[str(e)])


def _parse_sheet(sheet) -> list[dict]:
    rows = []
    for row in sheet.iter_rows(values_only=True):
        rows.append([_cell_str(c) for c in row])

    if not rows:
        return []

    # ищем строку заголовка с днями недели
    header_row_idx = _find_header_row(rows)
    if header_row_idx is None:
        return _parse_flat(rows)

    header = rows[header_row_idx]
    return _parse_with_header(rows, header_row_idx, header)


def _find_header_row(rows: list[list[str]]) -> int | None:
    day_kw = {"понедельник", "вторник", "среда", "четверг", "пятница", "суббота",
               "пн", "вт", "ср", "чт", "пт", "сб"}
    for i, row in enumerate(rows[:10]):
        matches = sum(1 for c in row if c.lower() in day_kw)
        if matches >= 3:
            return i
    return None


def _parse_with_header(rows, header_idx, header) -> list[dict]:
    day_cols: dict[int, str] = {}
    for i, h in enumerate(header):
        day = normalize_day(h)
        if day:
            day_cols[i] = day

    schedule = make_schedule_skeleton()
    current_time = None

    for row in rows[header_idx + 1:]:
        time_raw = _first_nonempty(row[:2])
        if time_raw:
            parsed = normalize_time(time_raw)
            if parsed:
                current_time = parsed

        if current_time is None:
            continue

        for col_i, day in day_cols.items():
            cell = row[col_i] if col_i < len(row) else ""
            if not cell:
                continue
            week_type, lesson = _parse_cell(cell, current_time[0], current_time[1])
            if lesson:
                if week_type in ("odd", "both"):
                    schedule["odd_week"][day].append(lesson)
                if week_type in ("even", "both"):
                    schedule["even_week"][day].append({**lesson})

    if not any(schedule["odd_week"][d] for d in schedule["odd_week"]):
        return []

    return [{"name": "группа", "year": None, "form": "full_time",
             "degree": "bachelor", "schedule": schedule}]


def _parse_flat(rows: list[list[str]]) -> list[dict]:
    """Если нет заголовка с днями — пробуем колонки день/время/предмет."""
    header = rows[0]
    col = {
        "day": _find_col(header, ["день", "дн"]),
        "time": _find_col(header, ["время", "пара"]),
        "subject": _find_col(header, ["предмет", "дисциплина"]),
        "type": _find_col(header, ["вид", "тип"]),
        "teacher": _find_col(header, ["преподаватель", "педагог"]),
        "room": _find_col(header, ["аудитор", "кабинет"]),
    }
    if col["day"] is None or col["time"] is None:
        return []

    schedule = make_schedule_skeleton()
    for row in rows[1:]:
        day = normalize_day(_get(row, col["day"]) or "")
        if not day:
            continue
        times = normalize_time(_get(row, col["time"]) or "")
        if not times:
            continue
        subject = _get(row, col["subject"]) or ""
        lesson_type = normalize_lesson_type(_get(row, col["type"]) or subject)
        teacher = _get(row, col["teacher"])
        room = _get(row, col["room"])
        lesson = lesson_obj(None, times[0], times[1], subject, lesson_type, teacher, room)
        schedule["odd_week"][day].append(lesson)
        schedule["even_week"][day].append({**lesson})

    return [{"name": "группа", "year": None, "form": "full_time",
             "degree": "bachelor", "schedule": schedule}]


def _parse_cell(cell: str, time_start: str, time_end: str):
    if not cell or cell in {"-", "–", "—"}:
        return "both", None
    week_m = re.search(r"\b(числ[а-я]*|знам[а-я]*|н/|з/|н\b|з\b)\b", cell, re.I)
    week_type = normalize_week_type(week_m.group(1)) if week_m else "both"
    if week_m:
        cell = cell[:week_m.start()] + cell[week_m.end():]
    lesson_type = normalize_lesson_type(cell)
    room_m = re.search(r"(?:ауд\.?\s*)?([\wА-Яа-я]-?\d{2,4})", cell, re.I)
    room = room_m.group(1) if room_m else None
    clean = re.sub(r"\bлек\b\.?|\bпрактика\b|\bпр\b\.?|\bлаб\b\.?|\bсеминар\b", "", cell, flags=re.I).strip()
    return week_type, lesson_obj(None, time_start, time_end, clean, lesson_type, None, room)


def _cell_str(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _first_nonempty(cells: list[str]) -> str:
    for c in cells:
        if c:
            return c
    return ""


def _find_col(header: list[str], keywords: list[str]) -> int | None:
    for i, h in enumerate(header):
        h_lower = h.lower()
        if any(k in h_lower for k in keywords):
            return i
    return None


def _get(row: list[str], col: int | None) -> str | None:
    if col is None or col >= len(row):
        return None
    return row[col] or None


def _compute_confidence(groups):
    if not groups:
        return 0.0
    total = sum(len(l) for g in groups
                for day_l in g["schedule"]["odd_week"].values() for l in [day_l])
    return min(1.0, round(total / 20, 2)) if total else 0.1


def _bytes_to_tmp(data: bytes, ext: str) -> str:
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=ext)
    os.write(fd, data)
    os.close(fd)
    return path
