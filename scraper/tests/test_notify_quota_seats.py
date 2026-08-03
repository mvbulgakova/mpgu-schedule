"""Тест CLI-отправителя предварительных уведомлений (сеть замокана).

Запуск: python -m pytest scraper/tests/test_notify_quota_seats.py -v
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scraper.notify_quota_seats as NQ


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_sends_only_to_subscribers_with_known_position(tmp_path, monkeypatch):
    meta = {"lists": {
        "G": {"main_kcp": True, "direction": "44.03.01 Тест", "form": "очная",
              "unit": "ИФ", "kcp_epk": 33},
        "Q1": {"quota": True, "direction": "44.03.01 Тест", "form": "очная",
               "unit": "ИФ", "vid_mest": "отдельная квота",
               "kcp_epk": 9, "enrolled": 7},
    }}
    meta_path = _write(tmp_path, "lists_meta.json", meta)
    subs = {
        "111": {"code": "1234567", "last": {"G": 45}},
        "222": {"code": "7654321", "last": {}},   # нет сохранённой позиции
    }
    subs_path = _write(tmp_path, "subs.json", subs)

    sent = []
    monkeypatch.setattr(NQ, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))
    monkeypatch.setattr(NQ.time, "sleep", lambda s: None)
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NQ.main(["--code", "G", "--subs-path", str(subs_path),
                 "--meta-path", str(meta_path)])

    assert rc == 0
    assert len(sent) == 1
    assert sent[0][0] == 111
    assert "45-е из 33" in sent[0][1]
    assert "~35" in sent[0][1]


def test_no_send_without_vacancy(tmp_path, monkeypatch, capsys):
    meta = {"lists": {
        "G": {"main_kcp": True, "direction": "D", "form": "очная",
              "unit": "U", "kcp_epk": 33},
    }}
    meta_path = _write(tmp_path, "lists_meta.json", meta)
    subs_path = _write(tmp_path, "subs.json", {})

    sent = []
    monkeypatch.setattr(NQ, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NQ.main(["--code", "G", "--subs-path", str(subs_path),
                 "--meta-path", str(meta_path)])

    assert rc == 0
    assert sent == []
    assert "не найдено" in capsys.readouterr().out


def test_missing_bot_token_aborts(tmp_path, monkeypatch):
    meta_path = _write(tmp_path, "lists_meta.json", {"lists": {}})
    subs_path = _write(tmp_path, "subs.json", {})
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    rc = NQ.main(["--code", "G", "--subs-path", str(subs_path),
                 "--meta-path", str(meta_path)])

    assert rc == 1
