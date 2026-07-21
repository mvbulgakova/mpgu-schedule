"""Тесты прогноза проходного (чистые функции, без сети)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import prediction as P


def test_range_from_history_low_and_high():
    r = P.predict_range({"2023": 266, "2024": 242, "2025": 244}, sim=200)
    assert r == (242, 266)                       # sim ниже истории — не влияет на верх


def test_hot_year_sim_lifts_upper_bound():
    # текущий пол по согласиям уже выше прошлогоднего максимума → верх = sim
    r = P.predict_range({"2024": 242, "2025": 244}, sim=260)
    assert r == (242, 260)


def test_only_pre2021_history_ignored():
    assert P.predict_range({"2015": 121, "2019": 209}, sim=None) is None


def test_no_history_no_range():
    assert P.predict_range({}, sim=180) is None
    assert P.predict_range(None, sim=None) is None


def test_recent_caps_at_three_years():
    r = P.predict_range({"2021": 100, "2022": 300, "2023": 250,
                         "2024": 240, "2025": 244}, sim=None)
    # берём только 2023–2025 → min 240
    assert r == (240, 250)


def test_format_full_block_has_all_signals():
    out = P.format_prediction({"2024": 242, "2025": 244}, sim=230, cap=270, seats=18)
    assert "Примерный проходной-2026: ориентир ~242–244" in out
    assert "2024: 242, 2025: 244" in out
    assert "от ~230" in out and "5 августа" in out
    assert "топ-18" in out and "~270" in out
    assert "не гарантия" in out


def test_format_low_sim_shows_qualitative_note_not_absurd_number():
    # много мест, мало согласий → sim≈4; не показываем «от ~4» рядом с историей 240+
    out = P.format_prediction({"2024": 242, "2025": 244}, sim=4, cap=250, seats=80)
    assert "от ~4" not in out
    assert "согласий пока подано мало" in out
    assert "ориентир ~242–244" in out          # диапазон по-прежнему из истории


def test_format_no_history_shows_live_only():
    out = P.format_prediction(None, sim=210, cap=270, seats=18)
    assert "истории нет" in out
    assert "от ~210" in out and "~270" in out
    assert "ориентир" not in out               # диапазон не выдумываем


def test_format_old_only_history_flagged_no_range():
    out = P.format_prediction({"2015": 121, "2018": 200, "2019": 209},
                              sim=None, cap=None, seats=None)
    assert "до 2021" in out and "2019: 209" in out
    assert "ориентир" not in out               # диапазон по старым не даём
    assert "2015" not in out                   # показываем 2 последних старых


def test_format_history_only_no_live_still_gives_range():
    out = P.format_prediction({"2024": 242, "2025": 244})
    assert "ориентир ~242–244" in out
    assert "по согласиям" not in out           # живых сигналов нет — не выдумываем


def test_format_nothing_returns_none():
    assert P.format_prediction(None, None, None, None) is None
    assert P.format_prediction({}, None, None, None) is None
