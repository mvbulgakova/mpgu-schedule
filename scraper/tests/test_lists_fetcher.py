"""Тесты извлечения ссылок из страниц epk25 (чистые функции, без сети).

Запуск: python -m pytest scraper/tests/test_lists_fetcher.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.fetchers import lists_fetcher as LF

STRUCTURAL = """
<a href="/competitive-list/index">Competitive lists</a>
<a href="/competitive-list/direction?educationLevel=basic_higher_education&amp;university=main_university&amp;structuralUnit=1">Институт истории</a>
<a href="/competitive-list/direction?educationLevel=basic_higher_education&amp;university=anapa_branch">Анапский филиал</a>
"""

DIRECTION = """
<a href="/competitive-list/view?code=000000672">44.03.01 История</a>
<a href="/competitive-list/view?code=000000673">46.03.01 История</a>
<a href="/competitive-list/index">назад</a>
"""


def test_extract_direction_links():
    links = LF.extract_direction_links(STRUCTURAL)
    assert len(links) == 2
    assert all("competitive-list/direction" in u for u in links)
    assert all(u.startswith("https://epk25.mpgu.su") for u in links)


def test_extract_view_codes():
    codes = LF.extract_view_codes(DIRECTION)
    assert codes == ["000000672", "000000673"]


def test_structural_url_for_level():
    u = LF.structural_url("basic_higher_education")
    assert u == ("https://epk25.mpgu.su/competitive-list/structural"
                 "?educationLevel=basic_higher_education")


def test_extract_view_links_with_titles():
    links = LF.extract_view_links(DIRECTION)
    assert links == [("000000672", "44.03.01 История"),
                     ("000000673", "46.03.01 История")]
