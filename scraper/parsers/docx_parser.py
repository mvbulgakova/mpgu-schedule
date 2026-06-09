"""Парсер DOCX расписаний."""
import re

from docx import Document
from docx.table import Table

from scraper.parsers.base import BaseParser, ParseResult
from scraper.normalizer.schedule_normalizer import (
    normalize_day, normalize_lesson_type, normalize_time,
    normalize_week_type, make_schedule_skeleton, lesson_obj, extract_subgroup,
)

# Аббревиатуры типов занятий в скобках (как в ИПиП DOCX)
_TYPE_ABBR = {
    "лк": "lecture",
    "лек": "lecture",
    "пз": "practice",
    "прак": "practice",
    "лаб": "lab",
    "лб": "lab",
    "см": "seminar",
    "сем": "seminar",
    "семинар": "seminar",
}

# Ключевые слова должностей преподавателей
_TEACHER_PREFIXES = re.compile(
    r"^(доцент|проф\.|профессор|ст\.\s*преподаватель|ст\.преп\.|преподаватель|"
    r"асс\.|ассистент|доц\.|зав\.|академик|ст\.?\s*преп\.?)",
    re.IGNORECASE,
)


def _parse_multiline_cell(cell_text: str) -> dict:
    """Разбирает многострочный текст ячейки на поля subject/type/teacher/room/notes.

    Формат ИПиП:
      Строка 0: Название предмета (ТИП)
      Строка 1: Должность Фамилия И.О. [, Должность Фамилия И.О.]
      Строка 2+: Ауд. N[,M] или Каб. N
      Остальные: заметки (даты и т.п.)
    """
    lines = [l.strip() for l in cell_text.split("\n") if l.strip()]
    if not lines:
        return {"subject": "", "type": "other", "teacher": None, "room": None, "notes": ""}

    # --- Строка 0: предмет + тип в скобках ---
    subject_line = lines[0]
    lesson_type = "other"
    m = re.search(r"\(([^)]+)\)\s*$", subject_line)
    if m:
        abbr = m.group(1).strip().lower()
        if abbr in _TYPE_ABBR:
            lesson_type = _TYPE_ABBR[abbr]
            subject_line = subject_line[: m.start()].strip()
        else:
            guessed = normalize_lesson_type(abbr)
            if guessed != "other":
                lesson_type = guessed
                subject_line = subject_line[: m.start()].strip()

    subject_line, subgroup = extract_subgroup(subject_line)
    subject = subject_line

    teacher = None
    room = None
    note_parts = []

    for line in lines[1:]:
        # Проверка на аудиторию/кабинет
        if re.match(r"^(ауд|АУД|Ауд|каб|Каб|КАБ)\.?\s*\d", line) or re.match(
            r"^(ауд|АУД|Ауд|каб|Каб|КАБ)\.", line, re.IGNORECASE
        ):
            # "Ауд. 36,35" → "36,35"
            room_val = re.sub(r"^(ауд|каб)\.?\s*", "", line, flags=re.IGNORECASE).strip()
            room = room_val if room_val else None
            continue

        # Проверка на преподавателя
        if _TEACHER_PREFIXES.match(line):
            teacher = line
            continue

        # Остальное — заметки
        note_parts.append(line)

    notes = "; ".join(note_parts)
    return {
        "subject": subject,
        "type": lesson_type,
        "teacher": teacher,
        "room": room,
        "subgroup": subgroup,
        "notes": notes,
    }


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

            if "\n" in cell:
                parsed = _parse_multiline_cell(cell)
                lesson_type = parsed["type"]
                clean = parsed["subject"]
                teacher = parsed["teacher"]
                room = parsed["room"]
                sg = parsed["subgroup"]
                notes = parsed["notes"]
            else:
                lesson_type = normalize_lesson_type(cell)
                clean = re.sub(r"\bлек\b|\bпрактика\b|\bпр\b|\bлаб\b|\bсеминар\b", "", cell, flags=re.I).strip()
                clean, sg = extract_subgroup(clean)
                room_m = re.search(r"[\wА-Яа-я]-?\d{2,4}", clean)
                room = room_m.group(0) if room_m else None
                teacher = None
                notes = ""

            lesson = lesson_obj(None, current_time[0], current_time[1], clean, lesson_type, teacher, room, sg, notes=notes)
            if week_type in ("odd", "both"):
                schedule["odd_week"][day].append(lesson)
            if week_type in ("even", "both"):
                schedule["even_week"][day].append({**lesson})

    if not any(schedule["odd_week"][d] for d in schedule["odd_week"]):
        return []
    return [{"name": "группа", "year": None, "form": "full_time",
             "degree": "bachelor", "schedule": schedule}]


def _parse_multi_group_cols(table):
    """Handle tables where col0=day, col1=time, col2+=individual group schedules."""
    if len(table) < 4:
        return None
    # Find the row containing group names in cols 2+
    group_header_idx = None
    for ri, row in enumerate(table[:10]):
        found = any(
            re.search(r"\d{2,3}\s*ГРУППА", (row[ci] if ci < len(row) else ""), re.I)
            for ci in range(2, min(len(row), 12))
        )
        if found:
            group_header_idx = ri
            break
    if group_header_idx is None:
        return None
    group_header = table[group_header_idx]
    group_cols = {}  # col_idx -> name
    for ci in range(2, len(group_header)):
        cell = group_header[ci].strip() if ci < len(group_header) else ""
        if cell:
            group_cols[ci] = cell.split("\n")[0].strip().rstrip(":")
    if not group_cols:
        return None
    schedules = {name: make_schedule_skeleton() for name in group_cols.values()}
    for row in table[group_header_idx + 1:]:
        day = normalize_day(row[0]) if row else None
        if not day:
            continue
        times = normalize_time(row[1]) if len(row) > 1 else None
        if not times:
            continue
        for ci, name in group_cols.items():
            cell = row[ci].strip() if ci < len(row) else ""
            if not cell:
                continue
            week_m = re.search(r"\b(числ[а-я]*|знам[а-я]*|н/|з/)\b", cell, re.I)
            week_type = normalize_week_type(week_m.group(1)) if week_m else "both"

            if "\n" in cell:
                parsed = _parse_multiline_cell(cell)
                lesson_type = parsed["type"]
                subject = parsed["subject"]
                teacher = parsed["teacher"]
                room = parsed["room"]
                sg = parsed["subgroup"]
                notes = parsed["notes"]
            else:
                lesson_type = normalize_lesson_type(cell)
                subject, sg = extract_subgroup(cell)
                teacher = None
                room = None
                notes = ""

            lesson = lesson_obj(None, times[0], times[1], subject, lesson_type, teacher, room, sg, notes=notes)
            if week_type in ("odd", "both"):
                schedules[name]["odd_week"][day].append(lesson)
            if week_type in ("even", "both"):
                schedules[name]["even_week"][day].append({**lesson})
    result = [
        {"name": name, "year": None, "form": "full_time", "degree": "bachelor",
         "schedule": schedules[name]}
        for name in group_cols.values()
        if any(schedules[name]["odd_week"][d] for d in schedules[name]["odd_week"])
    ]
    return result if result else None


def _parse_flat(table):
    if len(table) < 2:
        return []
    multi = _parse_multi_group_cols(table)
    if multi is not None:
        return multi
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
        raw_subject = _get(row, col["subject"]) or ""
        raw_teacher = _get(row, col["teacher"])
        raw_room = _get(row, col["room"])

        # Если предмет содержит переносы строк — парсим многострочный формат ИПиП
        if "\n" in raw_subject:
            parsed = _parse_multiline_cell(raw_subject)
            subject = parsed["subject"]
            lesson_type = parsed["type"]
            teacher = raw_teacher or parsed["teacher"]
            room = raw_room or parsed["room"]
            notes = parsed["notes"]
        else:
            subject = raw_subject
            lesson_type = normalize_lesson_type(raw_subject) if raw_subject else "other"
            teacher = raw_teacher
            room = raw_room
            notes = ""

        lesson = lesson_obj(None, times[0], times[1], subject, lesson_type,
                            teacher, room, notes=notes)
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
