"""Тесты генерации iCal (.ics) фидов.

Запуск:  python -m pytest scraper/tests/test_build_ical.py
   или:  python scraper/tests/test_build_ical.py
"""
import sys
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.build_ical import _week_parity_dates, build_group_ics, _safe

SEM = {"tz": "Europe/Moscow", "start": "2026-02-09", "end": "2026-05-31",
       "odd_first": True}


def test_parity_odd_first_monday():
    start, end = dt.date(2026, 2, 9), dt.date(2026, 5, 31)  # 9th is Monday
    odd = _week_parity_dates(start, end, 0, want_odd=True, odd_first=True)
    even = _week_parity_dates(start, end, 0, want_odd=False, odd_first=True)
    assert odd[0] == dt.date(2026, 2, 9)    # week 1 = числитель
    assert even[0] == dt.date(2026, 2, 16)  # week 2 = знаменатель
    assert odd[1] == dt.date(2026, 2, 23)   # alternating
    assert all(d.weekday() == 0 for d in odd + even)


def test_parity_respects_range_start():
    # day-of-week falling before `start` is excluded
    start, end = dt.date(2026, 2, 11), dt.date(2026, 3, 1)  # Wed
    mondays = _week_parity_dates(start, end, 0, want_odd=True, odd_first=True)
    assert all(d >= start for d in mondays)


def test_odd_first_false_flips_parity():
    start, end = dt.date(2026, 2, 9), dt.date(2026, 3, 1)
    odd = _week_parity_dates(start, end, 0, want_odd=True, odd_first=False)
    assert odd[0] == dt.date(2026, 2, 16)  # first week now знаменатель


def test_build_group_ics_structure():
    g = {"name": "БОИ34-ИОВ2503", "schedule": {
        "odd_week": {"monday": [{
            "time_start": "09:00", "time_end": "10:30", "subject": "Философия",
            "type": "lecture", "teacher": "Доц. Иванов", "room": "206"}]},
        "even_week": {}}}
    ics = build_group_ics(g, SEM)
    assert ics.startswith("BEGIN:VCALENDAR")
    assert ics.rstrip().endswith("END:VCALENDAR")
    assert ics.count("BEGIN:VEVENT") == ics.count("END:VEVENT") > 0
    assert "SUMMARY:Философия (ЛК)" in ics
    assert "LOCATION:206" in ics
    assert "DTSTART;TZID=Europe/Moscow:20260209T090000" in ics  # first odd Monday


def test_empty_schedule_returns_none():
    assert build_group_ics({"name": "X", "schedule": {}}, SEM) is None


def test_special_chars_escaped():
    g = {"name": "X", "schedule": {"odd_week": {"monday": [{
        "time_start": "09:00", "time_end": "10:30",
        "subject": "Мат; анализ, ч.1", "type": "other"}]}, "even_week": {}}}
    ics = build_group_ics(g, SEM)
    assert "SUMMARY:Мат\\; анализ\\, ч.1" in ics


def test_safe_filename():
    assert _safe("БОИ34-ИОВ2503 (103) п/г 2") == "БОИ34-ИОВ2503__103__п_г_2"


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
