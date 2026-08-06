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


def _snapshot(root: Path, updated_at: str, changed: dict):
    """Снимок обхода: большой JSON, где между обходами меняются ЕДИНИЦЫ строк.

    Это и есть суть гонки. За две минуты у подавляющего большинства
    абитуриентов позиция не двигается, поэтому файлы двух обходов
    различаются в нескольких непересекающихся местах — а git такое сливает
    БЕЗ конфликта, и -X ours/-X theirs до этих кусков просто не доходит.
    """
    (root / "admissions" / "by_code").mkdir(parents=True, exist_ok=True)
    lines = ['{', f'  "updated_at": "{updated_at}",', '  "codes": {']
    for i in range(200):
        lines.append(f'    "{i:07d}": {{"position": {changed.get(i, i)}}},')
    lines += ['    "last": 0', '  }', '}']
    body = "\n".join(lines)
    (root / "admissions" / "lists_meta.json").write_text(body, encoding="utf-8")
    (root / "admissions" / "by_code" / "19.json").write_text(body, encoding="utf-8")


def _publish_race(tmp_path, ours_at, theirs_at):
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "-q", "--bare", "-b", "data", ".")
    seed = tmp_path / "seed"
    _init_repo(seed)
    _snapshot(seed, "2026-08-06T03:00:00+03:00", {})
    _git(seed, "add", "-A"); _git(seed, "commit", "-qm", "seed")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "origin", "data")

    # Чужой обход подвинул человека в начале файла...
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(origin), "other")
    _git(other, "config", "user.email", "t@t"); _git(other, "config", "user.name", "t")
    _snapshot(other, theirs_at, {5: 999})
    _git(other, "commit", "-qam", "чужой обход")
    _git(other, "push", "-q", "origin", "data")

    # ...наш — совсем другого, в конце. Куски не пересекаются.
    mine = tmp_path / "mine"
    _git(tmp_path, "clone", "-q", str(origin), "mine")
    _git(mine, "config", "user.email", "t@t"); _git(mine, "config", "user.name", "t")
    _git(mine, "reset", "-q", "--hard", "HEAD~1")
    _snapshot(mine, ours_at, {150: 777})
    _git(mine, "commit", "-qam", "наш обход")
    ours = (mine / "admissions" / "lists_meta.json").read_text(encoding="utf-8")
    theirs = (other / "admissions" / "lists_meta.json").read_text(encoding="utf-8")

    _retry_push(mine)
    published = subprocess.run(["git", "show", "data:admissions/lists_meta.json"],
                               cwd=origin, capture_output=True, text=True).stdout
    shard = subprocess.run(["git", "show", "data:admissions/by_code/19.json"],
                           cwd=origin, capture_output=True, text=True).stdout
    return published, shard, ours, theirs


def test_published_snapshot_is_never_a_mix_of_two_crawls(tmp_path):
    """Метаданные и шарды обязаны быть из ОДНОГО обхода, целиком.

    Живой инцидент 2026-08-06 (коммит f79827a6): обход 03:14 лёг rebase'ом на
    обход 03:12, git слил JSON построчно — и в ветке оказались метаданные
    одного прогона рядом с шардами другого. У списка 000000320 в метаданных
    608 человек, в шардах 594; у 000000644 наоборот, 585 против 2631.
    Абитуриент 1914288 исчез из шардов целиком, и бот разослал ему «вас
    больше нет в этом списке» по всем 13 спискам сразу.
    """
    published, shard, ours, theirs = _publish_race(
        tmp_path, ours_at="2026-08-06T03:14:00+03:00",
        theirs_at="2026-08-06T03:12:00+03:00")
    assert published == ours, "в ветку уехала склейка двух обходов"
    assert shard == ours, "шард разъехался с метаданными"
    assert '"position": 999' not in published, "чужая правка въехала молча"


def test_stale_crawl_does_not_overwrite_a_fresher_one(tmp_path):
    """Свой снимок публикуем, только если он новее лежащего в ветке."""
    published, shard, ours, theirs = _publish_race(
        tmp_path, ours_at="2026-08-06T03:12:00+03:00",
        theirs_at="2026-08-06T03:14:00+03:00")
    assert published == theirs and shard == theirs
