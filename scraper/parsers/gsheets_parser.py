"""Парсер Google Sheets (публичные таблицы через CSV экспорт)."""
import csv
import io
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import aiohttp

from scraper.parsers.base import BaseParser, ParseResult
from scraper.normalizer.schedule_normalizer import (
    normalize_day, normalize_lesson_type, normalize_time,
    normalize_week_type, make_schedule_skeleton, lesson_obj,
)


def gsheets_to_csv_url(url: str) -> str:
    """Преобразует ссылку на Google Sheets в URL для CSV-экспорта."""
    # https://docs.google.com/spreadsheets/d/{id}/edit#gid=0
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    if not m:
        return url
    sheet_id = m.group(1)
    gid = "0"
    gid_m = re.search(r"[#&?]gid=(\d+)", url)
    if gid_m:
        gid = gid_m.group(1)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


class GSheetsParser(BaseParser):
    def parse(self, source: str | bytes) -> ParseResult:
        if isinstance(source, bytes):
            text = source.decode("utf-8", errors="replace")
        else:
            text = source
        try:
            rows = list(csv.reader(io.StringIO(text)))
            groups = _parse_csv_rows(rows)
            confidence = _compute_confidence(groups)
            return ParseResult(groups=groups, parser_used="gsheets", confidence=confidence)
        except Exception as e:
            return ParseResult(groups=[], parser_used="gsheets", confidence=0.0,
                               warnings=[str(e)])


def _parse_csv_rows(rows: list[list[str]]) -> list[dict]:
    if not rows:
        return []

    # ищем строку с днями недели
    header_idx = _find_header(rows)
    if header_idx is None:
        return _parse_flat(rows)

    header = rows[header_idx]
    day_cols: dict[int, str] = {}
    for i, h in enumerate(header):
        day = normalize_day(h.strip())
        if day:
            day_cols[i] = day

    schedule = make_schedule_skeleton()
    current_time = None

    for row in rows[header_idx + 1:]:
        time_raw = _first_nonempty(row[:2])
        if time_raw:
            parsed = normalize_time(time_raw.strip())
            if parsed:
                current_time = parsed

        if not current_time:
            continue

        for col_i, day in day_cols.items():
            cell = row[col_i].strip() if col_i < len(row) else ""
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


def _parse_flat(rows):
    header = rows[0]
    col = {
        "day": _find_col(header, ["день"]),
        "time": _find_col(header, ["время", "пара"]),
        "subject": _find_col(header, ["предмет", "дисциплина"]),
        "teacher": _find_col(header, ["преподаватель"]),
        "room": _find_col(header, ["аудитор"]),
    }
    if not col["day"] or not col["time"]:
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
        lesson = lesson_obj(None, times[0], times[1], subject, "other",
                            _get(row, col["teacher"]), _get(row, col["room"]))
        schedule["odd_week"][day].append(lesson)
        schedule["even_week"][day].append({**lesson})
    return [{"name": "группа", "year": None, "form": "full_time",
             "degree": "bachelor", "schedule": schedule}]


def _find_header(rows):
    day_kw = {"понедельник", "вторник", "среда", "четверг", "пятница", "суббота",
               "пн", "вт", "ср", "чт", "пт", "сб"}
    for i, row in enumerate(rows[:10]):
        if sum(1 for c in row if c.strip().lower() in day_kw) >= 3:
            return i
    return None


def _parse_cell(cell, t_start, t_end):
    if not cell or cell in {"-", "–", "—"}:
        return "both", None
    week_m = re.search(r"\b(числ[а-я]*|знам[а-я]*|н/|з/|н\b|з\b)\b", cell, re.I)
    week_type = normalize_week_type(week_m.group(1)) if week_m else "both"
    lesson_type = normalize_lesson_type(cell)
    room_m = re.search(r"(?:ауд\.?\s*)?([\wА-Яа-я]-?\d{2,4})", cell, re.I)
    room = room_m.group(1) if room_m else None
    clean = re.sub(r"\bлек\b\.?|\bпрактика\b|\bпр\b\.?|\bлаб\b\.?|\bсеминар\b", "", cell, flags=re.I).strip()
    return week_type, lesson_obj(None, t_start, t_end, clean, lesson_type, None, room)


def _first_nonempty(cells):
    for c in cells:
        if c.strip():
            return c.strip()
    return ""


def _find_col(header, kw):
    for i, h in enumerate(header):
        if any(k in h.lower() for k in kw):
            return i
    return None


def _get(row, col):
    if col is None or col >= len(row):
        return None
    return row[col].strip() or None


def _compute_confidence(groups):
    if not groups:
        return 0.0
    total = sum(len(l) for g in groups
                for day_l in g["schedule"]["odd_week"].values() for l in [day_l])
    return min(1.0, round(total / 20, 2)) if total else 0.1
