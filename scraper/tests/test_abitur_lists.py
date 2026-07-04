"""Тесты чтения шардированного индекса списков (lookup/format), без сети.

Запуск: python -m pytest scraper/tests/test_abitur_lists.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import lists as L

META = {
    "updated_at": "2026-07-02T20:00:00+03:00", "campaign": "2026",
    "lists": {"000000672": {"direction": "44.03.01 Педагогическое образование. История",
                            "form": "заочная", "kind": "бюджет",
                            "totals": [290, 250]}},
}
SHARD = {
    "updated_at": "2026-07-02T20:00:00+03:00",
    "codes": {"1281839": [{"list": "000000672", "position": 1, "score_total": 290,
                           "consent": False, "priority_pz": 28, "bvi": False,
                           "status": "На рассмотрении"}]},
}


def test_lookup_found_and_missing():
    assert L.lookup(SHARD, "1281839")
    assert L.lookup(SHARD, "0000") == []
    assert L.lookup(SHARD, " 1281839 ") != []  # нормализация


def test_format_positions_found():
    out = L.format_positions(META, SHARD, "1281839")
    assert "История" in out
    assert "заочная" in out and "бюджет" in out   # форма и вид мест в названии
    assert "290" in out
    assert "2026-07-02" in out
    assert "epk25.mpgu.su" in out


def test_format_positions_not_found():
    out = L.format_positions(META, SHARD, "9999")
    assert "не найден" in out.lower()
    assert "epk25.mpgu.su" in out


def test_format_positions_survives_missing_meta():
    out = L.format_positions(None, SHARD, "1281839")
    assert "000000672" in out  # fallback на код списка
