"""Тесты маркера кампании и стража устаревания. Без сети."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import campaign


def test_not_stale_during_campaign():
    assert campaign.is_stale(dt.date(2026, 7, 20)) is False
    assert campaign.staleness_warning(dt.date(2026, 7, 20)) == ""


def test_stale_next_year():
    assert campaign.is_stale(dt.date(2027, 1, 15)) is True
    w = campaign.staleness_warning(dt.date(2027, 6, 1))
    assert "устарел" in w and campaign.CAMPAIGN in w
