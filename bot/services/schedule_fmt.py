from datetime import date

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_RU = {
    "monday": "Понедельник", "tuesday": "Вторник", "wednesday": "Среда",
    "thursday": "Четверг", "friday": "Пятница", "saturday": "Суббота",
    "sunday": "Воскресенье",
}
TYPE_RU = {"lecture": "ЛК", "practice": "ПЗ", "lab": "ЛР", "seminar": "СЕМ", "other": ""}


def _esc(s) -> str:
    return (str("" if s is None else s)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def get_current_week_key(d: date | None = None) -> str:
    if d is None:
        import datetime
        d = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).date()
    return "even_week" if d.isocalendar()[1] % 2 == 0 else "odd_week"


def format_day(day: str, lessons: list[dict], even_week: bool) -> str:
    week_label = "чётная" if even_week else "нечётная"
    head = f"📅 <b>{DAY_RU.get(day, day)}</b> · {week_label} неделя"

    if not lessons:
        return f"{head}\n\nЗанятий нет 🎉"

    sorted_lessons = sorted(lessons, key=lambda l: l.get("time_start") or "")
    parts = []
    for l in sorted_lessons:
        type_label = TYPE_RU.get(l.get("type", ""), "")
        type_str = f" ({type_label})" if type_label else ""
        t_start = l.get("time_start") or ""
        t_end = l.get("time_end") or ""
        time_str = f"{t_start}–{t_end}" if t_end else t_start
        extra = ", ".join(_esc(x) for x in (l.get("teacher"), l.get("room")) if x)
        subgroup = l.get("subgroup")
        sg_str = f" [п/г {subgroup}]" if subgroup else ""
        parts.append(
            f"🕐 <b>{time_str}</b> {_esc(l.get('subject', ''))}{type_str}{sg_str}"
            + (f"\n   {extra}" if extra else "")
        )
    return head + "\n\n" + "\n\n".join(parts)


def format_today(group_data: dict) -> str:
    import datetime
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
    day = DAYS[now.weekday()]
    week_key = get_current_week_key(now.date())
    even = week_key == "even_week"
    lessons = ((group_data.get("schedule") or {}).get(week_key) or {}).get(day) or []
    name_line = f"👤 <b>{_esc(group_data.get('name', ''))}</b>\n"
    return name_line + format_day(day, lessons, even)


def format_tomorrow(group_data: dict) -> str:
    import datetime
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
    tomorrow = now.date() + datetime.timedelta(days=1)
    day = DAYS[tomorrow.weekday()]
    week_key = get_current_week_key(tomorrow)
    even = week_key == "even_week"
    lessons = ((group_data.get("schedule") or {}).get(week_key) or {}).get(day) or []
    name_line = f"👤 <b>{_esc(group_data.get('name', ''))}</b>\n"
    return name_line + format_day(day, lessons, even)


def format_week(group_data: dict) -> str:
    import datetime
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
    week_key = get_current_week_key(now.date())
    even = week_key == "even_week"
    schedule = (group_data.get("schedule") or {}).get(week_key) or {}
    parts = [f"👤 <b>{_esc(group_data.get('name', ''))}</b> · {'чётная' if even else 'нечётная'} неделя\n"]
    for day in DAYS[:6]:  # пн–сб
        lessons = schedule.get(day) or []
        parts.append(format_day(day, lessons, even))
    return "\n\n".join(parts)
