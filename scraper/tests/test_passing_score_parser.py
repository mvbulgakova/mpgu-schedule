"""Тесты парсера архивных таблиц проходных и поиска страниц по хабам.

Запуск: python -m pytest scraper/tests/test_passing_score_parser.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.fetchers.history_fetcher import find_year_pages
from scraper.parsers.passing_score_parser import parse_score_table

FIX = """<table>
<tr><td>Направление подготовки</td><td>Образовательные программы, форма</td>
<td>Конкурс в 2019</td><td>Проходной балл 2019 года</td></tr>
<tr><td>Географический факультет</td></tr>
<tr><td>05.03.02\nГеография</td><td>Общая география\nОчная, 4 года</td><td>17.2</td><td>205</td></tr>
<tr><td>44.03.01\nПедагогическое образование</td><td>География\nОчная, 4 года</td><td>12.6</td><td>220</td></tr>
</table>"""


def test_parse_year_table():
    rows = parse_score_table(FIX, year=2019)
    assert len(rows) == 2
    r = rows[0]
    assert r["year"] == 2019 and r["code"] == "05.03.02"
    assert r["program"] == "Общая география"
    assert r["form"] == "очная"
    assert r["passing"] == 205
    assert r["competition"] == 17.2


def test_parse_skips_faculty_and_header_rows():
    rows = parse_score_table(FIX, year=2019)
    assert all(r["passing"] for r in rows)


HUB = """
<a href="/x/konkurs-i-prohodnoj-ball-v-2019-godu/">Конкурс и проходной балл в 2019 году</a>
<a href="/x/konkurs-i-prohodnoj-ball-v-2019-godu-v-filialah-mpgu/">Конкурс и проходной балл в 2019 году в филиалах</a>
<a href="/y/prikazy-o-zachislenii/">Приказы о зачислении</a>
"""


def test_find_year_pages_picks_main_not_branches():
    pages = find_year_pages(HUB)
    assert pages == {2019: "https://mpgu.su/x/konkurs-i-prohodnoj-ball-v-2019-godu/"}
