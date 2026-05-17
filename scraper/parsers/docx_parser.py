"""Парсер DOCX расписаний."""
import re

from docx import Document
from docx.table import Table

from scraper.parsers.base import BaseParser, ParseResult
from scraper.normalizer.schedule_normalizer import (
    normalize_day, normalize_lesson_type, normalize_time,
    normalize_week_type, make_schedule_skeleton, lesson_obj,
)


class DocxParser(BaseParser):
    def parse(self, source: str | bytes) -> ParseResult:
        path = source if isinstance(source, str) else _bytes_to_tmp(source, ".docx")
        try:
            doc = Document(path)
            tables_raw = []
            for table in doc.tables:
                rows = []
                for row in table.rows:
                    rows.append([cell.text.strip() for cell in row.cells])
                tables_raw.append(rows)

            groups = []
            for table in tables_raw:
                if not table:
                    continue
                header = [c.lower() for c in table[0]]
                if _has_day_columns(header):
                    groups.extend(_parse_day_columns(table))
                else:
                    groups.extend(_parse_flat(table))

            confidence = _compute_confidence(groups)
            return ParseResult(groups=groups, parser_used="docx", confidence=confidence)
        except Exception as e:
            return ParseResult(groups=[], parser_used="docx", confidence=0.0,
                               warnings=[str(e)])


def _has_day_columns(header):
    day_kw = {"понедельник", "вторник", "среда", "четверг", "пятница", "суббота",
               "пн", "вт", "ср", "чт", "пт", "сб"}
    return sum(1 for h in header if h in day_kw) >= 3


def _parse_day_columns(table):
    header = table[0]
    day_cols = {}
    for i, h in enumerate(header):
        day = normalize_day(h)
        if day:
            day_cols[i] = day

    schedule = make_schedule_skeleton()
    current_time = None

    for row in table[1:]:
        time_raw = row[0] if row else ""
        if time_raw:
            parsed = normalize_time(time_raw)
            if parsed:
                current_time = parsed
        if not current_time:
            continue
        for col_i, day in day_cols.items():
            cell = row[col_i] if col_i < len(row) else ""
            if not cell:
                continue
            week_m = re.search(r"\b(числ[а-я]*|знам[а-я]*|н/|з/)\b", cell, re.I)
            week_type = normalize_week_type(week_m.group(1)) if week_m else "both"
            lesson_type = normalize_lesson_type(cell)
            clean = re.sub(r"\bлек\b|\bпрактика\b|\bпр\b|\bлаб\b|\bсеминар\b", "", cell, flags=re.I).strip()
            room_m = re.search(r"[\wА-Яа-я]-?\d{2,4}", clean)
            room = room_m.group(0) if room_m else None
            lesson = lesson_obj(None, current_time[0], current_time[1], clean, lesson_type, None, room)
            if week_type in ("odd", "both"):
                schedule["odd_week"][day].append(lesson)
            if week_type in ("even", "both"):
                schedule["even_week"][day].append({**lesson})

    if not any(schedule["odd_week"][d] for d in schedule["odd_week"]):
        return []
    return [{"name": "группа", "year": None, "form": "full_time",
             "degree": "bachelor", "schedule": schedule}]


def _parse_flat(table):
    if len(table) < 2:
        return []
    header = [c.lower() for c in table[0]]
    col = {
        "day": _find_col(header, ["день"]),
        "time": _find_col(header, ["время"]),
        "subject": _find_col(header, ["предмет", "дисциплина"]),
        "teacher": _find_col(header, ["преподаватель"]),
        "room": _find_col(header, ["аудитор"]),
    }
    if col["day"] is None or col["time"] is None:
        return []
    schedule = make_schedule_skeleton()
    for row in table[1:]:
        day = normalize_day(_get(row, col["day"]) or "")
        if not day:
            continue
        times = normalize_time(_get(row, col["time"]) or "")
        if not times:
            continue
        subject = _get(row, col["subject"]) or ""
        lesson = lesson_obj(None, times[0], times[1], subject, "other",
                            _get(row, col["teacher"]), _get(row, col["room"]))
        schedule["odd_week"][day].append(lesson)
        schedule["even_week"][day].append({**lesson})
    return [{"name": "группа", "year": None, "form": "full_time",
             "degree": "bachelor", "schedule": schedule}]


def _find_col(header, kw):
    for i, h in enumerate(header):
        if any(k in h for k in kw):
            return i
    return None


def _get(row, col):
    if col is None or col >= len(row):
        return None
    return row[col] or None


def _compute_confidence(groups):
    if not groups:
        return 0.0
    total = sum(len(l) for g in groups
                for day_l in g["schedule"]["odd_week"].values() for l in [day_l])
    return min(1.0, round(total / 20, 2)) if total else 0.1


def _bytes_to_tmp(data, ext):
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=ext)
    os.write(fd, data)
    os.close(fd)
    return path
