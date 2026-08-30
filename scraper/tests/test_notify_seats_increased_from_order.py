"""Тест CLI-отправителя уведомлений о росте КЦП по приказу (сеть замокана).

Запуск: python -m pytest scraper/tests/test_notify_seats_increased_from_order.py -v
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scraper.notify_seats_increased_from_order as NIO


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _base(tmp_path, kcp_general=10, kcp_quota=2):
    baseline = {"lists": {
        "G": {"main_kcp": True, "direction": "44.03.01 Тест", "form": "очная",
              "kcp_epk": kcp_general},
        "Q": {"quota": True, "direction": "44.03.01 Тест", "form": "очная",
              "kcp_epk": kcp_quota},
    }}
    return _write(tmp_path, "baseline_meta.json", baseline)


def test_sends_only_to_subscribers_of_the_grown_list(tmp_path, monkeypatch):
    baseline_path = _base(tmp_path, kcp_general=10, kcp_quota=2)
    order_records = [
        {"direction": "44.03.01 Тест", "form": "очная",
         "quota_kind": "особая", "count": 1},
    ]
    order_path = _write(tmp_path, "order_records.json", order_records)
    subs = {
        "111": {"code": "1234567", "last": {"G": 45}},
        "222": {"code": "7654321", "last": {}},           # не следит за G
    }
    subs_path = _write(tmp_path, "subs.json", subs)

    sent = []
    monkeypatch.setattr(NIO, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))
    monkeypatch.setattr(NIO.time, "sleep", lambda s: None)
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NIO.main(["--baseline-path", str(baseline_path),
                  "--order-records-path", str(order_path),
                  "--subs-path", str(subs_path)])

    assert rc == 0
    assert len(sent) == 1
    assert sent[0][0] == 111
    expected_text = NIO.quota_vacancy.format_seats_increased(
        old=10, new=11, direction="44.03.01 Тест", form="очная",
        code="1234567", enrolled=0)
    assert sent[0][1] == expected_text


def test_exclude_path_filters_out_already_notified_codes(tmp_path, monkeypatch):
    baseline_path = _base(tmp_path, kcp_general=10, kcp_quota=2)
    order_records = [
        {"direction": "44.03.01 Тест", "form": "очная",
         "quota_kind": "особая", "count": 1},
    ]
    order_path = _write(tmp_path, "order_records.json", order_records)
    exclude_path = _write(tmp_path, "exclude.json", ["G"])
    subs_path = _write(tmp_path, "subs.json",
                       {"111": {"code": "1234567", "last": {"G": 45}}})

    sent = []
    monkeypatch.setattr(NIO, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))
    monkeypatch.setattr(NIO.time, "sleep", lambda s: None)
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NIO.main(["--baseline-path", str(baseline_path),
                  "--order-records-path", str(order_path),
                  "--subs-path", str(subs_path),
                  "--exclude-path", str(exclude_path)])

    assert rc == 0
    assert sent == []


def test_no_growth_sends_nothing(tmp_path, monkeypatch, capsys):
    baseline_path = _base(tmp_path, kcp_general=10, kcp_quota=2)
    order_records = [
        {"direction": "44.03.01 Тест", "form": "очная",
         "quota_kind": "особая", "count": 2},   # съедает весь квотный резерв
    ]
    order_path = _write(tmp_path, "order_records.json", order_records)
    subs_path = _write(tmp_path, "subs.json",
                       {"111": {"code": "1", "last": {"G": 5}}})

    sent = []
    monkeypatch.setattr(NIO, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NIO.main(["--baseline-path", str(baseline_path),
                  "--order-records-path", str(order_path),
                  "--subs-path", str(subs_path)])

    assert rc == 0
    assert sent == []
    assert "не найдено" in capsys.readouterr().out


def test_missing_bot_token_aborts(tmp_path, monkeypatch):
    baseline_path = _write(tmp_path, "baseline_meta.json", {"lists": {}})
    order_path = _write(tmp_path, "order_records.json", [])
    subs_path = _write(tmp_path, "subs.json", {})
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    sent = []
    monkeypatch.setattr(NIO, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))

    rc = NIO.main(["--baseline-path", str(baseline_path),
                  "--order-records-path", str(order_path),
                  "--subs-path", str(subs_path)])

    assert rc == 1
    assert sent == []


def test_missing_order_records_file_aborts_gracefully(tmp_path, monkeypatch):
    baseline_path = _base(tmp_path)
    subs_path = _write(tmp_path, "subs.json", {})
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NIO.main(["--baseline-path", str(baseline_path),
                  "--order-records-path", str(tmp_path / "missing.json"),
                  "--subs-path", str(subs_path)])

    assert rc == 0


def test_two_grown_lists_send_distinct_messages_to_their_own_subscribers(
        tmp_path, monkeypatch):
    baseline = {"lists": {
        "G1": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 10},
        "Q1": {"quota": True, "direction": "A", "form": "очная", "kcp_epk": 2},
        "G2": {"main_kcp": True, "direction": "B", "form": "заочная", "kcp_epk": 20},
        "Q2": {"quota": True, "direction": "B", "form": "заочная", "kcp_epk": 3},
    }}
    baseline_path = _write(tmp_path, "baseline_meta.json", baseline)
    order_records = [
        {"direction": "A", "form": "очная",
         "quota_kind": "особая", "count": 1},
        {"direction": "B", "form": "заочная",
         "quota_kind": "целевая", "count": 1},
    ]
    order_path = _write(tmp_path, "order_records.json", order_records)
    subs = {
        "111": {"code": "1111111", "last": {"G1": 5}},
        "222": {"code": "2222222", "last": {"G2": 15}},
    }
    subs_path = _write(tmp_path, "subs.json", subs)

    sent = []
    monkeypatch.setattr(NIO, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))
    monkeypatch.setattr(NIO.time, "sleep", lambda s: None)
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NIO.main(["--baseline-path", str(baseline_path),
                  "--order-records-path", str(order_path),
                  "--subs-path", str(subs_path)])

    assert rc == 0
    by_chat = dict(sent)
    assert "11→12" not in by_chat.get(111, "")  # sanity: not garbled
    assert by_chat[111].startswith("📈")
    assert by_chat[222].startswith("📈")
