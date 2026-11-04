"""Объединение пользователей бота без двойного счёта.

Запуск: python -m pytest scraper/tests/test_count_users.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper import count_users as C
from scraper.abitur import feedback


def test_union_dedups_people_who_both_subscribed_and_wrote():
    """Один человек, и подписавшийся, и писавший текстом, считается один раз."""
    subs = {"111": {"code": "x"}, "222": {"code": "y"},
            C._ORDERS_KEY: {"sent": []}}
    fb = [{"anon": feedback.anon(111), "kind": "question", "text": "a"},
          {"anon": feedback.anon(333), "kind": "question", "text": "b"}]
    r = C.count(subs, fb)
    assert r["feedback"] == 2        # 111, 333
    assert r["subscribers"] == 2     # 111, 222
    assert r["overlap"] == 1         # 111 — в обоих
    assert r["union"] == 3           # 111, 222, 333


def test_service_record_is_not_counted_as_a_user():
    assert C.count({C._ORDERS_KEY: {"sent": []}}, [])["union"] == 0


def test_subscriber_hash_matches_feedback_hash_for_same_id():
    """Ключ subs — строка, feedback хеширует int; хеши должны совпасть."""
    assert C.subscriber_hashes({"777": {}}) == {feedback.anon(777)}


def test_empty_inputs_give_zero():
    assert C.count({}, [])["union"] == 0
