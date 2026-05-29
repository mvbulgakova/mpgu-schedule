"""Приводит сырые данные парсеров к единой схеме."""
import re
from datetime import datetime, date as date_type

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

# стандартные временные слоты МПГУ (актуальная звонковая сетка основного корпуса)
TIME_SLOTS = {
    1: ("09:00", "10:30"),
    2: ("10:40", "12:10"),
    3: ("12:40", "14:10"),
    4: ("14:20", "15:50"),
    5: ("16:00", "17:30"),
    6: ("17:40", "19:10"),
    7: ("19:20", "20:50"),
}

WEEK_ODD = {"числитель", "числ", "н", "н/", "над", "нечётная", "нечетная", "i", "1"}
WEEK_EVEN = {"знаменатель", "знам", "з", "з/", "под", "чётная", "четная", "ii", "2"}

_TEACHER_TITLE_RE = re.compile(
    r"((?:проф|доц|ст\.?\s*преп(?:од)?|ассистент|ассист|асс|преп)\.?\s+"
    r"[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ]\.[А-ЯЁ]\.?)?)",
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
    aud = re.search(r"ауд\.?\s*(\S+)", remainder, re.I)
    if aud:
        room = aud.group(0).strip()
    else:
        num = re.search(r"\b\d{2,}\b", remainder)
        room = num.group(0) if num else None
    return room, teacher


# Подгруппы: (п/г 1), (1 п/г), (подгр. 2), (подгруппа 2)
_SUBGROUP_RE = re.compile(
    r"\(\s*(?:п[/.]?\s*г\.?|подгр(?:уппа)?\.?)\s*(\d+)\s*\)"
    r"|\(\s*(\d+)\s*[-–]?\s*(?:я\s*)?(?:п[/.]?\s*г\.?|подгр(?:уппа)?\.?)\s*\)",
    re.IGNORECASE,
)


def extract_subgroup(text: str) -> tuple[str, int | None]:
    """Вытаскивает номер подгруппы из текста; возвращает (очищенный текст, номер или None)."""
    m = _SUBGROUP_RE.search(text)
    if not m:
        return text, None
    sg = int(m.group(1) or m.group(2))
    cleaned = (text[: m.start()] + text[m.end() :]).strip(" ,.")
    return cleaned, sg


def date_str_to_weekday(s: str) -> str | None:
    """Конвертирует строку даты 'DD.MM.YYYY', 'DD.MM.YY' или 'DD.MM' в день недели."""
    s = s.strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%d.%m"):
        try:
            dt = datetime.strptime(s, fmt)
            if fmt == "%d.%m":
                dt = dt.replace(year=datetime.now().year)
            days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            return days[dt.weekday()]
        except ValueError:
            continue
    return None


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
    return {
        "slot": slot,
        "time_start": time_start,
        "time_end": time_end,
        "subject": subject.strip(),
        "type": lesson_type,
        "teacher": teacher.strip() if teacher else None,
        "room": room.strip() if room else None,
        "subgroup": subgroup,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Финальная очистка (применяется ко всем парсерам перед записью в data-ветку)
# ---------------------------------------------------------------------------

# Подгруппа без скобок: "1 п/гр", "2 п/г", "п/г 1", "подгр. 2", "1-я подгруппа"
_SUBGROUP_LOOSE_RE = re.compile(
    r"(?<!\w)(\d)\s*[-–]?\s*(?:я\s+)?п[/.]?\s*г(?:р|руппа)?\.?(?!\w)"
    r"|(?<!\w)п[/.]?\s*г(?:р|руппа)?\.?\s*[№#]?\s*(\d)(?!\w)",
    re.IGNORECASE,
)

# Префикс "ауд." / "ауд" перед номером аудитории
_AUD_PREFIX_RE = re.compile(r"ауд(?:итория)?\.?\s*", re.IGNORECASE)


def pull_subgroup(text: str | None) -> tuple[str | None, int | None]:
    """Достаёт номер подгруппы (скобочный или свободный формат) и чистит текст."""
    if not text:
        return text, None
    cleaned, sg = extract_subgroup(text)  # скобочный формат: (п/г 1)
    if sg is not None:
        return cleaned, sg
    # Свободный паттерн ("1 п/гр") применяем только к коротким полям —
    # в длинных слепленных ячейках он ловит ложные совпадения.
    if len(text) > 60:
        return text, None
    m = _SUBGROUP_LOOSE_RE.search(text)
    if not m:
        return text, None
    sg = int(m.group(1) or m.group(2))
    cleaned = text[: m.start()] + text[m.end() :]
    # не срезаем точку — она часть инициалов ("О.И.")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;")
    return cleaned, sg


def clean_room(room: str | None) -> str | None:
    """Убирает префикс 'ауд.' и мусор перед ним.

    PWA сама дописывает 'ауд. ' перед номером, поэтому 'ауд. 403' в данных
    превращается в 'ауд. ауд. 403'. Берём всё после последнего маркера 'ауд.'.
    Залы, онлайн-ссылки и буквенные значения (без 'ауд') не трогаем.
    """
    if not room:
        return None
    r = room.strip()
    if "ауд" not in r.lower():
        return r or None
    # Заменяем маркеры "ауд." пробелом, сохраняя несколько аудиторий
    # ("332 / ауд. 333" -> "332 / 333", "411ауд. 302" -> "411 302").
    r = _AUD_PREFIX_RE.sub(" ", r)
    r = re.sub(r"\s{2,}", " ", r).strip(" ,;/")
    return r or None


def sanitize_lesson(lesson: dict) -> dict:
    """Финальная нормализация одной пары независимо от парсера-источника."""
    subject = (lesson.get("subject") or "").strip()
    teacher = lesson.get("teacher")
    room = lesson.get("room")
    notes = (lesson.get("notes") or "").strip()
    subgroup = lesson.get("subgroup")

    # 1. Если в room затесались "Звание Фамилия И.О." — вынести в teacher
    room, teacher = _split_room_teacher(room, teacher)

    # 2. Вытащить подгруппу из любого поля и убрать токен везде, где встретился
    found_sg = subgroup
    subject, sg = pull_subgroup(subject)
    if found_sg is None:
        found_sg = sg
    if teacher:
        teacher, sg = pull_subgroup(teacher)
        if found_sg is None:
            found_sg = sg
    if room:
        room, sg = pull_subgroup(room)
        if found_sg is None:
            found_sg = sg
    if notes:
        notes, sg = pull_subgroup(notes)
        if found_sg is None:
            found_sg = sg
    subgroup = found_sg

    # 3. Почистить аудиторию ("ауд. 403" -> "403", "Имя, ауд. 301" -> "301")
    room = clean_room(room)

    teacher = teacher.strip(" ,;") if teacher else None
    room = room.strip(" ,;") if room else None

    # 4. Достроить slot из времени, если не задан
    slot = lesson.get("slot")
    if slot is None and lesson.get("time_start"):
        slot = infer_slot(lesson["time_start"])

    return {
        "slot": slot,
        "time_start": lesson.get("time_start"),
        "time_end": lesson.get("time_end"),
        "subject": subject,
        "type": lesson.get("type", "other"),
        "teacher": teacher or None,
        "room": room or None,
        "subgroup": subgroup,
        "notes": notes,
    }


def _lesson_key(l: dict) -> tuple:
    return (
        l.get("time_start"), l.get("time_end"), l.get("subject"),
        l.get("type"), l.get("teacher"), l.get("room"),
        l.get("subgroup"), l.get("notes"),
    )


# Латинские буквы, визуально идентичные кириллическим (гомоглифы).
# Коды групп МПГУ всегда кириллические, но vision/OCR часто подставляет
# латиницу ("БOМ35" с латинской O). Нормализуем ТОЛЬКО в именах групп —
# в предметах/преподавателях латиница может быть легитимной.
_HOMOGLYPHS = str.maketrans({
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
})


def fix_homoglyphs(name: str) -> str:
    """Заменяет латинские гомоглифы на кириллицу в коде группы."""
    return name.translate(_HOMOGLYPHS) if name else name


def sanitize_groups(groups: list[dict]) -> list[dict]:
    """Чистит расписание всех групп: имена (гомоглифы), подгруппы, аудитории,
    slot, удаление точных дублей и сортировка пар внутри дня по времени.
    Мутирует и возвращает тот же список."""
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for group in groups:
        if group.get("name"):
            group["name"] = fix_homoglyphs(group["name"]).strip()
        schedule = group.get("schedule") or {}
        for week_key in ("odd_week", "even_week"):
            week = schedule.get(week_key)
            if not week:
                continue
            for day in days:
                lessons = week.get(day)
                if not lessons:
                    continue
                cleaned: list[dict] = []
                seen: set[tuple] = set()
                for raw in lessons:
                    lesson = sanitize_lesson(raw)
                    key = _lesson_key(lesson)
                    if key in seen:
                        continue
                    seen.add(key)
                    cleaned.append(lesson)
                cleaned.sort(key=lambda l: (l.get("time_start") or "99:99", l.get("slot") or 99))
                week[day] = cleaned
    return groups
