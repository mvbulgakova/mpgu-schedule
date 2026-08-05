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


# ── Подписка «обновление списков» (независимо от слежки за кодом) ─────────────

def _meta(src, upd="2026-08-05T10:00:00+03:00"):
    return {"updated_at": upd,
            "lists": {"G": {"page_updated_at": src, "direction": "44.03.01 X",
                            "form": "очная", "kind": "бюджет"}}}


def test_subscribe_to_list_updates_without_following_a_code(monkeypatch):
    monkeypatch.setattr(bot.lists, "fetch_meta",
                        lambda *a, **k: _meta("2026-08-05T09:50:00+03:00"))
    out = bot._handle_callback(chat_id=10, data="u:1")
    assert "10" in bot.SUBS
    sub = bot.SUBS["10"]
    assert sub.get("lists_updates") is True
    assert sub.get("src") == "2026-08-05T09:50:00+03:00"   # текущее — не шлём сразу
    assert sub.get("code") is None                          # код при этом не нужен
    assert "обновл" in out.text.lower()


def test_unsubscribe_from_list_updates_keeps_code_following(monkeypatch):
    monkeypatch.setattr(bot.lists, "fetch_meta",
                        lambda *a, **k: _meta("2026-08-05T09:50:00+03:00"))
    bot.SUBS["11"] = {"code": "1234567", "last": {"G": 5}, "updated_at": "t"}
    bot._handle_callback(chat_id=11, data="u:1")
    assert bot.SUBS["11"]["lists_updates"] is True
    bot._handle_callback(chat_id=11, data="u:0")
    assert bot.SUBS["11"].get("lists_updates") is not True
    assert bot.SUBS["11"]["code"] == "1234567"      # слежку за кодом не трогаем


def test_notifies_only_when_source_timestamp_advances(monkeypatch):
    sent = []
    monkeypatch.setattr(bot, "_send", lambda tok, chat, reply: sent.append((chat, reply.text)))
    monkeypatch.setattr(bot.lists, "fetch_shard", lambda code: None)
    bot.SUBS["12"] = {"lists_updates": True, "src": "2026-08-05T08:00:00+03:00"}

    monkeypatch.setattr(bot.lists, "fetch_meta",
                        lambda *a, **k: _meta("2026-08-05T08:00:00+03:00"))
    bot._check_subs("token")
    assert sent == []                                # не менялось — молчим

    monkeypatch.setattr(bot.lists, "fetch_meta",
                        lambda *a, **k: _meta("2026-08-05T09:50:00+03:00"))
    bot._check_subs("token")
    assert len(sent) == 1 and sent[0][0] == 12
    assert "09:50" in sent[0][1]
    assert bot.SUBS["12"]["src"] == "2026-08-05T09:50:00+03:00"

    sent.clear()
    bot._check_subs("token")
    assert sent == []                                # повторно то же — молчим


def test_code_follower_without_updates_subscription_gets_no_list_notice(monkeypatch):
    sent = []
    monkeypatch.setattr(bot, "_send", lambda tok, chat, reply: sent.append((chat, reply.text)))
    monkeypatch.setattr(bot.lists, "fetch_shard", lambda code: None)
    monkeypatch.setattr(bot.lists, "fetch_meta",
                        lambda *a, **k: _meta("2026-08-05T09:50:00+03:00"))
    bot.SUBS["13"] = {"code": "1234567", "last": {}, "updated_at": "old"}
    bot._check_subs("token")
    assert sent == []


# ── Подписчики /follow тоже узнают об обновлении списков ──────────────────────

def _no_change_shard():
    return {"updated_at": "t", "codes": {"1234567": [
        {"list": "G", "position": 5, "score_total": 240, "consent": True,
         "priority_pz": 1, "bvi": False, "status": ""}]}}


def test_existing_follower_is_not_spammed_on_first_seen_source(monkeypatch):
    """У старых подписок поля src нет — первый прогон только запоминает."""
    sent = []
    monkeypatch.setattr(bot, "_send", lambda t, c, r: sent.append((c, r.text)))
    monkeypatch.setattr(bot.lists, "fetch_meta",
                        lambda *a, **k: _meta("2026-08-05T10:00:00+03:00"))
    monkeypatch.setattr(bot.lists, "fetch_shard", lambda code: _no_change_shard())
    bot.SUBS["20"] = {"code": "1234567", "last": {"G": 5},
                      "updated_at": "2026-08-05T10:00:00+03:00"}
    bot._check_subs("token")
    assert sent == []
    assert bot.SUBS["20"]["src"] == "2026-08-05T10:00:00+03:00"


def test_follower_notified_when_source_updates_even_if_position_same(monkeypatch):
    sent = []
    monkeypatch.setattr(bot, "_send", lambda t, c, r: sent.append((c, r.text)))
    monkeypatch.setattr(bot.lists, "fetch_shard", lambda code: _no_change_shard())
    bot.SUBS["21"] = {"code": "1234567", "last": {"G": 5}, "updated_at": "old",
                      "src": "2026-08-05T10:00:00+03:00"}
    monkeypatch.setattr(bot.lists, "fetch_meta",
                        lambda *a, **k: _meta("2026-08-05T11:00:00+03:00"))
    bot._check_subs("token")
    assert len(sent) == 1
    assert "11:00" in sent[0][1] and "без изменений" in sent[0][1].lower()
    assert bot.SUBS["21"]["src"] == "2026-08-05T11:00:00+03:00"

    sent.clear()
    bot._check_subs("token")
    assert sent == []          # то же обновление второй раз не шлём


def test_position_diff_is_not_duplicated_by_update_notice(monkeypatch):
    """Если позиция сдвинулась — шлём только дифф, он и так про обновление."""
    sent = []
    monkeypatch.setattr(bot, "_send", lambda t, c, r: sent.append((c, r.text)))
    moved = {"updated_at": "t", "codes": {"1234567": [
        {"list": "G", "position": 3, "score_total": 240, "consent": True,
         "priority_pz": 1, "bvi": False, "status": ""}]}}
    monkeypatch.setattr(bot.lists, "fetch_shard", lambda code: moved)
    monkeypatch.setattr(bot.lists, "fetch_meta",
                        lambda *a, **k: _meta("2026-08-05T11:00:00+03:00"))
    bot.SUBS["22"] = {"code": "1234567", "last": {"G": 5}, "updated_at": "old",
                      "src": "2026-08-05T10:00:00+03:00"}
    bot._check_subs("token")
    assert len(sent) == 1
    assert "5" in sent[0][1] and "3" in sent[0][1]     # дифф позиции
    assert "без изменений" not in sent[0][1].lower()


def test_no_notice_when_source_did_not_move(monkeypatch):
    sent = []
    monkeypatch.setattr(bot, "_send", lambda t, c, r: sent.append((c, r.text)))
    monkeypatch.setattr(bot.lists, "fetch_shard", lambda code: _no_change_shard())
    monkeypatch.setattr(bot.lists, "fetch_meta",
                        lambda *a, **k: _meta("2026-08-05T10:00:00+03:00"))
    bot.SUBS["23"] = {"code": "1234567", "last": {"G": 5}, "updated_at": "old",
                      "src": "2026-08-05T10:00:00+03:00"}
    bot._check_subs("token")
    assert sent == []


# ── Отметку «видел» нельзя двигать раньше доставки ───────────────────────────

def test_source_mark_not_advanced_when_shard_fetch_fails(monkeypatch):
    """Сбой загрузки шарда не должен «съедать» обновление насовсем."""
    sent = []
    monkeypatch.setattr(bot, "_send", lambda t, c, r: sent.append(r.text))
    monkeypatch.setattr(bot.lists, "fetch_meta",
                        lambda *a, **k: _meta("2026-08-05T14:00:00+03:00"))
    monkeypatch.setattr(bot.lists, "fetch_shard", lambda code: None)   # CDN моргнул
    bot.SUBS["30"] = {"code": "1234567", "last": {"G": 5}, "updated_at": "old",
                      "src": "2026-08-05T13:00:00+03:00"}
    bot._check_subs("tok")
    assert sent == []
    assert bot.SUBS["30"]["src"] == "2026-08-05T13:00:00+03:00", \
        "отметка ушла вперёд без доставки — уведомление потеряно навсегда"

    # сеть вернулась — уведомление всё ещё должно уйти
    monkeypatch.setattr(bot.lists, "fetch_shard", lambda code: _no_change_shard())
    bot._check_subs("tok")
    assert len(sent) == 1 and "14:00" in sent[0]
    assert bot.SUBS["30"]["src"] == "2026-08-05T14:00:00+03:00"


def test_source_mark_not_advanced_when_send_fails(monkeypatch):
    def boom(t, c, r):
        raise RuntimeError("Telegram 500")
    monkeypatch.setattr(bot, "_send", boom)
    monkeypatch.setattr(bot.lists, "fetch_meta",
                        lambda *a, **k: _meta("2026-08-05T14:00:00+03:00"))
    monkeypatch.setattr(bot.lists, "fetch_shard", lambda code: _no_change_shard())
    bot.SUBS["31"] = {"code": "1234567", "last": {"G": 5}, "updated_at": "old",
                      "src": "2026-08-05T13:00:00+03:00"}
    bot._check_subs("tok")
    assert bot.SUBS["31"]["src"] == "2026-08-05T13:00:00+03:00"


def test_updates_only_sub_keeps_mark_when_send_fails(monkeypatch):
    def boom(t, c, r):
        raise RuntimeError("Telegram 500")
    monkeypatch.setattr(bot, "_send", boom)
    monkeypatch.setattr(bot.lists, "fetch_meta",
                        lambda *a, **k: _meta("2026-08-05T14:00:00+03:00"))
    monkeypatch.setattr(bot.lists, "fetch_shard", lambda code: None)
    bot.SUBS["32"] = {"lists_updates": True, "src": "2026-08-05T13:00:00+03:00"}
    bot._check_subs("tok")
    assert bot.SUBS["32"]["src"] == "2026-08-05T13:00:00+03:00"
