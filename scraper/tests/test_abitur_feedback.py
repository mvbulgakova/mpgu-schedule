"""Тесты сбора обратной связи (отзывы студентов + вопросы). Без сети.

Запуск: python -m pytest scraper/tests/test_abitur_feedback.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import feedback as F
import scraper.telegram_bot as bot


def setup_function(_):
    bot.AWAITING_FEEDBACK.clear()
    bot.FEEDBACK.clear()
    bot.ADMIN_CHAT_ID = 0


def test_store_and_csv_roundtrip(tmp_path):
    p = tmp_path / "fb.json"
    F.add(p, [], user_id=123, kind="otzyv", text="общага норм, но душ по расписанию")
    items = F.load(p)
    assert len(items) == 1
    e = items[0]
    assert e["kind"] == "otzyv" and "общага" in e["text"]
    assert "123" not in str(e)                # сырой user_id не хранится
    assert len(e["anon"]) == 12               # хеш-идентификатор
    csv_bytes = F.to_csv(items)
    assert csv_bytes.startswith(b"\xef\xbb\xbf")   # BOM для Excel
    assert "общага".encode("utf-8") in csv_bytes


def test_same_user_same_anon(tmp_path):
    p = tmp_path / "fb.json"
    F.add(p, [], 42, "otzyv", "раз")
    items = F.add(p, F.load(p), 42, "otzyv", "два")
    assert items[0]["anon"] == items[1]["anon"]
    other = F.add(p, items, 43, "otzyv", "три")
    assert other[2]["anon"] != items[0]["anon"]


def test_otzyv_flow_saves_and_thanks():
    bot.ADMIN_CHAT_ID = 0
    out = bot.handle_message(chat_id=70, text="/otzyv")
    assert "впечатлен" in out.text.lower() or "отзыв" in out.text.lower()
    assert bot.AWAITING_FEEDBACK.get(70) is True
    out2 = bot.handle_message(chat_id=70, text="преподы идут навстречу, сессия ок")
    assert "спасибо" in out2.text.lower()
    assert 70 not in bot.AWAITING_FEEDBACK
    assert any("навстречу" in e["text"] for e in bot.FEEDBACK)


def test_otzyv_inline_text():
    out = bot.handle_message(chat_id=71, text="/otzyv общежитие на Космонавтов чистое")
    assert "спасибо" in out.text.lower()
    assert any("Космонавтов" in e["text"] for e in bot.FEEDBACK)


def test_free_questions_also_logged(monkeypatch):
    monkeypatch.setattr(bot, "_answer_free", lambda cid, q: "ответ")
    bot.handle_message(chat_id=72, text="а трудно ли учиться на физмате?")
    assert any(e["kind"] == "question" and "физмате" in e["text"]
               for e in bot.FEEDBACK)


def test_admin_commands_silent_for_strangers():
    bot.ADMIN_CHAT_ID = 999
    out = bot.handle_message(chat_id=73, text="/export")
    assert out.text == ""          # молча (пустой ответ не отправляется)
    out2 = bot.handle_message(chat_id=73, text="/fb_stats")
    assert out2.text == ""


def test_admin_stats_and_myid():
    bot.ADMIN_CHAT_ID = 74
    bot.handle_message(chat_id=75, text="/otzyv душно в корпусе 4")
    out = bot.handle_message(chat_id=74, text="/fb_stats")
    assert "1" in out.text and ("корпус" in out.text or "душно" in out.text)
    out2 = bot.handle_message(chat_id=76, text="/myid")
    assert "76" in out2.text
