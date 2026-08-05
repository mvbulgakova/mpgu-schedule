"""Публикация в data при гонке двух прогонов. Локальный git, без сети.

Запуск: python -m pytest scraper/tests/test_git_storage_push.py -v
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.storage.git_storage import _retry_push


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, text=True)


def _init_repo(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "data", ".")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")


def test_concurrent_publish_keeps_the_fresher_crawl(tmp_path):
    """Наш прогон догоняет чужой — победить должны НАШИ файлы.

    Живой инцидент 2026-08-05: ручной прогон и воркфлоу опубликовались
    одновременно, push словил non-fast-forward, и разрешение конфликта
    оставило В ВЕТКЕ чужой lists_meta.json рядом с нашими шардами — 662
    списка против 28313 кодов. Причина: при rebase «ours» — это ветка, НА
    которую перекладывают, то есть чужой прогон; флаг делал ровно обратное
    тому, что написано в комментарии рядом с ним.
    """
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "-q", "--bare", "-b", "data", ".")

    seed = tmp_path / "seed"
    _init_repo(seed)
    (seed / "admissions").mkdir()
    (seed / "admissions" / "lists_meta.json").write_text("базовое", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "seed")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "origin", "data")

    # Чужой прогон успел опубликоваться первым
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(origin), "other")
    _git(other, "config", "user.email", "t@t")
    _git(other, "config", "user.name", "t")
    (other / "admissions" / "lists_meta.json").write_text("ЧУЖОЙ", encoding="utf-8")
    _git(other, "commit", "-qam", "чужой прогон")
    _git(other, "push", "-q", "origin", "data")

    # Наш обход стартовал раньше, но публикуется вторым
    mine = tmp_path / "mine"
    _git(tmp_path, "clone", "-q", str(origin) + "", "mine")
    _git(mine, "config", "user.email", "t@t")
    _git(mine, "config", "user.name", "t")
    _git(mine, "fetch", "-q", "origin")
    _git(mine, "reset", "-q", "--hard", "HEAD~1")     # мы ещё не видели чужой коммит
    (mine / "admissions" / "lists_meta.json").write_text("НАШ", encoding="utf-8")
    _git(mine, "commit", "-qam", "наш обход")

    _retry_push(mine)

    published = subprocess.run(
        ["git", "show", "data:admissions/lists_meta.json"],
        cwd=origin, capture_output=True, text=True).stdout
    assert published == "НАШ", (
        f"в ветке остались чужие данные: {published!r}")
