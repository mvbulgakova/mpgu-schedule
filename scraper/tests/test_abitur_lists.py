"""Тесты чтения индекса конкурсных списков (lookup/format), без сети.

Запуск: python -m pytest scraper/tests/test_abitur_lists.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import lists as L

INDEX = {
    "updated_at": "2026-07-01T20:00:00+03:00", "campaign": "2026",
    "lists": {"000000672": {"direction": "44.03.01 История",
                            "url": "https://epk25.mpgu.su/competitive-list/view?code=000000672"}},
    "codes": {"1281839": [{"list": "000000672", "position": 1, "score_total": 290,
                           "consent": False, "priority_pz": 28, "bvi": False,
                           "status": "На рассмотрении"}]},
}


def test_lookup_found_and_missing():
    assert L.lookup(INDEX, "1281839")
    assert L.lookup(INDEX, "0000") == []
    assert L.lookup(INDEX, " 1281839 ") != []  # нормализация пробелов


def test_format_positions_found():
    out = L.format_positions(INDEX, "1281839")
    assert "44.03.01 История" in out
    assert "290" in out and "1" in out
    assert "2026-07-01" in out  # время обновления
    assert "epk25.mpgu.su" in out  # ссылка на официальный список


def test_format_positions_not_found():
    out = L.format_positions(INDEX, "9999")
    assert "не найден" in out.lower()
    assert "epk25.mpgu.su" in out or "mpgu.su" in out
