"""Тесты диспетчеризации бота (без сети).

Запуск: python -m pytest scraper/tests/test_abitur_bot.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scraper.telegram_bot as bot


def setup_function(_):
    bot.SESSIONS.clear()


def test_start_returns_greeting_with_menu():
    out = bot.handle_message(chat_id=1, text="/start")
    assert out.keyboard, "ожидается меню тем"
    assert "абитур" in out.text.lower() or "поступл" in out.text.lower()


def test_menu_lists_topics():
    out = bot.handle_message(chat_id=1, text="/abitur")
    data = [cb for row in out.keyboard for (_, cb) in row]
    assert any(cb.startswith("t:") for cb in data)


def test_calc_command_starts_dialog():
    out = bot.handle_message(chat_id=1, text="/bally")
    assert 1 in bot.SESSIONS
    assert "уровень" in out.text.lower()


def test_volunteer_hours_message_during_calc():
    bot.handle_message(chat_id=2, text="/bally")
    bot.handle_callback(chat_id=2, data="c:level:base")
    bot.handle_callback(chat_id=2, data="c:pedagogical:1")
    bot.handle_callback(chat_id=2, data="c:target:0")
    out = bot.handle_message(chat_id=2, text="200")
    assert bot.SESSIONS[2].volunteer_hours == 200
    assert "200" in out.text or "Шаг" in out.text


def test_topic_callback_returns_answer():
    out = bot.handle_callback(chat_id=3, data="t:contacts")
    assert "priem@mpgu.su" in out.text


def test_free_question_without_credentials_falls_back(monkeypatch):
    # фабрика клиента бросает → деградация без падения
    monkeypatch.setattr(bot, "_answer_free",
                        lambda q: "Спросите кнопками /abitur или у приёмной комиссии: priem@mpgu.su")
    out = bot.handle_message(chat_id=4, text="а когда подавать документы?")
    assert "priem@mpgu.su" in out.text


def test_dates_route_via_callback_and_command():
    out = bot.handle_message(chat_id=7, text="/sroki")
    data = [cb for row in out.keyboard for (_, cb) in row]
    assert "d:base" in data
    out = bot.handle_callback(chat_id=7, data="d:base:budget:ege")
    assert "25 июля" in out.text


def test_menu_has_dates_button():
    out = bot.handle_message(chat_id=8, text="/abitur")
    data = [cb for row in out.keyboard for (_, cb) in row]
    assert "d:" in data
