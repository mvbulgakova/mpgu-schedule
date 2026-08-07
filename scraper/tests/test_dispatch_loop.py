"""Тесты тикера, поднимающего сегментированный обход (scraper/dispatch_loop.py).

Запуск: python -m pytest scraper/tests/test_dispatch_loop.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper import crawl_loop as CL
from scraper import dispatch_loop as DL


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def _env(monkeypatch, **extra):
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    monkeypatch.setenv("GITHUB_REPOSITORY", "mvbulgakova/mpgu-schedule")
    monkeypatch.setenv("GITHUB_REF_NAME", "claude/migrate-mpgu-schedule-jj5gV")
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def test_dispatch_posts_to_the_workflow_dispatch_endpoint(monkeypatch):
    seen = {}

    class FakeResp:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        seen["body"] = req.data.decode("utf-8")
        seen["auth"] = req.get_header("Authorization")
        return FakeResp()

    monkeypatch.setattr(DL.urllib.request, "urlopen", fake_urlopen)
    DL.dispatch("fetch-lists-sharded.yml", "main", "o/r", "t0ken")

    assert seen["url"] == ("https://api.github.com/repos/o/r/actions/workflows/"
                           "fetch-lists-sharded.yml/dispatches")
    assert seen["method"] == "POST"
    assert '"ref": "main"' in seen["body"]
    assert seen["auth"] == "Bearer t0ken"


def test_ticker_fires_on_every_cycle(monkeypatch):
    """Ритм задаёт долгий прогон: обход поднимается раз в интервал."""
    clock = Clock()
    calls = []
    _env(monkeypatch)
    monkeypatch.setattr(CL.time, "time", clock.time)
    monkeypatch.setattr(CL.time, "sleep", clock.sleep)
    monkeypatch.setattr(DL, "dispatch",
                        lambda w, r, repo, t: calls.append((w, r)))

    assert DL.main(["--seconds", "1000", "--interval", "300"]) == 0
    assert len(calls) == 4
    assert calls[0] == ("fetch-lists-sharded.yml",
                        "claude/migrate-mpgu-schedule-jj5gV")


def test_a_rejected_dispatch_does_not_stop_the_ticker(monkeypatch):
    """Отказ API — не повод замолчать до следующего крона.

    Крон здесь только поднимает прогон; если тикер умрёт на первой ошибке,
    обновления встанут на часы — ровно то, от чего мы уходили.
    """
    clock = Clock()
    calls = []
    _env(monkeypatch)
    monkeypatch.setattr(CL.time, "time", clock.time)
    monkeypatch.setattr(CL.time, "sleep", clock.sleep)

    def flaky(w, r, repo, t):
        calls.append(w)
        if len(calls) == 1:
            raise RuntimeError("403 Resource not accessible by integration")

    monkeypatch.setattr(DL, "dispatch", flaky)
    assert DL.main(["--seconds", "600", "--interval", "200"]) == 0
    assert len(calls) == 3


def test_missing_settings_fail_loudly_instead_of_spinning(monkeypatch):
    """Без токена тикер выглядел бы работающим, ничего не запуская."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    assert DL.main(["--seconds", "60", "--interval", "60"]) == 1
