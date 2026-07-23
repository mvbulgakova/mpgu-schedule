"""Тесты извлечения «дисциплина → семестры» из учебного плана (по координатам)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.parsers import study_plan_semesters as SPS


def test_decode_digits_and_letters():
    assert SPS.decode_codes(["1234"]) == [1, 2, 3, 4]
    assert SPS.decode_codes(["2", "1"]) == [1, 2]
    assert SPS.decode_codes(["А", "В", "С"]) == [10, 11, 12]     # 10/11/12 семестры
    assert SPS.decode_codes(["9А"]) == [9, 10]


def _w(x, y, text):
    return (x, y, x + 10, y + 8, text, 0, 0, 0)


# синтетическая «страница»: заголовки столбцов + две дисциплины
_HEADER = [
    _w(24, 41, "Индекс"), _w(75, 41, "Наименование"),
    _w(130, 41, "Экзамен"), _w(142, 41, "Зачет"),
    _w(153, 41, "Зачет"), _w(170, 41, "КР"), _w(190, 41, "з.е."),
]


def test_parse_assigns_only_control_column_tokens():
    rows = [
        # История России: экзамен сем2, зачёт сем1; «4» и «144» — з.е./часы (правее)
        _w(14, 60, "Б1.О.01.01"), _w(46, 60, "История"), _w(61, 60, "России"),
        _w(131, 60, "2"), _w(143, 60, "1"), _w(190, 60, "4"), _w(212, 60, "144"),
        # Иностранный язык: идёт семестры 1-4 (в столбце экзамена «1234»)
        _w(14, 72, "Б1.О.02.01"), _w(46, 72, "Иностранный"), _w(70, 72, "язык"),
        _w(131, 72, "1234"), _w(190, 72, "8"),
    ]
    out = SPS.parse_words(_HEADER + rows)
    d = {r["name"]: r["semesters"] for r in out}
    assert d["История России"] == [1, 2]           # «4»/«144» не попали
    assert d["Иностранный язык"] == [1, 2, 3, 4]


def test_modules_filtered_leaves_only():
    rows = [
        _w(14, 60, "Б1.О.01"), _w(46, 60, "Модуль"),           # модуль (2 сегмента)
        _w(131, 60, "1"), _w(143, 60, "2"),
        _w(14, 72, "Б1.О.01.01"), _w(46, 72, "История"),       # лист (4 сегмента)
        _w(131, 72, "1"),
    ]
    out = SPS.parse_words(_HEADER + rows)
    names = {r["name"] for r in out}
    assert "История" in names and "Модуль" not in names
    out_all = SPS.parse_words(_HEADER + rows, leaves_only=False)
    assert "Модуль" in {r["name"] for r in out_all}


def test_by_semester_groups():
    rows = [{"index": "Б1.О.01.01", "name": "A", "semesters": [1, 2]},
            {"index": "Б1.О.01.02", "name": "B", "semesters": [2]}]
    bs = SPS.by_semester(rows)
    assert bs[1] == ["A"] and sorted(bs[2]) == ["A", "B"]


def test_no_header_returns_empty():
    assert SPS.parse_words([_w(14, 60, "Б1.О.01.01"), _w(46, 60, "X")]) == []
