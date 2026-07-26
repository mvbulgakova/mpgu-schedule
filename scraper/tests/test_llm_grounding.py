"""Тесты заземления ИИ: дата «сегодня» и жёсткие правила про согласие/баллы."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import llm

_MSK = dt.timezone(dt.timedelta(hours=3))


def test_today_block_marks_passed_deadlines():
    # 26 июля: подача документов (25 июля) уже позади — нельзя советовать «успей»
    out = llm._today_block(dt.datetime(2026, 7, 26, 14, 0, tzinfo=_MSK))
    assert "26 июля 2026" in out
    passed = out.split("УЖЕ ПРОШЛИ:")[1].split("ВПЕРЕДИ:")[0]
    assert "25 июля" in passed
    ahead = out.split("ВПЕРЕДИ:")[1]
    assert "5 августа" in ahead and "25 июля" not in ahead


def test_today_block_earlier_date_keeps_deadline_ahead():
    out = llm._today_block(dt.datetime(2026, 7, 10, 9, 0, tzinfo=_MSK))
    assert "10 июля 2026" in out
    assert "25 июля" in out.split("ВПЕРЕДИ:")[1]


def test_system_prompt_has_date_and_hard_rules():
    sys_blocks = llm._build_system("БАЗА")
    text = sys_blocks[0]["text"]
    assert "=== СЕГОДНЯ:" in text
    # правило про одно согласие (живая ошибка: бот советовал «согласие в оба вуза»)
    assert "двух согласий не бывает" in text
    assert "в ОДНОМ вузе" in text
    # правило про потолок баллов (живая ошибка: «и 300, и выше»)
    assert "310" in text and "300 и выше" in text
