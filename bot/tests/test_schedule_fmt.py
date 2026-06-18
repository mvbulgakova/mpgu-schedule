import pytest
from bot.services.schedule_fmt import format_day, format_week, get_current_week_key
from datetime import date


def _make_lesson(**kwargs):
    base = {
        "slot": 1, "time_start": "09:00", "time_end": "10:30",
        "subject": "Математика", "type": "lecture",
        "teacher": "Иванов И.И.", "room": "403", "subgroup": None, "notes": ""
    }
    return {**base, **kwargs}


def test_format_day_no_lessons():
    result = format_day("monday", [], even_week=False)
    assert "Занятий нет" in result
    assert "Понедельник" in result


def test_format_day_one_lesson():
    lessons = [_make_lesson()]
    result = format_day("monday", lessons, even_week=False)
    assert "09:00" in result
    assert "Математика" in result
    assert "Иванов" in result
    assert "403" in result


def test_format_day_escapes_html():
    lessons = [_make_lesson(subject="Алгебра <и> анализ & топология")]
    result = format_day("monday", lessons, even_week=False)
    assert "<и>" not in result
    assert "&lt;и&gt;" in result


def test_format_day_sorts_by_time():
    lessons = [
        _make_lesson(slot=2, time_start="10:40", subject="Б"),
        _make_lesson(slot=1, time_start="09:00", subject="А"),
    ]
    result = format_day("tuesday", lessons, even_week=True)
    assert result.index("09:00") < result.index("10:40")


def test_get_current_week_key_odd():
    monday_week1 = date(2025, 12, 29)  # ISO week 1 — odd
    key = get_current_week_key(monday_week1)
    assert key == "odd_week"


def test_get_current_week_key_even():
    monday_week2 = date(2026, 1, 5)  # ISO week 2 — even
    key = get_current_week_key(monday_week2)
    assert key == "even_week"
