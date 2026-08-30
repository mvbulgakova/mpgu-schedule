"""Тесты расчёта вакантных квотных мест и текста уведомления (чисто, без сети).

Запуск: python -m pytest scraper/tests/test_quota_vacancy.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur.quota_vacancy import (compute_group_vacancies,
                                           format_notification, format_report,
                                           format_seats_increased,
                                           general_list_for_key,
                                           seats_increased,
                                           seats_increased_from_order,
                                           unmatched_order_keys,
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


def test_format_notification_exact_text():
    expected = (
        "Предварительно: сейчас вы примерно 45-е из 33 (бюджет, "
        "«44.03.01 Тест», очная). По квотам этого направления пока есть "
        "незанятые места (~2) — по правилам они должны перейти в общий "
        "конкурс, но ещё не добавлены. Если добавят, ориентировочно вы "
        "будете ~45-е из ~35.\n\n"
        "Это предварительная прикидка по открытым данным, а не "
        "официальная информация — точная позиция обновится в живом "
        "списке. Следите: /spisok 1234567"
    )
    text = format_notification(pos=45, kcp=33, vacant=2,
                               direction="44.03.01 Тест", form="очная",
                               code="1234567")
    assert text == expected


def test_seats_increased_detects_growth_in_general_lists():
    baseline = {
        "G": {"main_kcp": True, "direction": "44.03.01 Тест", "form": "очная",
              "kcp_epk": 33},
        "Q1": {"quota": True, "direction": "44.03.01 Тест", "form": "очная",
               "kcp_epk": 9},
    }
    current = {
        "G": {"main_kcp": True, "direction": "44.03.01 Тест", "form": "очная",
              "kcp_epk": 35, "enrolled": 3},
        "Q1": {"quota": True, "direction": "44.03.01 Тест", "form": "очная",
               "kcp_epk": 7},
    }
    result = seats_increased(baseline, current)
    assert result == {"G": {"direction": "44.03.01 Тест", "form": "очная",
                            "old": 33, "new": 35, "enrolled": 3}}


def test_seats_increased_enrolled_is_none_when_unknown():
    baseline = {
        "G": {"main_kcp": True, "direction": "44.03.01 Тест", "form": "очная",
              "kcp_epk": 33},
    }
    current = {
        "G": {"main_kcp": True, "direction": "44.03.01 Тест", "form": "очная",
              "kcp_epk": 35},
    }
    result = seats_increased(baseline, current)
    assert result["G"]["enrolled"] is None


def test_seats_increased_ignores_unchanged_and_decreased_and_non_general():
    baseline = {
        "G1": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 10},
        "G2": {"main_kcp": True, "direction": "B", "form": "очная", "kcp_epk": 10},
        "Q1": {"quota": True, "direction": "C", "form": "очная", "kcp_epk": 10},
    }
    current = {
        "G1": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 10},
        "G2": {"main_kcp": True, "direction": "B", "form": "очная", "kcp_epk": 8},
        "Q1": {"quota": True, "direction": "C", "form": "очная", "kcp_epk": 20},
    }
    assert seats_increased(baseline, current) == {}


def test_seats_increased_skips_missing_baseline_or_unknown_kcp():
    baseline = {
        "G1": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": None},
    }
    current = {
        "G1": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 15},
        "G2": {"main_kcp": True, "direction": "B", "form": "очная", "kcp_epk": 15},
    }
    assert seats_increased(baseline, current) == {}


def test_format_seats_increased_exact_text():
    expected = (
        "📈 На вашем направлении стало больше бюджетных мест: было 33, "
        "теперь 35 (+2) — вернулись невостребованные места по квотам. "
        "«44.03.01 Тест», очная.\n\n"
        "Актуальную позицию смотрите: /spisok 1234567"
    )
    text = format_seats_increased(old=33, new=35, direction="44.03.01 Тест",
                                  form="очная", code="1234567")
    assert text == expected


def test_format_seats_increased_shows_occupancy_when_enrolled_known():
    expected = (
        "📈 На вашем направлении стало больше бюджетных мест: было 33, "
        "теперь 35 (+2) — вернулись невостребованные места по квотам. "
        "«44.03.01 Тест», очная.\n\n"
        "Уже зачислено: 3 из 35, свободно: 32.\n\n"
        "Актуальную позицию смотрите: /spisok 1234567"
    )
    text = format_seats_increased(old=33, new=35, direction="44.03.01 Тест",
                                  form="очная", code="1234567", enrolled=3)
    assert text == expected


def test_seats_increased_from_order_full_realistic_scenario():
    # Реальный кейс, уже проверенный вручную: особая 1/1, целевая 1/1,
    # отдельная 7/9 -> vacant = (1+1+9) - (1+1+7) = 11-9 = 2, new = 33+2 = 35.
    # БВИ = 3 -> enrolled в результате.
    baseline = {
        "G": {"main_kcp": True, "direction": "D", "form": "очная",
              "unit": "U", "kcp_epk": 33},
        "Q1": {"quota": True, "direction": "D", "form": "очная",
               "unit": "U", "kcp_epk": 1},
        "Q2": {"quota": True, "direction": "D", "form": "очная",
               "unit": "U", "kcp_epk": 1},
        "Q3": {"quota": True, "direction": "D", "form": "очная",
               "unit": "U", "kcp_epk": 9},
    }
    order_records = [
        {"unit": "U", "direction": "D", "form": "очная",
         "quota_kind": "особая", "count": 1},
        {"unit": "U", "direction": "D", "form": "очная",
         "quota_kind": "целевая", "count": 1},
        {"unit": "U", "direction": "D", "form": "очная",
         "quota_kind": "отдельная", "count": 7},
        {"unit": "U", "direction": "D", "form": "очная",
         "quota_kind": "бви", "count": 3},
    ]
    result = seats_increased_from_order(baseline, order_records)
    assert result == {"G": {"direction": "D", "form": "очная",
                            "old": 33, "new": 35, "enrolled": 3}}


# Регрессия 2026-08-04: реальный кейс (000000320, Институт биологии и
# химии) — PDF переносит направленность по-разному в разных блоках ОДНОГО
# направления ("...Безопасность \nжизнедеятельности/Биология..." в одном
# блоке, "...Безопасность жизнедеятельности/ \nБиология..." в другом),
# из-за чего после склейки строк получаются РАЗНЫЕ строки: с пробелом
# после "/" и без. Особая/целевая блоки улетали под другой ключ и не
# попадали в сумму (13 мест квоты вместо 9 учтённых). epk25 сам пишет
# направленности так же непоследовательно (пробел то есть, то нет), так
# что сопоставление ключей должно быть нечувствительно к этому пробелу.
def test_seats_increased_from_order_matches_despite_slash_spacing_drift():
    baseline = {
        "G": {"main_kcp": True, "direction": "A/B", "form": "очная",
              "unit": "U", "kcp_epk": 47},
        "Q_otdelnaya": {"quota": True, "direction": "A/B", "form": "очная",
                        "unit": "U", "kcp_epk": 9},
        # тот же реальный список направления, но с пробелом после "/" —
        # ровно как приходит из PDF в блоке "Особая"/"Целевая".
        "Q_osobaya": {"quota": True, "direction": "A/ B", "form": "очная",
                      "unit": "U", "kcp_epk": 3},
    }
    order_records = [
        {"unit": "U", "direction": "A/B", "form": "очная",
         "quota_kind": "отдельная", "count": 4},
        # тот же порядок записи, что и у "особой" квоты выше — с пробелом.
        {"unit": "U", "direction": "A/ B", "form": "очная",
         "quota_kind": "особая", "count": 3},
    ]
    result = seats_increased_from_order(baseline, order_records)
    # vacant = (9+3) - (4+3) = 5, new = 47+5 = 52 — квота "Особая" должна
    # учесться в сумме, а не потеряться из-за разницы в пробеле.
    assert result == {"G": {"direction": "A/B", "form": "очная",
                            "old": 47, "new": 52, "enrolled": 0}}


# Регрессия 2026-08-04: постоянный alias-словарь известных расхождений
# написания между приказом и epk25 (дефис после кода направления, отличия
# от сокращений на epk25, обрезанные "..." направленности). Реальный
# случай — Ставропольский филиал, приказ пишет с дефисом "44.03.02 -
# Психолого-педагогическое...", на epk25 дефиса нет.
def test_seats_increased_from_order_resolves_known_direction_alias():
    baseline = {
        "G": {"main_kcp": True,
              "direction": "44.03.02 Психолого-педагогическое образование. "
                           "Психология и социальная педагогика",
              "form": "очная", "unit": "Ставропольский филиал", "kcp_epk": 19},
        "Q1": {"quota": True,
               "direction": "44.03.02 Психолого-педагогическое образование. "
                            "Психология и социальная педагогика",
               "form": "очная", "unit": "Ставропольский филиал", "kcp_epk": 5},
    }
    order_records = [
        {"unit": "Ставропольский филиал",
         "direction": "44.03.02 - Психолого-педагогическое образование. "
                      "Психология и социальная педагогика",
         "form": "очная", "quota_kind": "отдельная", "count": 3},
    ]
    result = seats_increased_from_order(baseline, order_records)
    assert result == {"G": {
        "direction": "44.03.02 Психолого-педагогическое образование. "
                     "Психология и социальная педагогика",
        "form": "очная", "old": 19, "new": 21, "enrolled": 0}}
    assert unmatched_order_keys(baseline, order_records) == []


def test_seats_increased_from_order_skips_key_not_in_order_records():
    baseline = {
        "G": {"main_kcp": True, "direction": "D", "form": "очная",
              "unit": "U", "kcp_epk": 33},
        "Q1": {"quota": True, "direction": "D", "form": "очная",
               "unit": "U", "kcp_epk": 9},
    }
    # order_records пуст (или только для другого ключа)
    order_records = [
        {"unit": "ДРУГОЕ", "direction": "ДРУГОЕ", "form": "очная",
         "quota_kind": "особая", "count": 5},
    ]
    assert seats_increased_from_order(baseline, []) == {}
    assert seats_increased_from_order(baseline, order_records) == {}


def test_seats_increased_from_order_no_quota_lists_legitimate_zero():
    baseline = {
        "G": {"main_kcp": True, "direction": "D2", "form": "очная",
              "unit": "U2", "kcp_epk": 20},
        # нет квотных списков вообще для этого ключа
    }
    order_records = [
        {"unit": "U2", "direction": "D2", "form": "очная",
         "quota_kind": "бви", "count": 5},
    ]
    # quota_kcp_sum=0, quota_enrolled=0 (никаких особая/целевая/отдельная
    # записей нет), vacant=0 -> пропуск, а не false positive.
    assert seats_increased_from_order(baseline, order_records) == {}


def test_seats_increased_from_order_partial_quota_data_skips_group():
    baseline = {
        "G": {"main_kcp": True, "direction": "D", "form": "очная",
              "unit": "U", "kcp_epk": 33},
        "Q1": {"quota": True, "direction": "D", "form": "очная",
               "unit": "U", "kcp_epk": None},  # не распарсился
        "Q2": {"quota": True, "direction": "D", "form": "очная",
               "unit": "U", "kcp_epk": 9},
    }
    order_records = [
        {"unit": "U", "direction": "D", "form": "очная",
         "quota_kind": "особая", "count": 1},
        {"unit": "U", "direction": "D", "form": "очная",
         "quota_kind": "целевая", "count": 1},
        {"unit": "U", "direction": "D", "form": "очная",
         "quota_kind": "отдельная", "count": 7},
        {"unit": "U", "direction": "D", "form": "очная",
         "quota_kind": "бви", "count": 3},
    ]
    assert seats_increased_from_order(baseline, order_records) == {}


def test_unmatched_order_keys_finds_direction_missing_from_baseline():
    baseline = {
        "G": {"main_kcp": True, "direction": "D", "form": "очная",
              "unit": "U", "kcp_epk": 33},
    }
    order_records = [
        {"unit": "U", "direction": "D", "form": "очная",
         "quota_kind": "особая", "count": 1},
        {"unit": "U2", "direction": "D2", "form": "очная",
         "quota_kind": "бви", "count": 5},
    ]
    assert unmatched_order_keys(baseline, order_records) == [("D2", "очная", "U2")]


def test_seats_increased_from_order_skips_when_general_kcp_unknown():
    baseline = {
        "G": {"main_kcp": True, "direction": "D", "form": "очная",
              "unit": "U", "kcp_epk": None},
        "Q1": {"quota": True, "direction": "D", "form": "очная",
               "unit": "U", "kcp_epk": 1},
        "Q2": {"quota": True, "direction": "D", "form": "очная",
               "unit": "U", "kcp_epk": 1},
        "Q3": {"quota": True, "direction": "D", "form": "очная",
               "unit": "U", "kcp_epk": 9},
    }
    order_records = [
        {"unit": "U", "direction": "D", "form": "очная",
         "quota_kind": "особая", "count": 1},
        {"unit": "U", "direction": "D", "form": "очная",
         "quota_kind": "целевая", "count": 1},
        {"unit": "U", "direction": "D", "form": "очная",
         "quota_kind": "отдельная", "count": 7},
        {"unit": "U", "direction": "D", "form": "очная",
         "quota_kind": "бви", "count": 3},
    ]
    assert seats_increased_from_order(baseline, order_records) == {}
