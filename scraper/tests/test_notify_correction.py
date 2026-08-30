"""Тест CLI точечной корректирующей рассылки (сеть замокана)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scraper.notify_correction as NC


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_sends_only_to_subscribers_tracking_the_code(tmp_path, monkeypatch):
    subs = {
        "111": {"code": "1234567", "last": {"000000690": 5}},
        "222": {"code": "7654321", "last": {"000000555": 3}},  # другой код
        "333": {"code": "3333333", "last": {}},
    }
    subs_path = _write(tmp_path, "subs.json", subs)

    sent = []
    monkeypatch.setattr(NC, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))
    monkeypatch.setattr(NC.time, "sleep", lambda s: None)
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NC.main(["--list-code", "000000690", "--message", "Уточнение текста",
                 "--subs-path", str(subs_path)])

    assert rc == 0
    assert sent == [(111, "Уточнение текста")]


def test_missing_bot_token_aborts(tmp_path, monkeypatch):
    subs_path = _write(tmp_path, "subs.json", {})
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    sent = []
    monkeypatch.setattr(NC, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))

    rc = NC.main(["--list-code", "000000690", "--message", "текст",
                 "--subs-path", str(subs_path)])

    assert rc == 1
    assert sent == []


def test_missing_message_aborts(tmp_path, monkeypatch):
    subs_path = _write(tmp_path, "subs.json", {})
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.delenv("CORRECTION_MESSAGE", raising=False)

    sent = []
    monkeypatch.setattr(NC, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))

    rc = NC.main(["--list-code", "000000690", "--subs-path", str(subs_path)])

    assert rc == 1
    assert sent == []


def test_continues_past_malformed_last_field(tmp_path, monkeypatch, capsys):
    subs = {
        "111": {"code": "1111111", "last": ["oops", "not", "a", "dict"]},
        "222": {"code": "2222222", "last": {"000000690": 10}},
    }
    subs_path = _write(tmp_path, "subs.json", subs)

    sent = []
    monkeypatch.setattr(NC, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))
    monkeypatch.setattr(NC.time, "sleep", lambda s: None)
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NC.main(["--list-code", "000000690", "--message", "текст",
                 "--subs-path", str(subs_path)])

    assert rc == 0
    assert sent == [(222, "текст")]
    assert "с ошибкой: 1" in capsys.readouterr().out


def test_continues_after_send_failure(tmp_path, monkeypatch):
    subs = {
        "111": {"code": "1111111", "last": {"000000690": 5}},
        "222": {"code": "2222222", "last": {"000000690": 10}},
    }
    subs_path = _write(tmp_path, "subs.json", subs)

    def fake_send(token, chat_id, reply):
        if chat_id == 111:
            raise RuntimeError("boom")

    sent = []
    monkeypatch.setattr(NC, "_send", fake_send)
    monkeypatch.setattr(NC.time, "sleep", lambda s: None)
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NC.main(["--list-code", "000000690", "--message", "текст",
                 "--subs-path", str(subs_path)])

    assert rc == 0
