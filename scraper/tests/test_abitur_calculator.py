"""Тесты данных правил и калькулятора доп. баллов.

Запуск: python -m pytest scraper/tests/test_abitur_calculator.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import achievements as A


def test_sport_points_table():
    assert A.SPORT["gto_gold"][1] == 5
    assert A.SPORT["gto_silver_bronze"][1] == 4
    assert A.SPORT["master"][1] == 8
    assert A.SPORT["kms"][1] == 6
    assert A.SPORT["champion_olympic"][1] == 10


def test_volunteer_points_base_non_pedagogical():
    f = A.volunteer_points
    assert f("base", False, 50) == 0
    assert f("base", False, 100) == 2
    assert f("base", False, 250) == 3
    assert f("base", False, 300) == 4


def test_volunteer_points_base_pedagogical_is_higher():
    f = A.volunteer_points
    # для пед-направления берётся максимум из общих и пед. ступеней
    assert f("base", True, 100) == 6
    assert f("base", True, 200) == 8
    assert f("base", True, 300) == 10
    assert f("base", True, 90) == 0


def test_volunteer_points_spec():
    f = A.volunteer_points
    assert f("spec", False, 200) == 0
    assert f("spec", False, 300) == 4
    assert f("spec", False, 400) == 5
    assert f("spec", False, 500) == 6
    assert f("spec", True, 100) == 8
    assert f("spec", True, 300) == 10


from scraper.abitur.calculator import CalcInput, calculate


def _base(**kw):
    defaults = dict(level="base", pedagogical=False, target_quota=False,
                    sport=None, edu_honors=False, abilimpiks=False, svo=False,
                    do_profile=False, olympiad=None, volunteer_hours=0,
                    publications=None, patents=False, fieb=None, premia=None,
                    target_points=0)
    defaults.update(kw)
    return CalcInput(**defaults)


def test_calculate_sport_takes_single_max():
    # выбран КМС (6) — спорт даёт только один вид
    r = calculate(_base(sport="kms"))
    assert r.general_raw == 6
    assert r.total == 6
    assert r.capped is False


def test_calculate_caps_general_at_10():
    # медаль(10) + золото ГТО(5) + волонтёрство 300ч(4) = 19 → потолок 10
    r = calculate(_base(edu_honors=True, sport="gto_gold", volunteer_hours=300))
    assert r.general_raw == 19
    assert r.general_capped == 10
    assert r.total == 10
    assert r.capped is True


def test_calculate_pedagogical_volunteering():
    r = calculate(_base(pedagogical=True, volunteer_hours=200))
    assert r.general_raw == 8
    assert r.total == 8


def test_calculate_target_quota_adds_up_to_5():
    # общие: медаль 10 (потолок 10) + целевые 5 → 15
    r = calculate(_base(edu_honors=True, target_quota=True, target_points=7))
    assert r.general_capped == 10
    assert r.target_capped == 5
    assert r.total == 15


def test_calculate_target_points_ignored_without_quota():
    r = calculate(_base(edu_honors=True, target_quota=False, target_points=5))
    assert r.target_capped == 0
    assert r.total == 10


def test_calculate_spec_publications_and_patents():
    r = calculate(_base(level="spec", publications="multi", patents=True))
    assert r.general_raw == 20
    assert r.general_capped == 10


def test_calculate_breakdown_lists_contributors():
    r = calculate(_base(sport="kms", olympiad="prizer"))
    labels = [lbl for (lbl, _) in r.breakdown]
    assert any("КМС" in l for l in labels)
    assert any("Призёр" in l for l in labels)
    assert r.general_raw == 11
    assert r.general_capped == 10
