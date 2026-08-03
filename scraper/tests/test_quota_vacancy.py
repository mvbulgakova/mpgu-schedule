"""Тесты расчёта вакантных квотных мест и текста уведомления (чисто, без сети).

Запуск: python -m pytest scraper/tests/test_quota_vacancy.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur.quota_vacancy import (compute_group_vacancies,
                                           format_report,
                                           general_list_for_key,
                                           vacancy_for_list)

KEY = ("44.03.01 Русский язык и Литература", "очная", "Институт филологии")


def _quota_list(vid, kcp_epk, enrolled):
    return {"quota": True, "direction": KEY[0], "form": KEY[1], "unit": KEY[2],
            "vid_mest": vid, "kcp_epk": kcp_epk, "enrolled": enrolled}


def test_full_data_sums_vacant_across_quota_kinds():
    # Реальный кейс 03.08.26: особая 1/1, целевая 1/1, отдельная 7/9 —
    # 2 вакантных места по отдельной квоте, суммарно по группе.
    lists = {
        "Q1": _quota_list("особая квота", 1, 1),
        "Q2": _quota_list("целевая детализированная квота", 1, 1),
        "Q3": _quota_list("отдельная квота", 9, 7),
    }
    groups = compute_group_vacancies(lists)
    assert groups[KEY]["vacant"] == 2
    assert groups[KEY]["breakdown"] == [
        ("особая квота", 1, 1),
        ("целевая детализированная квота", 1, 1),
        ("отдельная квота", 9, 7),
    ]


def test_incomplete_data_excludes_whole_group():
    # Если хоть у одного квотного списка группы неизвестен enrolled —
    # группа целиком не участвует (не даём заниженного/ложного числа).
    lists = {
        "Q1": _quota_list("особая квота", 9, None),   # enrolled не распарсился
        "Q2": _quota_list("отдельная квота", 9, 7),
    }
    assert compute_group_vacancies(lists) == {}


def test_zero_vacant_group_not_included():
    lists = {"Q1": _quota_list("особая квота", 1, 1)}
    assert compute_group_vacancies(lists) == {}


def test_general_list_for_key_finds_main_kcp_match():
    lists = {
        "G": {"main_kcp": True, "direction": KEY[0], "form": KEY[1], "unit": KEY[2]},
        "Q1": _quota_list("особая квота", 1, 1),
    }
    assert general_list_for_key(lists, KEY) == "G"
    assert general_list_for_key(lists, ("другое", "очная", "X")) is None


def test_vacancy_for_list_looks_up_by_general_code():
    lists = {
        "G": {"main_kcp": True, "direction": KEY[0], "form": KEY[1],
              "unit": KEY[2], "kcp_epk": 33},
        "Q1": _quota_list("отдельная квота", 9, 7),
    }
    info = vacancy_for_list(lists, "G")
    assert info["vacant"] == 2
    assert vacancy_for_list(lists, "НЕТ_ТАКОГО") is None


def test_format_report_lists_only_groups_with_vacancy():
    lists = {
        "G": {"main_kcp": True, "direction": KEY[0], "form": KEY[1],
              "unit": KEY[2], "kcp_epk": 33},
        "Q1": _quota_list("особая квота", 1, 1),
        "Q2": _quota_list("целевая детализированная квота", 1, 1),
        "Q3": _quota_list("отдельная квота", 9, 7),
    }
    report = format_report(lists)
    assert KEY[0] in report
    assert "вакантно квот: 2" in report
    assert "отдельная квота: 7/9" in report


def test_format_report_empty_when_no_vacancies():
    assert format_report({}) == "Незанятых квотных мест не найдено."
