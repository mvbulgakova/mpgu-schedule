"""Тесты долгоживущего цикла обхода (scraper/crawl_loop.py).

Время подменяем фальшивыми часами: цикл рассчитан на часы работы, ждать
их в тестах нельзя, а проверять надо именно арифметику пауз и дедлайна.

Запуск: python -m pytest scraper/tests/test_crawl_loop.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper import crawl_loop as CL


class Clock:
    """Часы, которые двигает только sleep и сами проходы."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def _patch(monkeypatch, clock, build):
    import scraper.build_lists_index as BLI
    monkeypatch.setattr(CL.time, "time", clock.time)
    monkeypatch.setattr(CL.time, "sleep", clock.sleep)
    monkeypatch.setattr(BLI, "main", build)


def test_loop_keeps_the_requested_interval_between_passes(monkeypatch):
    """Проход должен начинаться не чаще раза в --interval, а не подряд.

    Иначе один раннер молотит epk25 без остановки: и лимит на адрес,
    и коммит в data на каждый чих.
    """
    clock = Clock()
    passes = []

    def build():
        passes.append(clock.now)
        clock.now += 200          # проход занял 200с
        return 0

    _patch(monkeypatch, clock, build)
    CL.main(["--seconds", "1000", "--interval", "300"])

    assert len(passes) == 4, f"проходов: {len(passes)}"
    # между НАЧАЛАМИ проходов ровно interval
    assert [b - a for a, b in zip(passes, passes[1:])] == [300, 300, 300]
    assert clock.slept[:3] == [100, 100, 100]


def test_slow_pass_is_not_delayed_further(monkeypatch):
    """Если проход дольше интервала — следующий стартует сразу, без паузы."""
    clock = Clock()
    passes = []

    def build():
        passes.append(clock.now)
        clock.now += 500          # дольше интервала
        return 0

    _patch(monkeypatch, clock, build)
    CL.main(["--seconds", "1000", "--interval", "300"])

    assert len(passes) == 2
    assert clock.slept == [], f"лишние паузы: {clock.slept}"


def test_failed_pass_does_not_stop_the_loop(monkeypatch):
    """Упавший проход не повод молчать до следующего запуска по расписанию."""
    clock = Clock()
    passes = []

    def build():
        passes.append(clock.now)
        clock.now += 100
        if len(passes) == 1:
            raise RuntimeError("epk25 прилёг")
        return 0

    _patch(monkeypatch, clock, build)
    rc = CL.main(["--seconds", "600", "--interval", "200"])

    assert rc == 0
    assert len(passes) == 3, "цикл должен был продолжиться после ошибки"


def test_loop_never_sleeps_past_its_deadline(monkeypatch):
    """Спать дольше остатка нельзя: job убьют таймаутом прямо во сне."""
    clock = Clock()
    start = clock.now

    def build():
        clock.now += 10
        return 0

    _patch(monkeypatch, clock, build)
    CL.main(["--seconds", "250", "--interval", "100"])

    assert clock.now <= start + 250, f"цикл перебрал: {clock.now - start}s"


def test_defaults_come_from_environment(monkeypatch):
    """Workflow задаёт RUN_SECONDS/CYCLE_SECONDS через env, как боту."""
    clock = Clock()
    passes = []

    def build():
        passes.append(clock.now)
        clock.now += 50
        return 0

    monkeypatch.setenv("RUN_SECONDS", "200")
    monkeypatch.setenv("CYCLE_SECONDS", "100")
    _patch(monkeypatch, clock, build)
    CL.main([])

    assert len(passes) == 2
    assert clock.slept[:1] == [50]
