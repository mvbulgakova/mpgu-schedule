"""Тесты конечного автомата калькулятора.

Запуск: python -m pytest scraper/tests/test_abitur_dialog.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import dialog


def test_start_asks_level():
    s = dialog.start()
    view = dialog.render(s)
    assert "уровень" in view.text.lower()
    # есть кнопки выбора уровня
    data = [cb for row in view.keyboard for (_, cb) in row]
    assert "c:level:base" in data and "c:level:spec" in data


def test_flow_to_result_base():
    s = dialog.start()
    s, _ = dialog.handle(s, "c:level:base")
    s, _ = dialog.handle(s, "c:pedagogical:0")
    s, _ = dialog.handle(s, "c:target:0")
    # на шаге достижений включаем медаль и считаем
    s, _ = dialog.handle(s, "c:toggle:edu_honors")
    s, done = dialog.handle(s, "c:done:1")
    assert done is True
    result = dialog.compute(s)
    assert result.total == 10


def test_toggle_is_reversible():
    s = dialog.start()
    s, _ = dialog.handle(s, "c:level:base")
    s, _ = dialog.handle(s, "c:pedagogical:1")
    s, _ = dialog.handle(s, "c:target:0")
    s, _ = dialog.handle(s, "c:toggle:svo")
    assert s.svo is True
    s, _ = dialog.handle(s, "c:toggle:svo")
    assert s.svo is False


def test_volunteer_hours_via_text():
    s = dialog.start()
    s, _ = dialog.handle(s, "c:level:base")
    s, _ = dialog.handle(s, "c:pedagogical:1")
    s, _ = dialog.handle(s, "c:target:0")
    s = dialog.set_volunteer_hours(s, 200)
    assert s.volunteer_hours == 200
    assert dialog.compute(s).total == 8


def test_olympiad_cycles_none_winner_prizer():
    s = dialog.start()
    s, _ = dialog.handle(s, "c:level:base")
    s, _ = dialog.handle(s, "c:pedagogical:0")
    s, _ = dialog.handle(s, "c:target:0")
    assert s.olympiad is None
    s, _ = dialog.handle(s, "c:olympcycle:1")
    assert s.olympiad == "winner"
    s, _ = dialog.handle(s, "c:olympcycle:1")
    assert s.olympiad == "prizer"
    s, _ = dialog.handle(s, "c:olympcycle:1")
    assert s.olympiad is None
    # победитель олимпиады = 10 баллов
    s, _ = dialog.handle(s, "c:olympcycle:1")
    assert dialog.compute(s).total == 10


def test_sport_picker_sets_and_clears():
    s = dialog.start()
    s, _ = dialog.handle(s, "c:level:base")
    s, _ = dialog.handle(s, "c:pedagogical:0")
    s, _ = dialog.handle(s, "c:target:0")
    # открыть меню спорта → показать варианты
    s, _ = dialog.handle(s, "c:sportmenu:1")
    view = dialog.render(s)
    data = [cb for row in view.keyboard for (_, cb) in row]
    assert any(cb.startswith("c:sport:") for cb in data)
    # выбрать КМС (6) — возвращаемся на экран достижений
    s, _ = dialog.handle(s, "c:sport:kms")
    assert s.sport == "kms"
    assert s.step == dialog.STEP_ACHIEVE
    assert dialog.compute(s).total == 6
    # снять выбор
    s, _ = dialog.handle(s, "c:sport:none")
    assert s.sport is None


def test_sport_and_olympiad_capped_together():
    s = dialog.start()
    s, _ = dialog.handle(s, "c:level:base")
    s, _ = dialog.handle(s, "c:pedagogical:0")
    s, _ = dialog.handle(s, "c:target:0")
    s, _ = dialog.handle(s, "c:sport:champion_world")   # 10
    s, _ = dialog.handle(s, "c:olympcycle:1")           # winner 10
    assert dialog.compute(s).total == 10                # потолок 10


def test_result_text_includes_disclaimer():
    s = dialog.start()
    s, _ = dialog.handle(s, "c:level:base")
    s, _ = dialog.handle(s, "c:pedagogical:0")
    s, _ = dialog.handle(s, "c:target:0")
    s, _ = dialog.handle(s, "c:toggle:edu_honors")
    text = dialog.result_text(dialog.compute(s))
    assert "приёмной комиссией" in text or "предварительн" in text.lower()
    assert "10" in text
