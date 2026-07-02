"""Тесты потока проверки списков в боте (без сети).

Запуск: python -m pytest scraper/tests/test_abitur_bot_lists.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scraper.telegram_bot as bot


def setup_function(_):
    bot.SESSIONS.clear()
    bot.AWAITING_CODE.clear()


def test_spisok_command_asks_for_code():
    out = bot.handle_message(chat_id=1, text="/spisok")
    assert bot.AWAITING_CODE.get(1) is True
    assert "код" in out.text.lower()


def test_code_after_spisok_is_looked_up(monkeypatch):
    monkeypatch.setattr(bot, "_lookup_code", lambda code: f"POSITIONS for {code}")
    bot.handle_message(chat_id=2, text="/spisok")
    out = bot.handle_message(chat_id=2, text="1281839")
    assert "POSITIONS for 1281839" in out.text
    assert 2 not in bot.AWAITING_CODE  # флаг снят


def test_spisok_with_inline_code(monkeypatch):
    monkeypatch.setattr(bot, "_lookup_code", lambda code: f"POS:{code}")
    out = bot.handle_message(chat_id=3, text="/spisok 999")
    assert "POS:999" in out.text


def test_volunteer_hours_take_priority_over_list_code(monkeypatch):
    # активна сессия калькулятора на шаге achieve → число = часы, не код списка
    monkeypatch.setattr(bot, "_lookup_code", lambda code: "SHOULD_NOT_APPEAR")
    bot.handle_message(chat_id=4, text="/bally")
    bot.handle_callback(chat_id=4, data="c:level:base")
    bot.handle_callback(chat_id=4, data="c:pedagogical:1")
    bot.handle_callback(chat_id=4, data="c:target:0")
    bot.AWAITING_CODE[4] = True  # даже если флаг стоит — калькулятор важнее
    out = bot.handle_message(chat_id=4, text="200")
    assert bot.SESSIONS[4].volunteer_hours == 200
    assert "SHOULD_NOT_APPEAR" not in out.text
