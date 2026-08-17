"""Тесты сборки истории проходных (чисто, без сети).

Запуск: python -m pytest scraper/tests/test_build_admissions.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.build_admissions_index import build_history

PROGRAMS = [
    {"code": "05.03.02", "form": "очная", "name": "География, направленность Общая география",
     "exam_slots": [], "places": 20},
    {"code": "44.03.01", "form": "очная", "name": "Педагогическое образование, направленность История и Обществознание",
     "exam_slots": [], "places": 25},
    {"code": "44.03.01", "form": "очная", "name": "Педагогическое образование, направленность География и Экология",
     "exam_slots": [], "places": 45},
]

ROWS = [
    {"year": 2019, "code": "05.03.02", "program": "Общая география", "form": "очная",
     "passing": 205, "competition": 17.2},
    {"year": 2020, "code": "05.03.02", "program": "Общая география", "form": "очная",
     "passing": 210, "competition": None},
    {"year": 2020, "code": "44.03.01", "program": "История и Обществознание", "form": "очная",
     "passing": 240, "competition": None},
    {"year": 2020, "code": "99.99.99", "program": "Неизвестное", "form": "очная",
     "passing": 200, "competition": None},
]


def test_build_history_matches_by_direction_words():
    doc = build_history(ROWS, PROGRAMS)
    progs = doc["programs"]
    geo = next(v for v in progs.values() if v["code"] == "05.03.02")
    assert geo["history"] == {"2019": 205, "2020": 210}
    assert geo["range3"] == [205, 210]
    assert geo["last"] == [2020, 210]
    ped = next(v for v in progs.values() if v["code"] == "44.03.01")
    assert "История" in ped["name"]  # не перепутали с Географией и Экологией
    assert ped["history"] == {"2020": 240}


def test_unmatched_rows_are_kept():
    doc = build_history(ROWS, PROGRAMS)
    assert len(doc["unmatched"]) == 1
    assert doc["unmatched"][0]["code"] == "99.99.99"


def test_specific_profile_beats_broader_group():
    # профиль зачисления «История» должен лечь в каталожную «История», а не
    # в более широкую группу «История и Воспитательная работа/…»
    programs = [
        {"code": "44.03.01", "form": "очная", "places": 32,
         "name": "Педагогическое образование, направленность История"},
        {"code": "44.03.01", "form": "очная", "places": 58,
         "name": "Педагогическое образование, направленность История и "
                 "Воспитательная работа/Обществознание"},
    ]
    rows = [{"year": 2025, "code": "44.03.01", "program": "История",
             "form": "очная", "passing": 210, "competition": None}]
    doc = build_history(rows, programs)
    hit = [v for v in doc["programs"].values()
           if v["history"].get("2025") == 210]
    assert len(hit) == 1
    assert hit[0]["name"].endswith("История")   # не «…и Воспитательная работа»


def test_true_ambiguity_still_unmatched():
    # если два кандидата одинаково хороши и оба не покрывают профиль — не гадаем
    programs = [
        {"code": "44.03.01", "form": "очная", "places": 20,
         "name": "Педагогическое образование, направленность Химия и Экология"},
        {"code": "44.03.01", "form": "очная", "places": 30,
         "name": "Педагогическое образование, направленность Биология и Экология"},
    ]
    rows = [{"year": 2025, "code": "44.03.01", "program": "Физика и Экология",
             "form": "очная", "passing": 200, "competition": None}]
    doc = build_history(rows, programs)
    assert doc["programs"] == {}
    assert len(doc["unmatched"]) == 1
