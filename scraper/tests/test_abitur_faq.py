"""Тесты базы знаний, FAQ-маршрутизации и маршрута дат.

Запуск: python -m pytest scraper/tests/test_abitur_faq.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import faq


def test_knowledge_base_has_key_anchors():
    kb = faq.load_knowledge()
    for anchor in ["приёмн", "ЕГЭ", "ДВИ", "общежит", "priem@mpgu.su",
                   "базовое высшее", "индивидуальн", "целев", "квот",
                   "Госуслуг", "согласие"]:
        assert anchor.lower() in kb.lower(), anchor


def test_knowledge_base_verified_facts():
    kb = faq.load_knowledge()
    # даты из Правил 2026 (разд. 6), а не из FAQ-2025
    assert "5 августа" in kb          # основной этап: согласие
    assert "27 августа" in kb         # платное БВО: договор+оплата
    # медосмотр — только для 44.00.00, а не «086/у всем»
    assert "44.00.00" in kb and "НЕ всем" in kb
    assert "ЗАКЛЮЧИТЕЛЬНОМ этапе" in kb or "ЗАКЛЮЧИТЕЛЬНОГО этапа" in kb  # ВсОШ=БВИ


def test_route_commands():
    assert faq.route("/start")[0] == "start"
    assert faq.route("/help")[0] == "help"
    assert faq.route("/abitur")[0] == "menu"
    assert faq.route("/bally")[0] == "calc"
    assert faq.route("/bally@MpguBot")[0] == "calc"
    assert faq.route("/sroki")[0] == "dates"
    assert faq.route("/spisok 123")[:2] == ("spisok", "123")


def test_route_free_question():
    intent, _ = faq.route("когда подавать документы?")
    assert intent == "free"


def test_topics_have_labels_and_answers():
    assert faq.TOPICS, "темы не заданы"
    for tid, (label, answer) in faq.TOPICS.items():
        assert label and answer
        assert "http" in answer or "mpgu" in answer.lower() or "trudvsem" in answer


def test_topic_answer_known_and_unknown():
    doc = faq.topic_answer("documents")
    assert "Госуслуг" in doc and "оригинал" in doc.lower()
    assert faq.topic_answer("does-not-exist") is None


def test_dates_route_walk_base_budget_vi():
    text, kb = faq.dates_step("")
    assert "куда" in text.lower() or "Сроки" in text
    data = [cb for row in kb for (_, cb) in row]
    assert "d:base" in data and "d:spec" in data

    text, kb = faq.dates_step("base")
    data = [cb for row in kb for (_, cb) in row]
    assert "d:base:budget" in data and "d:base:paid" in data

    text, kb = faq.dates_step("base:budget")
    data = [cb for row in kb for (_, cb) in row]
    assert "d:base:budget:vi" in data and "d:base:budget:ege" in data

    text, kb = faq.dates_step("base:budget:vi")
    assert kb == []
    assert "15 июля" in text and "5 августа" in text


def test_dates_route_finals_have_correct_deadlines():
    assert "25 июля" in faq.dates_step("base:budget:ege")[0]
    assert "27 августа" in faq.dates_step("base:paid")[0]
    assert "8 августа" in faq.dates_step("spec:budget")[0]
    assert "28 августа" in faq.dates_step("spec:paid")[0]


def test_dates_route_unknown_path_recovers():
    text, kb = faq.dates_step("bogus:path")
    assert "/sroki" in text
