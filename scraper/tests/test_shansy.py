"""Тесты калькулятора шансов (разбор, подбор, форматирование). Без сети.

Запуск: python -m pytest scraper/tests/test_shansy.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import shansy


def test_parse_scores_message():
    s = shansy.parse_scores("русский 78, общество 84 история 90")
    assert s == {"русский язык": 78, "обществознание": 84, "история": 90}


def test_parse_scores_rejects_garbage():
    assert shansy.parse_scores("привет") is None
    assert shansy.parse_scores("русский 178, история 90") is None  # балл 0..100
    assert shansy.parse_scores("история 90, общество 80") is None  # без русского
    assert shansy.parse_scores("русский 78") is None               # один предмет


PROGRAMS = [
    {"code": "44.03.05", "name": "Педагогическое образование, направленность История и Обществознание",
     "form": "очная", "places": 25, "paid_only": False, "dvi": False,
     "exam_slots": [["История", "Иностранный язык"], ["Обществознание"], ["Русский язык"]]},
    {"code": "42.03.02", "name": "Журналистика, направленность Журналистика",
     "form": "очная", "places": None, "paid_only": True, "dvi": True,
     "exam_slots": [["Русский язык"], ["Литература"], ["Сочинение (творческое испытание)"]]},
    {"code": "01.03.01", "name": "Математика, направленность Математика",
     "form": "очная", "places": 20, "paid_only": False, "dvi": False,
     "exam_slots": [["Математика (профильная)"], ["Физика", "Информатика"], ["Русский язык"]]},
]


def test_match_programs_respects_exam_slots():
    scores = {"русский язык": 70, "обществознание": 80, "история": 90}
    got = shansy.match_programs(scores, PROGRAMS)
    codes = [m["program"]["code"] for m in got]
    assert "44.03.05" in codes           # все слоты закрыты
    assert "01.03.01" not in codes       # нет математики → не предлагаем
    ped = next(m for m in got if m["program"]["code"] == "44.03.05")
    assert ped["total"] == 70 + 80 + 90


def test_match_dvi_program_flagged_not_dropped():
    scores = {"русский язык": 70, "литература": 88}
    got = shansy.match_programs(scores, PROGRAMS)
    zhur = next(m for m in got if m["program"]["code"] == "42.03.02")
    assert zhur["need_dvi"] is True
    assert zhur["total"] == 70 + 88      # ДВИ-слот не входит в сумму ЕГЭ


def test_slot_takes_best_alternative():
    scores = {"русский язык": 70, "история": 60, "иностранный язык": 95,
              "обществознание": 80}
    got = shansy.match_programs(scores, PROGRAMS)
    ped = next(m for m in got if m["program"]["code"] == "44.03.05")
    assert ped["total"] == 70 + 80 + 95  # взяли иняз 95, а не историю 60


HISTORY = {"programs": {
    "k1": {"code": "44.03.05", "form": "очная",
           "name": "Педагогическое образование, направленность История и Обществознание",
           "history": {"2019": 274, "2020": 266}, "range3": [266, 274], "last": [2020, 266]}}}

LISTS = {"updated_at": "2026-07-02",
         "lists": {"L1": {"direction": "44.03.05 Педагогическое образование. История и Обществознание",
                          "form": "очная", "kind": "бюджет",
                          "totals": [250, 230]}}}


def test_format_includes_live_history_and_disclaimer():
    scores = {"русский язык": 70, "обществознание": 80, "история": 90}
    matches = shansy.match_programs(scores, PROGRAMS)
    text = shansy.format_answer(matches, HISTORY, LISTS, scores)
    assert "не гарант" in text.lower()
    assert "2019: 274" in text and "2020: 266" in text
    assert "в списке 2 чел" in text          # live-блок нашёл список L1
    assert "240" in text                      # сумма
    assert "ДВИ" not in text.split("Журналистика")[0]  # у пед-программы нет пометки ДВИ


def test_answer_prompt_on_bad_input():
    out = shansy.answer("привет")
    assert "русский 78" in out
