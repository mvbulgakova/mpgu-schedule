"""Parse Russian full names and generate abbreviated forms for schedule matching.

MPGU website displays names as "Имя Отчество Фамилия" (First Patronymic Last).
Schedules use "Фамилия И.О." abbreviated form.

Matching strategy:
  "Архипова Т.В."  → normalize → "архиповатв"
  "Архипова Т. В." → normalize → "архиповатв"
  "Архипова Татьяна Валентиновна" → abbreviated → "Архипова Т.В." → normalize → "архиповатв"
"""
import re

# Patronymic suffix pattern
_PATR_RE = re.compile(
    r"^[А-ЯЁ][а-яё]+(ович|евич|овна|евна|ийч|ийна|ьич|ична)$"
)

_ABBR_IN_NAME = re.compile(r"^[А-ЯЁ]\.$")


def parse_name(full_name: str) -> dict:
    """
    Parse a 2-3 word Russian name into components.

    Returns dict with keys: first, patronymic, last, abbreviated.
    abbreviated = "Фамилия И.О." (used for schedule matching).
    """
    parts = full_name.strip().split()
    if not parts:
        return _empty(full_name)

    if len(parts) == 1:
        return {"first": "", "patronymic": "", "last": parts[0], "abbreviated": parts[0]}

    # Find patronymic index by suffix
    patr_idx: int | None = None
    for i, p in enumerate(parts):
        if _PATR_RE.match(p):
            patr_idx = i
            break

    if patr_idx is None:
        # No patronymic - 2-word name
        first, last = parts[0], parts[-1]
        return {
            "first": first,
            "patronymic": "",
            "last": last,
            "abbreviated": f"{last} {first[0]}." if first else last,
        }

    patronymic = parts[patr_idx]

    if patr_idx == 1 and len(parts) >= 3:
        # "Имя Отчество Фамилия" — MPGU website format
        first, last = parts[0], parts[2]
    elif patr_idx == 2 and len(parts) >= 3:
        # "Фамилия Имя Отчество"
        last, first = parts[0], parts[1]
    else:
        first = parts[0] if patr_idx > 0 else (parts[1] if len(parts) > 1 else "")
        last = parts[-1] if patr_idx < len(parts) - 1 else parts[0]

    abbreviated = (
        f"{last} {first[0]}.{patronymic[0]}."
        if last and first and patronymic
        else full_name
    )
    return {
        "first": first,
        "patronymic": patronymic,
        "last": last,
        "abbreviated": abbreviated,
    }


def _empty(raw: str) -> dict:
    return {"first": "", "patronymic": "", "last": raw, "abbreviated": raw}


_TITLE_PREFIX_RE = re.compile(
    r"^(?:проф|доц|ст\.?\s*преп(?:одаватель)?|асс(?:истент)?|преп(?:одаватель)?)\s*\.?\s+",
    re.IGNORECASE,
)


def match_key(name: str) -> str:
    """
    Produce a canonical key for matching:
    "Архипова Т.В." → "архиповатв"
    "Архипова Татьяна Валентиновна" → "архиповатв"
    "доц. Архипова Т.В." → "архиповатв"
    """
    name = _TITLE_PREFIX_RE.sub("", name.strip())
    parts = name.split()
    # If looks like a full name (3 parts with patronymic), abbreviate first
    if len(parts) >= 3:
        parsed = parse_name(name)
        name = parsed["abbreviated"]
    # Strip all non-letter characters, lowercase
    return re.sub(r"[^а-яёa-z]", "", name.lower())


def match_teacher(schedule_name: str, db: list[dict]) -> dict | None:
    """
    Find the best match in db for a schedule name like "Архипова Т.В."
    Returns the teacher record or None.

    Tries exact match first, then prefix match (in case patronymic is missing).
    """
    if not schedule_name:
        return None
    target = match_key(schedule_name)
    if not target:
        return None

    for t in db:
        if t.get("_key") == target:
            return t

    # Prefix: schedule may omit patronymic "Архипова Т." → target = "архиповат"
    for t in db:
        key = t.get("_key", "")
        if key and len(target) >= 6 and (key.startswith(target) or target.startswith(key)):
            return t

    return None
