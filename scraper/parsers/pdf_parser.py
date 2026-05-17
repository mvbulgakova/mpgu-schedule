"""PDF парсер с тремя уровнями: pdfplumber → camelot → Claude vision."""
import os
import re
from pathlib import Path

import pdfplumber

from scraper.parsers.base import BaseParser, ParseResult
from scraper.normalizer.schedule_normalizer import (
    normalize_day, normalize_lesson_type, normalize_time,
    normalize_week_type, make_schedule_skeleton, lesson_obj, TIME_SLOTS,
)

CONFIDENCE_THRESHOLD = 0.65


class PDFParser(BaseParser):
    def parse(self, source: str | bytes) -> ParseResult:
        path = source if isinstance(source, str) else _bytes_to_tmp(source, ".pdf")

        result = self._try_pdfplumber(path)
        if result.confidence >= CONFIDENCE_THRESHOLD:
            return result

        result = self._try_camelot(path)
        if result.confidence >= CONFIDENCE_THRESHOLD:
            return result

        return self._try_claude(path)

    # ── уровень 1: pdfplumber ─────────────────────────────────────────────────

    def _try_pdfplumber(self, path: str) -> ParseResult:
        try:
            with pdfplumber.open(path) as pdf:
                all_tables = []
                for page in pdf.pages:
                    tables = page.extract_tables({
                        "vertical_strategy": "lines",
                        "horizontal_strategy": "lines",
                        "intersection_tolerance": 5,
                    })
                    all_tables.extend(tables or [])

                if not all_tables:
                    return ParseResult(groups=[], parser_used="pdfplumber", confidence=0.0,
                                       warnings=["Таблицы не найдены"])

                groups = _parse_tables(all_tables)
                confidence = _compute_confidence(groups)
                return ParseResult(groups=groups, parser_used="pdfplumber", confidence=confidence)
        except Exception as e:
            return ParseResult(groups=[], parser_used="pdfplumber", confidence=0.0,
                               warnings=[str(e)])

    # ── уровень 2: camelot ────────────────────────────────────────────────────

    def _try_camelot(self, path: str) -> ParseResult:
        try:
            import camelot
            tables = camelot.read_pdf(path, pages="all", flavor="lattice")
            if not tables or len(tables) == 0:
                tables = camelot.read_pdf(path, pages="all", flavor="stream")

            raw_tables = [t.df.values.tolist() for t in tables]
            groups = _parse_tables(raw_tables)
            confidence = _compute_confidence(groups)
            return ParseResult(groups=groups, parser_used="camelot", confidence=confidence)
        except Exception as e:
            return ParseResult(groups=[], parser_used="camelot", confidence=0.0,
                               warnings=[str(e)])

    # ── уровень 3: Claude vision ──────────────────────────────────────────────

    def _try_claude(self, path: str) -> ParseResult:
        try:
            from scraper.utils.claude_client import ClaudeClient
            client = ClaudeClient()
            raw = client.parse_pdf_pages(path)
            groups = raw.get("groups", [])
            confidence = 0.85 if groups else 0.0
            return ParseResult(groups=groups, parser_used="claude", confidence=confidence,
                               warnings=["Использован Claude vision fallback"])
        except Exception as e:
            return ParseResult(groups=[], parser_used="claude", confidence=0.0,
                               warnings=[f"Claude fallback провалился: {e}"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _bytes_to_tmp(data: bytes, ext: str) -> str:
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=ext)
    os.write(fd, data)
    os.close(fd)
    return path


def _parse_tables(tables: list[list[list]]) -> list[dict]:
    """Определяет формат таблицы и парсит группы."""
    groups = []
    for table in tables:
        if not table or len(table) < 2:
            continue
        header = [str(c or "").strip().lower() for c in table[0]]

        if _is_day_column_format(header):
            groups.extend(_parse_day_columns(table))
        elif _is_day_row_format(header):
            groups.extend(_parse_day_rows(table))
        else:
            # пробуем эвристически
            groups.extend(_parse_heuristic(table))

    return groups


def _is_day_column_format(header: list[str]) -> bool:
    """Заголовок содержит дни недели как столбцы."""
    day_keywords = {"понедельник", "пн", "вторник", "вт", "среда", "ср",
                    "четверг", "чт", "пятница", "пт", "суббота", "сб"}
    matches = sum(1 for h in header if any(d in h for d in day_keywords))
    return matches >= 3


def _is_day_row_format(header: list[str]) -> bool:
    """Заголовок содержит 'день', 'время', 'предмет'."""
    kw = {"день", "время", "предмет", "дисциплина", "преподаватель", "аудитор"}
    return sum(1 for h in header if any(k in h for k in kw)) >= 2


def _parse_day_columns(table: list[list]) -> list[dict]:
    """Формат: первый столбец — время, остальные — дни недели."""
    header = [str(c or "").strip() for c in table[0]]
    day_indices = {}
    for i, h in enumerate(header):
        day = normalize_day(h)
        if day:
            day_indices[i] = day

    schedule = make_schedule_skeleton()
    current_time = None

    for row in table[1:]:
        if not row:
            continue
        time_raw = str(row[0] or "").strip()
        if time_raw:
            parsed = normalize_time(time_raw)
            if parsed:
                current_time = parsed

        if current_time is None:
            continue

        for col_i, day in day_indices.items():
            if col_i >= len(row):
                continue
            cell = str(row[col_i] or "").strip()
            if not cell:
                continue

            for lesson in _parse_cell(cell, current_time[0], current_time[1]):
                week = lesson.pop("_week", "both")
                if week in ("odd", "both"):
                    schedule["odd_week"][day].append(lesson)
                if week in ("even", "both"):
                    schedule["even_week"][day].append({**lesson})

    if not any(schedule["odd_week"][d] for d in schedule["odd_week"]):
        return []

    return [{
        "name": "группа",
        "year": None,
        "form": "full_time",
        "degree": "bachelor",
        "schedule": schedule,
    }]


def _parse_day_rows(table: list[list]) -> list[dict]:
    """Формат: каждая строка — одно занятие с колонками день/время/предмет/..."""
    header = [str(c or "").strip().lower() for c in table[0]]

    col = {
        "day": _find_col(header, ["день", "дн"]),
        "time": _find_col(header, ["время", "пара"]),
        "subject": _find_col(header, ["предмет", "дисциплина", "название"]),
        "type": _find_col(header, ["вид", "тип", "форма"]),
        "teacher": _find_col(header, ["преподаватель", "педагог", "фио"]),
        "room": _find_col(header, ["аудитор", "кабинет", "зал"]),
        "group": _find_col(header, ["группа"]),
    }

    groups_data: dict[str, dict] = {}

    for row in table[1:]:
        if not row:
            continue

        day_raw = _get(row, col["day"])
        day = normalize_day(day_raw) if day_raw else None
        if not day:
            continue

        time_raw = _get(row, col["time"]) or ""
        times = normalize_time(time_raw)
        if not times:
            continue

        subject = _get(row, col["subject"]) or ""
        lesson_type = normalize_lesson_type(_get(row, col["type"]) or subject)
        teacher = _get(row, col["teacher"])
        room = _get(row, col["room"])
        group_name = _get(row, col["group"]) or "группа"

        lesson = lesson_obj(None, times[0], times[1], subject, lesson_type, teacher, room)

        if group_name not in groups_data:
            groups_data[group_name] = {
                "name": group_name,
                "year": None,
                "form": "full_time",
                "degree": "bachelor",
                "schedule": make_schedule_skeleton(),
            }

        groups_data[group_name]["schedule"]["odd_week"][day].append(lesson)
        groups_data[group_name]["schedule"]["even_week"][day].append({**lesson})

    return list(groups_data.values())


def _parse_heuristic(table: list[list]) -> list[dict]:
    """Последний шанс — пробуем угадать формат по содержимому."""
    # если первая колонка содержит времена — это day_columns без заголовка дней
    first_col = [str(r[0] or "") for r in table if r]
    has_times = sum(1 for c in first_col if re.search(r"\d{1,2}:\d{2}", c)) >= 3
    if has_times:
        return _parse_day_columns(table)
    return []


def _parse_cell(cell: str, time_start: str, time_end: str) -> list[dict]:
    """Парсит содержимое одной ячейки расписания."""
    if not cell or cell in {"-", "–", "—", "."}:
        return []

    week_type = "both"
    # ищем признаки чётности (числитель/знаменатель)
    week_m = re.search(r"\b(числ[а-я]*|знам[а-я]*|н/|з/|н\b|з\b)\b", cell, re.I)
    if week_m:
        week_type = normalize_week_type(week_m.group(1))
        cell = cell[:week_m.start()] + cell[week_m.end():]

    lesson_type = normalize_lesson_type(cell)

    # ищем аудиторию: А-101, ауд.205, 3-17
    room_m = re.search(r"(?:ауд\.?\s*)?([\wА-Яа-я]-?\d{2,4})", cell, re.I)
    room = room_m.group(1) if room_m else None

    # убираем из текста аудиторию и тип занятия
    clean = cell
    if room_m:
        clean = clean[:room_m.start()] + clean[room_m.end():]
    for key in ["лек", "лекция", "практ", "практика", "лаб", "семинар", "пр."]:
        clean = re.sub(rf"\b{key}\b\.?", "", clean, flags=re.I)
    clean = clean.strip(" ,;\n")

    lesson = lesson_obj(None, time_start, time_end, clean, lesson_type, None, room)
    lesson["_week"] = week_type
    return [lesson]


def _find_col(header: list[str], keywords: list[str]) -> int | None:
    for i, h in enumerate(header):
        if any(k in h for k in keywords):
            return i
    return None


def _get(row: list, col: int | None) -> str | None:
    if col is None or col >= len(row):
        return None
    v = row[col]
    return str(v).strip() if v is not None else None


def _compute_confidence(groups: list[dict]) -> float:
    if not groups:
        return 0.0
    total_lessons = sum(
        sum(len(lessons) for day_lessons in g["schedule"]["odd_week"].values()
            for lessons in [day_lessons])
        for g in groups
    )
    if total_lessons == 0:
        return 0.1
    # эвристика: больше 5 занятий в неделю → хорошая уверенность
    confidence = min(1.0, total_lessons / 20)
    return round(confidence, 2)
