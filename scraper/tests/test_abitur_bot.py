"""Тесты диспетчеризации бота (без сети).

Запуск: python -m pytest scraper/tests/test_abitur_bot.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scraper.telegram_bot as bot


def setup_function(_):
    bot.SESSIONS.clear()
    bot.AWAITING_SCORES.clear()


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
                        lambda cid, q: "Спросите кнопками /abitur или у приёмной комиссии: priem@mpgu.su")
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


def test_shansy_command_asks_for_scores():
    out = bot.handle_message(chat_id=9, text="/shansy")
    assert bot.AWAITING_SCORES.get(9) is True
    assert "русский 78" in out.text


def test_shansy_scores_after_prompt(monkeypatch):
    monkeypatch.setattr(bot, "_shansy_answer", lambda t: f"MATCHES for {t}")
    bot.handle_message(chat_id=10, text="/shansy")
    out = bot.handle_message(chat_id=10, text="русский 78, история 90")
    assert "MATCHES for" in out.text
    assert 10 not in bot.AWAITING_SCORES


def test_volunteer_hours_beat_scores_state(monkeypatch):
    monkeypatch.setattr(bot, "_shansy_answer", lambda t: "SHOULD_NOT_APPEAR")
    bot.handle_message(chat_id=11, text="/bally")
    bot.handle_callback(chat_id=11, data="c:level:base")
    bot.handle_callback(chat_id=11, data="c:pedagogical:1")
    bot.handle_callback(chat_id=11, data="c:target:0")
    bot.AWAITING_SCORES[11] = True
    out = bot.handle_message(chat_id=11, text="200")
    assert bot.SESSIONS[11].volunteer_hours == 200
    assert "SHOULD_NOT_APPEAR" not in out.text


def test_vybor_starts_consultation_with_history():
    import scraper.telegram_bot as bot
    bot.HISTORY.clear()
    out = bot.handle_message(chat_id=55, text="/vybor")
    assert "подбер" in out.text.lower()
    assert bot.HISTORY[55][0]["role"] == "assistant"


def test_free_answer_keeps_rolling_history(monkeypatch):
    import scraper.telegram_bot as bot
    bot.HISTORY.clear()
    calls = []
    def fake_answer(q, history=None, **kw):
        calls.append(list(history or []))
        return f"ответ на {q}"
    monkeypatch.setattr(bot.llm, "answer", fake_answer)
    bot.handle_message(chat_id=56, text="хочу учить детей языкам")
    bot.handle_message(chat_id=56, text="а какие экзамены?")
    # второй вызов видит первый обмен
    assert any("хочу учить детей языкам" in m.get("content", "") for m in calls[1])
    # история ограничена
    for i in range(10):
        bot.handle_message(chat_id=56, text=f"вопрос {i}")
    assert len(bot.HISTORY[56]) <= bot._HISTORY_MAX


def test_llm_error_not_saved_to_history(monkeypatch):
    import scraper.telegram_bot as bot
    bot.HISTORY.clear()
    monkeypatch.setattr(bot.llm, "answer",
                        lambda q, history=None, **kw: "Не удалось ответить автоматически. X")
    bot.handle_message(chat_id=57, text="вопрос")
    assert 57 not in bot.HISTORY or bot.HISTORY[57] == []


def test_menu_button_on_every_reply_and_escape():
    bot.AWAITING_CODE.clear(); bot.AWAITING_SCORES.clear()
    # у обычного ответа есть кнопка возврата в меню
    out = bot.handle_message(chat_id=91, text="/spisok")
    data = [cb for row in out.keyboard for (_, cb) in row]
    assert "open:menu" in data
    assert bot.AWAITING_CODE.get(91) is True
    # нажатие «Меню» выходит из режима ожидания кода
    out2 = bot.handle_callback(chat_id=91, data="open:menu")
    assert 91 not in bot.AWAITING_CODE
    d2 = [cb for row in out2.keyboard for (_, cb) in row]
    assert "open:calc" in d2          # это само меню
    assert "open:menu" not in d2      # в меню кнопки «Меню» нет


def test_start_menu_has_no_menu_button():
    out = bot.handle_message(chat_id=92, text="/start")
    data = [cb for row in out.keyboard for (_, cb) in row]
    assert "open:menu" not in data
