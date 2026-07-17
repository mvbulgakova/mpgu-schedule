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
    bot.SUBS.clear()


def test_spisok_command_asks_for_code():
    out = bot.handle_message(chat_id=1, text="/spisok")
    assert bot.AWAITING_CODE.get(1) is True
    assert "код" in out.text.lower()


def test_code_after_spisok_is_looked_up(monkeypatch):
    monkeypatch.setattr(bot, "_lookup_code",
                        lambda code: bot.Reply(f"POSITIONS for {code}", []))
    bot.handle_message(chat_id=2, text="/spisok")
    out = bot.handle_message(chat_id=2, text="1281839")
    assert "POSITIONS for 1281839" in out.text
    assert 2 not in bot.AWAITING_CODE  # флаг снят


def test_spisok_with_inline_code(monkeypatch):
    monkeypatch.setattr(bot, "_lookup_code",
                        lambda code: bot.Reply(f"POS:{code}", []))
    out = bot.handle_message(chat_id=3, text="/spisok 999")
    assert "POS:999" in out.text


def test_volunteer_hours_take_priority_over_list_code(monkeypatch):
    # активна сессия калькулятора на шаге achieve → число = часы, не код списка
    monkeypatch.setattr(bot, "_lookup_code",
                        lambda code: bot.Reply("SHOULD_NOT_APPEAR", []))
    bot.handle_message(chat_id=4, text="/bally")
    bot.handle_callback(chat_id=4, data="c:level:base")
    bot.handle_callback(chat_id=4, data="c:pedagogical:1")
    bot.handle_callback(chat_id=4, data="c:target:0")
    bot.AWAITING_CODE[4] = True  # даже если флаг стоит — калькулятор важнее
    out = bot.handle_message(chat_id=4, text="200")
    assert bot.SESSIONS[4].volunteer_hours == 200
    assert "SHOULD_NOT_APPEAR" not in out.text


# ── Подписка «следи за кодом» ────────────────────────────────────────────────

META = {"updated_at": "2026-07-17T12:00:00+03:00", "lists": {
    "L1": {"direction": "44.03.01 История", "form": "очная", "kind": "бюджет"}}}
SHARD = {"updated_at": "t", "codes": {"12345": [
    {"list": "L1", "position": 5, "score_total": 250, "consent": False,
     "priority_pz": 1, "bvi": False, "status": "Участвует"}]}}


def _wire_fake_lists(monkeypatch, shard=SHARD):
    monkeypatch.setattr(bot.lists, "fetch_meta", lambda force=False: META)
    monkeypatch.setattr(bot.lists, "fetch_shard", lambda code: shard)


def test_lookup_offers_follow_button(monkeypatch):
    _wire_fake_lists(monkeypatch)
    out = bot._lookup_code("12345")
    data = [cb for row in out.keyboard for (_, cb) in row]
    assert "f:12345" in data


def test_follow_via_callback_and_unfollow(monkeypatch):
    _wire_fake_lists(monkeypatch)
    out = bot.handle_callback(chat_id=7, data="f:12345")
    assert "Слежу" in out.text
    assert bot.SUBS["7"]["code"] == "12345"
    assert bot.SUBS["7"]["last"] == {"L1": 5}
    out2 = bot.handle_message(chat_id=7, text="/unfollow")
    assert "отключена" in out2.text.lower()
    assert "7" not in bot.SUBS


def test_follow_command_with_code(monkeypatch):
    _wire_fake_lists(monkeypatch)
    out = bot.handle_message(chat_id=8, text="/follow 12345")
    assert "Слежу" in out.text and bot.SUBS["8"]["code"] == "12345"


def test_follow_unknown_code_not_subscribed(monkeypatch):
    _wire_fake_lists(monkeypatch, shard={"updated_at": "t", "codes": {}})
    out = bot.handle_message(chat_id=9, text="/follow 777777")
    assert "не оформлена" in out.text
    assert "9" not in bot.SUBS


def test_check_subs_sends_diff_once(monkeypatch):
    _wire_fake_lists(monkeypatch)
    bot.SUBS["7"] = {"code": "12345", "last": {"L1": 9},
                     "updated_at": "старая-метка"}
    sent = []
    monkeypatch.setattr(bot, "_send", lambda tok, chat, reply: sent.append((chat, reply.text)))
    bot._check_subs("tok")
    assert len(sent) == 1 and sent[0][0] == 7
    assert "9 → " in sent[0][1] and "5" in sent[0][1]
    # повторная проверка при тех же данных — тишина
    bot._check_subs("tok")
    assert len(sent) == 1
