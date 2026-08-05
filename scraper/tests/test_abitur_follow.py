"""Тесты подписки «следи за моим кодом» (хранение, дифф позиций). Без сети.

Запуск: python -m pytest scraper/tests/test_abitur_follow.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import follow

META = {"updated_at": "2026-07-17T12:00:00+03:00", "lists": {
    "L1": {"direction": "44.03.01 История", "form": "очная", "kind": "бюджет"},
    "L2": {"direction": "44.03.01 История", "form": "очная", "kind": "платное"},
}}


def _e(lst, pos):
    return {"list": lst, "position": pos, "score_total": 250,
            "consent": False, "priority_pz": 1, "bvi": False, "status": "Участвует"}


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "subs.json"
    subs = {"42": {"code": "123", "last": {"L1": 5}, "updated_at": "t"}}
    follow.save(p, subs)
    assert follow.load(p) == subs


def test_load_missing_or_broken_file(tmp_path):
    assert follow.load(tmp_path / "nope.json") == {}
    p = tmp_path / "bad.json"
    p.write_text("{broken", encoding="utf-8")
    assert follow.load(p) == {}


def test_diff_none_when_unchanged():
    old = {"L1": 5, "L2": 7}
    assert follow.diff_text("123", old, [_e("L1", 5), _e("L2", 7)], META) is None


def test_diff_reports_position_change_with_direction():
    old = {"L1": 5}
    txt = follow.diff_text("123", old, [_e("L1", 3)], META)
    assert txt and "5 → " in txt and "3" in txt and "⬆️" in txt
    txt2 = follow.diff_text("123", {"L1": 3}, [_e("L1", 9)], META)
    assert "⬇️" in txt2


def test_diff_reports_new_and_gone_lists():
    txt = follow.diff_text("123", {"L1": 5}, [_e("L1", 5), _e("L2", 2)], META)
    assert txt and "появил" in txt
    txt2 = follow.diff_text("123", {"L1": 5, "L2": 2}, [_e("L1", 5)], META)
    assert txt2 and "больше нет" in txt2


def test_diff_mentions_only_changed_lists():
    old = {"L1": 5, "L2": 7}
    txt = follow.diff_text("123", old, [_e("L1", 4), _e("L2", 7)], META)
    # платное (L2) не изменилось — в тексте только один пункт-изменение
    assert txt.count("•") == 1


def test_positions_of():
    assert follow.positions_of([_e("L1", 5), _e("L2", 7)]) == {"L1": 5, "L2": 7}


def test_diff_shows_when_the_university_updated_the_lists():
    # В уведомлении важно, когда списки пересчитал ВУЗ, а не когда мы сходили
    # проверить: наш обход идёт каждые несколько минут и сам по себе ничего
    # не значит. Без этой строки человек не понимает, к какому моменту относится
    # его новое место.
    meta = {"updated_at": "2026-08-05T12:38:00+03:00", "lists": {
        "L1": {"direction": "44.03.01 История", "form": "очная", "kind": "бюджет",
               "page_updated_at": "2026-08-05T11:34:00+03:00"},
        "L2": {"direction": "44.03.01 История", "form": "очная", "kind": "платное",
               "page_updated_at": "2026-08-05T10:00:00+03:00"}}}
    txt = follow.diff_text("123", {"L1": 5}, [_e("L1", 3)], meta)
    assert "11:34" in txt          # самый свежий пересчёт вузом
    assert "12:38" not in txt      # время нашего обхода в уведомлении не нужно


def test_diff_without_page_updates_has_no_timestamp_line():
    txt = follow.diff_text("123", {"L1": 5}, [_e("L1", 3)], META)
    assert txt is not None and "epk25 обновлены" not in txt
