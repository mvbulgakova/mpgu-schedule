"""Генерирует iCalendar (.ics) фиды для каждой группы из данных расписания.

Расписание в данных абстрактное (odd_week=числитель / even_week=знаменатель,
день недели, время), поэтому для конкретных дат нужен конфиг семестра
`meta/semester.json`:

    {
      "tz": "Europe/Moscow",
      "start": "2026-02-09",   # первый учебный понедельник семестра
      "end":   "2026-05-31",   # последний учебный день
      "odd_first": true         # первая неделя семестра — числитель (odd_week)
    }

Для каждой пары раскрываем все её даты в [start, end] на неделях нужной
чётности и пишем по одному VEVENT на занятие. Файлы кладём в
`ical/<institute>/<safe-code>.ics`; их отдаёт тот же Cloudflare-прокси, что и
остальные данные, так что подписка работает по
`webcal://<proxy>/ical/<institute>/<code>.ics`.

Зависимостей нет (только stdlib) — запускается в CI после скрейпа.
"""
import json
import os
import re
import datetime as dt
from pathlib import Path

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_TYPE_RU = {
    "lecture": "ЛК", "practice": "ПЗ", "lab": "ЛР", "seminar": "СЕМ",
    "other": "",
}


def _safe(code: str) -> str:
    """Имя файла из кода группы (без слэшей/пробелов, latin/cyrillic как есть)."""
    return re.sub(r"[^\w-]", "_", code.strip())


def _parse_hhmm(s: str) -> tuple[int, int] | None:
    m = re.match(r"^(\d{1,2})[:.](\d{2})$", (s or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _week_parity_dates(start: dt.date, end: dt.date, weekday: int,
                       want_odd: bool, odd_first: bool) -> list[dt.date]:
    """Все даты с данным днём недели (0=Mon) на неделях нужной чётности."""
    # первая неделя семестра начинается с понедельника недели, куда попал start
    week0_monday = start - dt.timedelta(days=start.weekday())
    out = []
    d = week0_monday + dt.timedelta(days=weekday)
    while d <= end:
        if d >= start:
            week_index = (d - week0_monday).days // 7
            is_odd_week = (week_index % 2 == 0) == odd_first
            if is_odd_week == want_odd:
                out.append(d)
        d += dt.timedelta(days=7)
    return out


def _esc(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;") \
        .replace(",", "\\,").replace("\n", "\\n")


def _summary(lesson: dict) -> str:
    subj = (lesson.get("subject") or "").strip() or "Занятие"
    t = _TYPE_RU.get(lesson.get("type") or "other", "")
    return f"{subj} ({t})" if t else subj


def build_group_ics(group: dict, sem: dict, institute_name: str = "") -> str | None:
    """Строит .ics для одной группы. None, если занятий нет."""
    start = dt.date.fromisoformat(sem["start"])
    end = dt.date.fromisoformat(sem["end"])
    odd_first = bool(sem.get("odd_first", True))
    tz = sem.get("tz", "Europe/Moscow")
    code = group.get("name", "группа")

    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//mpgu-schedule//iCal//RU", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(code)} — расписание", f"X-WR-TIMEZONE:{tz}",
    ]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    n = 0
    sched = group.get("schedule", {}) or {}
    for wk, want_odd in (("odd_week", True), ("even_week", False)):
        for di, day in enumerate(DAYS):
            for lesson in (sched.get(wk, {}) or {}).get(day, []) or []:
                ts, te = _parse_hhmm(lesson.get("time_start")), _parse_hhmm(lesson.get("time_end"))
                if not ts:
                    continue
                for date in _week_parity_dates(start, end, di, want_odd, odd_first):
                    uid = f"{_safe(code)}-{date.isoformat()}-{ts[0]:02d}{ts[1]:02d}-{n}@mpgu-schedule"
                    ds = f"{date.strftime('%Y%m%d')}T{ts[0]:02d}{ts[1]:02d}00"
                    de = (f"{date.strftime('%Y%m%d')}T{te[0]:02d}{te[1]:02d}00"
                          if te else None)
                    desc_parts = [p for p in (lesson.get("teacher"),
                                              lesson.get("subgroup"),
                                              lesson.get("notes")) if p]
                    lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}",
                              f"DTSTART;TZID={tz}:{ds}"]
                    if de:
                        lines.append(f"DTEND;TZID={tz}:{de}")
                    lines.append(f"SUMMARY:{_esc(_summary(lesson))}")
                    if lesson.get("room"):
                        lines.append(f"LOCATION:{_esc(str(lesson['room']))}")
                    if desc_parts:
                        lines.append(f"DESCRIPTION:{_esc(' / '.join(map(str, desc_parts)))}")
                    lines.append("END:VEVENT")
                    n += 1
    if n == 0:
        return None
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def main(data_path: str | None = None) -> int:
    root = Path(data_path or os.environ.get("DATA_PATH", "."))
    sem_path = root / "meta" / "semester.json"
    if not sem_path.exists():
        print(f"Нет {sem_path} — пропускаю генерацию iCal")
        return 0
    sem = json.loads(sem_path.read_text(encoding="utf-8"))
    out_root = root / "ical"
    written = 0
    for inst_dir in sorted((root / "institutes").glob("*")):
        gdir = inst_dir / "groups"
        if not gdir.is_dir():
            continue
        dest = out_root / inst_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        for gf in gdir.glob("*.json"):
            group = json.loads(gf.read_text(encoding="utf-8"))
            ics = build_group_ics(group, sem)
            if ics:
                (dest / f"{_safe(group['name'])}.ics").write_text(ics, encoding="utf-8")
                written += 1
    print(f"Сгенерировано .ics: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
