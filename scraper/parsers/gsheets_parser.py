"""Парсер Google Sheets (публичные таблицы через CSV экспорт)."""
import csv
import io
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import aiohttp

from scraper.parsers.base import BaseParser, ParseResult
from scraper.normalizer.schedule_normalizer import (
    normalize_day, normalize_lesson_type, normalize_time,
    normalize_week_type, make_schedule_skeleton, lesson_obj, extract_subgroup,
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
            with open(source, encoding="utf-8", errors="replace") as f:
                text = f.read()
        try:
            rows = list(csv.reader(io.StringIO(text)))
            groups = _parse_csv_rows(rows)
            confidence = _compute_confidence(groups)
            return ParseResult(groups=groups, parser_used="gsheets", confidence=confidence)
        except Exception as e:
            return ParseResult(groups=[], parser_used="gsheets", confidence=0.0,
                               warnings=[str(e)])


_GROUP_RE = re.compile(r"[А-ЯЁA-Z]{2,5}\d{2}-[А-ЯЁA-Z]{2,4}\d{4}")
_TIME_RE = re.compile(r"(\d{1,2})[\.:](\d{2})\s*[-–]\s*(\d{1,2})[\.:](\d{2})")
_SKIP_PHRASES = {"самостоятельных занятий", "день самостоятельных"}
_SKIP_CELLS = {"—", "-", "–"}


def _parse_csv_rows(rows: list[list[str]]) -> list[dict]:
    if not rows:
        return []

    # Формат МПГУ-ИСГО: «день недели и дата» в col0, группы в col2+
    isgo_idx = _find_isgo_header(rows)
    if isgo_idx is not None:
        return _parse_isgo(rows, isgo_idx)

    # Классический формат: дни как столбцы
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


# ── формат МПГУ-ИСГО ─────────────────────────────────────────────────────────

def _find_isgo_header(rows: list[list[str]]) -> int | None:
    for i, row in enumerate(rows[:20]):
        if any("недели и дата" in c.lower() or "день недели" in c.lower() for c in row):
            return i
    return None


def _parse_time_str(text: str) -> tuple[str, str] | None:
    text = text.strip().rstrip("\r\n")
    m = _TIME_RE.search(text)
    if not m:
        return None
    t_start = f"{int(m.group(1)):02d}:{m.group(2)}"
    t_end = f"{int(m.group(3)):02d}:{m.group(4)}"
    return t_start, t_end


def _parse_isgo(rows: list[list[str]], header_idx: int) -> list[dict]:
    header = rows[header_idx]

    # Определяем колонки с группами (начиная с col2)
    group_cols: dict[int, str] = {}
    for ci, cell in enumerate(header):
        if ci < 2:
            continue
        name = cell.strip()
        if _GROUP_RE.match(name):
            group_cols[ci] = name

    if not group_cols:
        return []

    schedules: dict[str, dict] = {n: make_schedule_skeleton() for n in group_cols.values()}
    # seen: предотвращаем дублирование одинаковых занятий
    seen: dict[tuple, set] = {}

    current_day: str | None = None
    current_time: tuple[str, str] | None = None
    col_offset = 0  # 0: занятие в group_cols[ci]; -1: сдвинуто влево

    for row in rows[header_idx + 1:]:
        if not any(c.strip() for c in row):
            continue

        c0 = row[0].strip() if row else ""
        c1 = row[1].strip().rstrip("\r\n") if len(row) > 1 else ""

        # Пропускаем строки с «днём самоподготовки»
        combined = (c0 + " " + c1).lower()
        if any(s in combined for s in _SKIP_PHRASES):
            continue

        # Определяем день (первая строка col0 до переноса)
        first_line_c0 = c0.split("\n")[0].strip().lower()
        day = normalize_day(first_line_c0)
        if day:
            current_day = day
            col_offset = 0

        # Определяем время: в формате ИСГО оно всегда в col1
        t = _parse_time_str(c1)
        if t:
            current_time = t
            col_offset = 0
        elif not day:
            # col0 может быть временем (другие форматы)
            t = _parse_time_str(c0)
            if t:
                current_time = t
                col_offset = -1 if c1 and not _parse_time_str(c1) else 0

        if not current_day or not current_time:
            continue

        # Собираем занятия из колонок групп (с учётом сдвига)
        slot_key = (current_day, current_time[0])
        for col_idx, gname in group_cols.items():
            effective = col_idx + col_offset
            if effective < 0 or effective >= len(row):
                continue
            content = row[effective].strip()
            if not content or content in _SKIP_CELLS or any(s in content.lower() for s in _SKIP_PHRASES):
                continue
            # Дедупликация
            sk = (slot_key, gname)
            if sk not in seen:
                seen[sk] = set()
            if content in seen[sk]:
                continue
            seen[sk].add(content)

            lesson = _parse_isgo_cell(content, current_time[0], current_time[1])
            if lesson:
                schedules[gname]["odd_week"][current_day].append(lesson)
                schedules[gname]["even_week"][current_day].append({**lesson})

    result = []
    for name, sched in schedules.items():
        if any(sched["odd_week"][d] for d in sched["odd_week"]):
            result.append({"name": name, "year": None, "form": "part_time",
                           "degree": "bachelor", "schedule": sched})
    return result


_TEACHER_TITLE_RE = re.compile(
    r"\b(проф|доц|ст\.?\s*преп|асс|преп)\.?\s", re.IGNORECASE
)
_ROOM_RE = re.compile(r"\(ауд\.?\s*([\w\-]+)\)", re.IGNORECASE)
_TYPE_BRACKET_RE = re.compile(r"\(([А-ЯЁа-яёA-Za-z./]{2,6})[\s\d/]*\)")
_TYPE_MAP = {
    "лк": "lecture", "пз": "practice", "лаб": "lab", "лб": "lab",
    "сем": "seminar", "сем.": "seminar", "лаб.": "lab",
}


def _parse_isgo_cell(content: str, t_start: str, t_end: str) -> dict | None:
    """Парсит ячейку занятия формата ИСГО.

    Форматы:
    - 'Название (ЛК 16) доц. Иванов 01.09; 15.09. (ауд. 826)'  — одна строка
    - 'Название (ЛК 16)\nдоц. Иванов // ауд. 826'              — через '//'
    """
    if not content or content in {"-", "–", "—"}:
        return None
    lines = [ln.strip() for ln in content.replace("\r", "").split("\n") if ln.strip()]
    if not lines:
        return None

    lesson_type = "other"
    teacher: str | None = None
    room: str | None = None

    # Сканируем все строки для определения типа и комнаты
    for line in lines:
        for m in _TYPE_BRACKET_RE.finditer(line):
            t = _TYPE_MAP.get(m.group(1).lower())
            if t:
                lesson_type = t

        rm = _ROOM_RE.search(line)
        if rm and room is None:
            room = rm.group(1)

        if "//" in line:
            parts = line.split("//", 1)
            left, right = parts[0].strip(), parts[1].strip()
            if _TEACHER_TITLE_RE.search(left) and teacher is None:
                teacher = _clean_teacher(left)
            if right and room is None:
                # Правая часть после '//' — аудитория
                room = re.sub(r"(?i)ауд\.?\s*", "", right).strip(" .,()")

    # Извлекаем subject и teacher из первой строки
    first = lines[0]
    title_m = _TEACHER_TITLE_RE.search(first)
    if title_m and teacher is None:
        teacher = _clean_teacher(first[title_m.start():])
        subject_raw = first[:title_m.start()]
    else:
        subject_raw = first

    # Убираем скобки с типом занятия и лишние пробелы; извлекаем подгруппу
    subject = _TYPE_BRACKET_RE.sub("", subject_raw).strip(" ,.")
    subject, subgroup = extract_subgroup(subject)
    if not subject:
        return None

    return lesson_obj(None, t_start, t_end, subject, lesson_type, teacher, room, subgroup)


def _clean_teacher(text: str) -> str:
    """Убирает даты, аудиторию и лишние символы из строки с преподавателем."""
    # Убираем "(ауд. 826)" и подобное
    text = _ROOM_RE.sub("", text)
    # Убираем даты типа "01.09; 16.09; ..."
    text = re.sub(r"\b\d{2}\.\d{2}[;,]?", "", text)
    # Убираем скобки с типом занятия
    text = _TYPE_BRACKET_RE.sub("", text)
    return text.strip(" .,()")


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
