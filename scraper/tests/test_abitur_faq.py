"""Тесты базы знаний и FAQ-маршрутизации.

Запуск: python -m pytest scraper/tests/test_abitur_faq.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import faq


def test_knowledge_base_has_key_anchors():
    kb = faq.load_knowledge()
    for anchor in ["приёмн", "ЕГЭ", "ДВИ", "общежит", "priem@mpgu.su",
                   "базовое высшее", "индивидуальн"]:
        assert anchor.lower() in kb.lower(), anchor


def test_route_commands():
    assert faq.route("/start")[0] == "start"
    assert faq.route("/help")[0] == "help"
    assert faq.route("/abitur")[0] == "menu"
    assert faq.route("/bally")[0] == "calc"
    assert faq.route("/bally@MpguBot")[0] == "calc"


def test_route_free_question():
    intent, _ = faq.route("нужна ли справка 086у?")
    assert intent == "free"


def test_topics_have_labels_and_answers():
    assert faq.TOPICS, "темы не заданы"
    for tid, (label, answer) in faq.TOPICS.items():
        assert label and answer
        assert "http" in answer or "mpgu" in answer.lower()


def test_topic_answer_known_and_unknown():
    sroki = faq.topic_answer("sroki")
    assert "25 июля" in sroki or "августа" in sroki
    assert faq.topic_answer("does-not-exist") is None
