"""Тесты финальной очистки расписания (sanitize_*).

Запуск:  python -m pytest scraper/tests/test_sanitize.py
   или:  python scraper/tests/test_sanitize.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.normalizer.schedule_normalizer import (
    clean_room, pull_subgroup, sanitize_lesson, sanitize_groups, infer_slot,
    fix_homoglyphs,
)


def test_fix_homoglyphs_latin_to_cyrillic():
    out = fix_homoglyphs("БOМ35-МДО2201")  # latin O
    assert out == "БОМ35-МДО2201"
    assert all(ord(c) >= 0x400 or not c.isalpha() for c in out)


def test_fix_homoglyphs_leaves_non_homoglyph_latin():
    # Z and I have no cyrillic look-alike — must stay untouched
    assert fix_homoglyphs("MZIO34-СТ2501") == "МZIО34-СТ2501"


def test_sanitize_groups_normalizes_name():
    g = [{"name": "ВOМ34-ПИМ2408", "schedule": {}}]  # latin O
    sanitize_groups(g)
    assert g[0]["name"] == "ВОМ34-ПИМ2408"


# --- clean_room -------------------------------------------------------------

def test_clean_room_strips_aud_prefix():
    assert clean_room("ауд. 403") == "403"
    assert clean_room("ауд 211") == "211"
    assert clean_room("ауд. 308а") == "308а"


def test_clean_room_preserves_multiple_rooms():
    assert clean_room("ауд. 108, 210") == "108, 210"
    assert clean_room("332 / ауд. 333") == "332 / 333"
    assert clean_room("ауд. 332 / ауд. 333") == "332 / 333"


def test_clean_room_preserves_non_aud_values():
    assert clean_room("305") == "305"
    assert clean_room("А-101") == "А-101"
    assert clean_room("Спортивный зал") == "Спортивный зал"
    assert clean_room("Белый зал") == "Белый зал"
    assert clean_room(None) is None
    assert clean_room("") is None


# --- pull_subgroup ----------------------------------------------------------

def test_pull_subgroup_paren_form():
    assert pull_subgroup("Физика (п/г 1)") == ("Физика", 1)
    assert pull_subgroup("Химия (2 п/г)") == ("Химия", 2)


def test_pull_subgroup_loose_form():
    assert pull_subgroup("доц. Стесева О.И., 1 п/гр") == ("доц. Стесева О.И.", 1)
    assert pull_subgroup("п/г 2") == ("", 2)
    assert pull_subgroup("2 п/гр") == ("", 2)


def test_pull_subgroup_none_when_absent():
    assert pull_subgroup("Математический анализ") == ("Математический анализ", None)
    assert pull_subgroup("") == ("", None)
    assert pull_subgroup(None) == (None, None)


# --- infer_slot (актуальная сетка) -----------------------------------------

def test_infer_slot_real_grid():
    assert infer_slot("09:00") == 1
    assert infer_slot("10:40") == 2
    assert infer_slot("12:40") == 3
    assert infer_slot("14:20") == 4
    assert infer_slot("16:00") == 5
    assert infer_slot("08:00") is None  # вне основной сетки


# --- sanitize_lesson --------------------------------------------------------

def test_sanitize_lesson_math_messy_case():
    raw = {
        "slot": None, "time_start": "10:40", "time_end": "12:10",
        "subject": "Геометрия", "type": "practice",
        "teacher": "доц. Стесева О.И., 1 п/гр", "room": "ауд. 205",
        "subgroup": None, "notes": "",
    }
    out = sanitize_lesson(raw)
    assert out["teacher"] == "доц. Стесева О.И."
    assert out["room"] == "205"
    assert out["subgroup"] == 1
    assert out["slot"] == 2


def test_sanitize_lesson_room_with_subgroup_and_aud():
    raw = {
        "time_start": "09:00", "time_end": "10:30",
        "subject": "Геометрия", "type": "practice",
        "teacher": None, "room": "2 п/гр, ауд. 108",
        "subgroup": None, "notes": "",
    }
    out = sanitize_lesson(raw)
    assert out["room"] == "108"
    assert out["subgroup"] == 2


def test_sanitize_lesson_assistant_in_room():
    raw = {
        "time_start": "09:00", "time_end": "10:30",
        "subject": "Алгебра", "type": "practice",
        "teacher": None, "room": "ассист. Тихонов С.О., ауд. 301",
        "subgroup": None, "notes": "",
    }
    out = sanitize_lesson(raw)
    assert out["room"] == "301"
    assert out["teacher"] and "Тихонов" in out["teacher"]


def test_sanitize_lesson_does_not_touch_long_merged_field():
    blob = "доц. А.Б. до 18.05 / Экология п/г 1, проф. В.Г. " + "x" * 50
    raw = {
        "time_start": "09:00", "time_end": "10:30",
        "subject": "ДВ", "type": "lecture",
        "teacher": blob, "room": "315", "subgroup": None, "notes": "",
    }
    out = sanitize_lesson(raw)
    assert out["subgroup"] is None  # не вытаскиваем п/г из слепленной ячейки


def test_sanitize_lesson_recovers_teacher_from_room():
    raw = {
        "time_start": "09:00", "time_end": "10:30",
        "subject": "Алгебра", "type": "lecture",
        "teacher": None, "room": "доц. Стесева О.И., ауд. 205",
        "subgroup": None, "notes": "",
    }
    out = sanitize_lesson(raw)
    assert out["room"] == "205"
    assert out["teacher"] and "Стесева" in out["teacher"]


def test_sanitize_lesson_leaves_clean_data_untouched():
    raw = {
        "slot": 1, "time_start": "09:00", "time_end": "10:30",
        "subject": "История", "type": "lecture",
        "teacher": "проф. Шамин С.М.", "room": "322",
        "subgroup": None, "notes": "",
    }
    out = sanitize_lesson(raw)
    assert out == {
        "slot": 1, "time_start": "09:00", "time_end": "10:30",
        "subject": "История", "type": "lecture",
        "teacher": "проф. Шамин С.М.", "room": "322",
        "subgroup": None, "notes": "",
    }


# --- sanitize_groups: дедуп + сортировка ------------------------------------

def _lesson(t, subj, **kw):
    base = {
        "slot": None, "time_start": t, "time_end": "",
        "subject": subj, "type": "lecture", "teacher": None,
        "room": None, "subgroup": None, "notes": "",
    }
    base.update(kw)
    return base


def test_sanitize_groups_dedups_exact_repeats():
    groups = [{
        "name": "G1",
        "schedule": {
            "odd_week": {"saturday": [
                _lesson("10:40", "История", teacher="Шамин", room="322"),
                _lesson("10:40", "История", teacher="Шамин", room="322"),  # точный дубль
                _lesson("14:20", "История", teacher="Сазонов", room="323", type="practice"),  # другой
            ]},
            "even_week": {},
        },
    }]
    sanitize_groups(groups)
    sat = groups[0]["schedule"]["odd_week"]["saturday"]
    assert len(sat) == 2


def test_sanitize_groups_sorts_by_time():
    groups = [{
        "name": "G1",
        "schedule": {
            "odd_week": {"monday": [
                _lesson("14:20", "C"),
                _lesson("09:00", "A"),
                _lesson("10:40", "B"),
            ]},
            "even_week": {},
        },
    }]
    sanitize_groups(groups)
    mon = groups[0]["schedule"]["odd_week"]["monday"]
    assert [l["subject"] for l in mon] == ["A", "B", "C"]


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
