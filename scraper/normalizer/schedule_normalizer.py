"""Приводит сырые данные парсеров к единой схеме."""
import re
from datetime import datetime

DAY_NAMES = {
    "понедельник": "monday", "пн": "monday", "пон": "monday",
    "вторник": "tuesday", "вт": "tuesday",
    "среда": "wednesday", "ср": "wednesday",
    "четверг": "thursday", "чт": "thursday",
    "пятница": "friday", "пт": "friday",
    "суббота": "saturday", "сб": "saturday",
}

LESSON_TYPES = {
    "лекция": "lecture", "лек": "lecture", "лек.": "lecture", "лк": "lecture",
    "практика": "practice", "пр": "practice", "пр.": "practice", "практ": "practice", "пз": "practice",
    "лабораторная": "lab", "лаб": "lab", "лаб.": "lab",
    "семинар": "seminar", "сем": "seminar", "сем.": "seminar",
}

# стандартные временные слоты МПГУ
TIME_SLOTS = {
    1: ("08:00", "09:35"),
    2: ("09:45", "11:20"),
    3: ("11:30", "13:05"),
    4: ("13:30", "15:05"),
    5: ("15:15", "16:50"),
    6: ("17:00", "18:35"),
    7: ("18:45", "20:20"),
    8: ("20:30", "22:05"),
}

WEEK_ODD = {"числитель", "числ", "н", "н/", "над", "нечётная", "нечетная", "i", "1"}
WEEK_EVEN = {"знаменатель", "знам", "з", "з/", "под", "чётная", "четная", "ii", "2"}

_TEACHER_TITLE_RE = re.compile(
    r"((?:проф|доц|ст\.?\s*преп|асс|преп)\.?\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ]\.[А-ЯЁ]\.?)?)",
    re.IGNORECASE,
)


def _split_room_teacher(room: str | None, teacher: str | None) -> tuple[str | None, str | None]:
    """If room contains an academic title + name, extract teacher and leave only room number."""
    if not room:
        return room, teacher
    m = _TEACHER_TITLE_RE.search(room)
    if not m:
        return room, teacher
    if teacher is None:
        teacher = m.group(1).strip().rstrip(",. ")
    remainder = (room[: m.start()] + room[m.end() :]).strip(" ,")
    # keep "ауд. NNN" or bare room number
    aud = re.search(r"ауд\.?\s*(\S+)", remainder, re.I)
    if aud:
        room = aud.group(0).strip()
    else:
        num = re.search(r"\b\d{2,}\b", remainder)
        room = num.group(0) if num else None
    return room, teacher


def normalize_day(raw: str) -> str | None:
    key = raw.strip().lower().rstrip(".")
    return DAY_NAMES.get(key)


def normalize_lesson_type(raw: str) -> str:
    for key, val in LESSON_TYPES.items():
        if key in raw.lower():
            return val
    return "other"


def normalize_time(raw: str) -> tuple[str, str] | None:
    """Возвращает (time_start, time_end) в формате HH:MM."""
    raw = raw.strip().replace(".", ":")
    # формат "08:00-09:35" или "8:00 - 9:35" или "09:00\n10:30" (времена на отдельных строках)
    raw = re.sub(r"(\d{1,2}:\d{2})\n(\d{1,2}:\d{2})", r"\1-\2", raw)
    m = re.match(r"(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})", raw)
    if m:
        return _pad_time(m.group(1)), _pad_time(m.group(2))
    # только начало "08:00"
    m = re.match(r"^(\d{1,2}:\d{2})$", raw)
    if m:
        t = _pad_time(m.group(1))
        return t, _derive_end_time(t)
    # номер пары "1" или "1 пара"
    m = re.match(r"^(\d)[\s\w]*$", raw)
    if m:
        slot = int(m.group(1))
        if slot in TIME_SLOTS:
            return TIME_SLOTS[slot]
    return None


def _pad_time(t: str) -> str:
    h, m = t.split(":")
    return f"{int(h):02d}:{m}"


def _derive_end_time(start: str) -> str:
    for _, (s, e) in TIME_SLOTS.items():
        if s == start:
            return e
    return ""


def infer_slot(time_start: str) -> int | None:
    for slot, (s, _) in TIME_SLOTS.items():
        if s == time_start:
            return slot
    return None


def normalize_week_type(raw: str) -> str:
    """odd / even / both"""
    key = raw.strip().lower().rstrip(".")
    if key in WEEK_ODD:
        return "odd"
    if key in WEEK_EVEN:
        return "even"
    return "both"


def make_empty_week() -> dict:
    return {day: [] for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]}


def make_schedule_skeleton() -> dict:
    return {"odd_week": make_empty_week(), "even_week": make_empty_week()}


def lesson_obj(
    slot: int | None,
    time_start: str,
    time_end: str,
    subject: str,
    lesson_type: str,
    teacher: str | None,
    room: str | None,
    subgroup: int | None = None,
    notes: str = "",
) -> dict:
    if slot is None:
        slot = infer_slot(time_start)
    room_clean = room.strip() if room else None
    teacher_clean = teacher.strip() if teacher else None
    room_clean, teacher_clean = _split_room_teacher(room_clean, teacher_clean)
    return {
        "slot": slot,
        "time_start": time_start,
        "time_end": time_end,
        "subject": subject.strip(),
        "type": lesson_type,
        "teacher": teacher_clean,
        "room": room_clean,
        "subgroup": subgroup,
        "notes": notes,
    }
