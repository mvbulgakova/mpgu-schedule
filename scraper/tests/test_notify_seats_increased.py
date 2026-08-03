"""Тест CLI-отправителя уведомлений о подтверждённом росте КЦП (сеть замокана).

Запуск: python -m pytest scraper/tests/test_notify_seats_increased.py -v
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scraper.notify_seats_increased as NI


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_sends_only_to_subscribers_of_the_grown_list(tmp_path, monkeypatch):
    baseline = {"lists": {
        "G": {"main_kcp": True, "direction": "44.03.01 Тест", "form": "очная",
              "kcp_epk": 33},
    }}
    current = {"lists": {
        "G": {"main_kcp": True, "direction": "44.03.01 Тест", "form": "очная",
              "kcp_epk": 35},
    }}
    baseline_path = _write(tmp_path, "baseline_meta.json", baseline)
    meta_path = _write(tmp_path, "lists_meta.json", current)
    subs = {
        "111": {"code": "1234567", "last": {"G": 45}},
        "222": {"code": "7654321", "last": {}},           # не следит за G
        "333": {"code": "3333333", "last": {"Q1": 5}},    # следит за другим списком
    }
    subs_path = _write(tmp_path, "subs.json", subs)

    sent = []
    monkeypatch.setattr(NI, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))
    monkeypatch.setattr(NI.time, "sleep", lambda s: None)
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NI.main(["--baseline-path", str(baseline_path),
                 "--meta-path", str(meta_path),
                 "--subs-path", str(subs_path)])

    assert rc == 0
    assert len(sent) == 1
    assert sent[0][0] == 111
    expected_text = NI.quota_vacancy.format_seats_increased(
        old=33, new=35, direction="44.03.01 Тест", form="очная", code="1234567")
    assert sent[0][1] == expected_text


def test_two_grown_lists_send_distinct_messages_to_their_own_subscribers(tmp_path, monkeypatch):
    baseline = {"lists": {
        "G1": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 10},
        "G2": {"main_kcp": True, "direction": "B", "form": "заочная", "kcp_epk": 20},
    }}
    current = {"lists": {
        "G1": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 12},
        "G2": {"main_kcp": True, "direction": "B", "form": "заочная", "kcp_epk": 25},
    }}
    baseline_path = _write(tmp_path, "baseline_meta.json", baseline)
    meta_path = _write(tmp_path, "lists_meta.json", current)
    subs = {
        "111": {"code": "1111111", "last": {"G1": 5}},
        "222": {"code": "2222222", "last": {"G2": 15}},
    }
    subs_path = _write(tmp_path, "subs.json", subs)

    sent = []
    monkeypatch.setattr(NI, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))
    monkeypatch.setattr(NI.time, "sleep", lambda s: None)
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NI.main(["--baseline-path", str(baseline_path),
                 "--meta-path", str(meta_path),
                 "--subs-path", str(subs_path)])

    assert rc == 0
    assert len(sent) == 2
    by_chat = dict(sent)
    expected_g1 = NI.quota_vacancy.format_seats_increased(
        old=10, new=12, direction="A", form="очная", code="1111111")
    expected_g2 = NI.quota_vacancy.format_seats_increased(
        old=20, new=25, direction="B", form="заочная", code="2222222")
    assert by_chat[111] == expected_g1
    assert by_chat[222] == expected_g2

    out = None
    # Убедимся, что summary в выводе печатается (перехват отдельным тестом ниже
    # для четкости), здесь достаточно проверить отправку.


def test_two_grown_lists_summary_mentions_both(tmp_path, monkeypatch, capsys):
    baseline = {"lists": {
        "G1": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 10},
        "G2": {"main_kcp": True, "direction": "B", "form": "заочная", "kcp_epk": 20},
    }}
    current = {"lists": {
        "G1": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 12},
        "G2": {"main_kcp": True, "direction": "B", "form": "заочная", "kcp_epk": 25},
    }}
    baseline_path = _write(tmp_path, "baseline_meta.json", baseline)
    meta_path = _write(tmp_path, "lists_meta.json", current)
    subs = {
        "111": {"code": "1111111", "last": {"G1": 5}},
        "222": {"code": "2222222", "last": {"G2": 15}},
    }
    subs_path = _write(tmp_path, "subs.json", subs)

    monkeypatch.setattr(NI, "_send", lambda token, chat_id, reply: None)
    monkeypatch.setattr(NI.time, "sleep", lambda s: None)
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NI.main(["--baseline-path", str(baseline_path),
                 "--meta-path", str(meta_path),
                 "--subs-path", str(subs_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "G1" in out
    assert "G2" in out


def test_no_growth_sends_nothing(tmp_path, monkeypatch, capsys):
    baseline = {"lists": {
        "G": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 33},
    }}
    current = {"lists": {
        "G": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 33},
    }}
    baseline_path = _write(tmp_path, "baseline_meta.json", baseline)
    meta_path = _write(tmp_path, "lists_meta.json", current)
    subs_path = _write(tmp_path, "subs.json", {"111": {"code": "1", "last": {"G": 5}}})

    sent = []
    monkeypatch.setattr(NI, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NI.main(["--baseline-path", str(baseline_path),
                 "--meta-path", str(meta_path),
                 "--subs-path", str(subs_path)])

    assert rc == 0
    assert sent == []
    assert "Списков с увеличенным КЦП не найдено." in capsys.readouterr().out


def test_missing_bot_token_aborts(tmp_path, monkeypatch):
    baseline_path = _write(tmp_path, "baseline_meta.json", {"lists": {}})
    meta_path = _write(tmp_path, "lists_meta.json", {"lists": {}})
    subs_path = _write(tmp_path, "subs.json", {})
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    sent = []
    monkeypatch.setattr(NI, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))

    rc = NI.main(["--baseline-path", str(baseline_path),
                 "--meta-path", str(meta_path),
                 "--subs-path", str(subs_path)])

    assert rc == 1
    assert sent == []


def test_continues_after_one_send_failure_across_lists(tmp_path, monkeypatch):
    baseline = {"lists": {
        "G1": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 10},
        "G2": {"main_kcp": True, "direction": "B", "form": "заочная", "kcp_epk": 20},
    }}
    current = {"lists": {
        "G1": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 12},
        "G2": {"main_kcp": True, "direction": "B", "form": "заочная", "kcp_epk": 25},
    }}
    baseline_path = _write(tmp_path, "baseline_meta.json", baseline)
    meta_path = _write(tmp_path, "lists_meta.json", current)
    subs = {
        "111": {"code": "1111111", "last": {"G1": 5}},
        "222": {"code": "2222222", "last": {"G1": 8}},   # тоже следит за G1
        "333": {"code": "3333333", "last": {"G2": 15}},
    }
    subs_path = _write(tmp_path, "subs.json", subs)

    sent = []

    def fake_send(token, chat_id, reply):
        if chat_id == 222:
            raise RuntimeError("boom")
        sent.append((chat_id, reply.text))

    monkeypatch.setattr(NI, "_send", fake_send)
    monkeypatch.setattr(NI.time, "sleep", lambda s: None)
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NI.main(["--baseline-path", str(baseline_path),
                 "--meta-path", str(meta_path),
                 "--subs-path", str(subs_path)])

    assert rc == 0
    # 111 (G1) и 333 (G2) должны получить сообщения, несмотря на сбой на 222
    assert sorted(c for c, _ in sent) == [111, 333]


def test_continues_past_malformed_last_field(tmp_path, monkeypatch, capsys):
    """sub["last"] будучи списком роняет .get(...) без нашего try/except."""
    baseline = {"lists": {
        "G": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 10},
    }}
    current = {"lists": {
        "G": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 12},
    }}
    baseline_path = _write(tmp_path, "baseline_meta.json", baseline)
    meta_path = _write(tmp_path, "lists_meta.json", current)
    subs = {
        "111": {"code": "1111111", "last": ["oops", "not", "a", "dict"]},
        "222": {"code": "2222222", "last": {"G": 20}},
        "333": {"code": "3333333", "last": {"G": 30}},
    }
    subs_path = _write(tmp_path, "subs.json", subs)

    sent = []
    monkeypatch.setattr(NI, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))
    monkeypatch.setattr(NI.time, "sleep", lambda s: None)
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NI.main(["--baseline-path", str(baseline_path),
                 "--meta-path", str(meta_path),
                 "--subs-path", str(subs_path)])

    assert rc == 0
    assert sorted(c for c, _ in sent) == [222, 333]
    out = capsys.readouterr().out
    assert "с ошибкой: 1" in out


def test_continues_past_record_missing_code(tmp_path, monkeypatch, capsys):
    baseline = {"lists": {
        "G": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 10},
    }}
    current = {"lists": {
        "G": {"main_kcp": True, "direction": "A", "form": "очная", "kcp_epk": 12},
    }}
    baseline_path = _write(tmp_path, "baseline_meta.json", baseline)
    meta_path = _write(tmp_path, "lists_meta.json", current)
    subs = {
        "111": {"last": {"G": 10}},                       # нет ключа "code"
        "222": {"code": "2222222", "last": {"G": 20}},    # валидная запись
    }
    subs_path = _write(tmp_path, "subs.json", subs)

    sent = []
    monkeypatch.setattr(NI, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))
    monkeypatch.setattr(NI.time, "sleep", lambda s: None)
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NI.main(["--baseline-path", str(baseline_path),
                 "--meta-path", str(meta_path),
                 "--subs-path", str(subs_path)])

    assert rc == 0
    # запись без "code" не должна ронять весь прогон — оба чата получают
    # сообщение (отсутствующий code заменяется на "?" внутри текста)
    assert sorted(c for c, _ in sent) == [111, 222]
    assert "Отправлено всего: 2" in capsys.readouterr().out
