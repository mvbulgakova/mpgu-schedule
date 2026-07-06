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


# Формат 2015–2016: код+название в первой ячейке, столбцы БЮДЖЕТ (несколько «волн»)
# и ДОГОВОР. Проходной берём из ПОСЛЕДНЕГО бюджетного столбца, не из договорного.
FIX_WIDE = """<table>
<tr><td>Код и наименование направления подготовки</td><td>Форма и срок обучения</td>
<td>БЮДЖЕТ</td><td>ДОГОВОР</td></tr>
<tr><td>Конкурс в 2016 г.</td><td>Проходной балл на 3 августа 2016 г.</td>
<td>Проходной балл на 8 августа 2016 г.</td><td>Проходной балл</td></tr>
<tr><td>Географический факультет</td></tr>
<tr><td>05.03.02 География, профиль Общая география</td><td>Очная, 4 года</td>
<td>15.0</td><td>198</td><td>179</td><td>—</td></tr>
<tr><td>44.03.01 Педагогическое образование, профиль География</td><td>Очная, 4 года</td>
<td>12.0</td><td>210</td><td>204</td><td>163</td></tr>
</table>"""


def test_parse_wide_budget_column_2016():
    rows = parse_score_table(FIX_WIDE, year=2016)
    assert len(rows) == 2
    r0 = rows[0]
    assert r0["code"] == "05.03.02"
    assert "Общая география" in r0["program"]
    assert r0["form"] == "очная"
    assert r0["passing"] == 179            # последний бюджетный столбец, не договор (—)
    r1 = rows[1]
    assert r1["code"] == "44.03.01"
    assert r1["passing"] == 204            # 204 (бюджет 8 авг), НЕ 163 (договор)


HUB = """
<a href="/x/konkurs-i-prohodnoj-ball-v-2019-godu/">Конкурс и проходной балл в 2019 году</a>
<a href="/x/konkurs-i-prohodnoj-ball-v-2019-godu-v-filialah-mpgu/">Конкурс и проходной балл в 2019 году в филиалах</a>
<a href="/y/prikazy-o-zachislenii/">Приказы о зачислении</a>
<a href="/z/prohodnoy-ball-v-2016-godu/">Проходной балл в 2016 году</a>
<a href="/w/svedenija-o-zachislenii/">Сведения о зачислении</a>
"""


def test_find_year_pages_picks_main_not_branches():
    pages = find_year_pages(HUB)
    # ловим и «Конкурс и проходной балл» (2019), и «Проходной балл» (2016);
    # филиалы, приказы и «сведения о зачислении» — исключены
    assert pages == {
        2019: "https://mpgu.su/x/konkurs-i-prohodnoj-ball-v-2019-godu/",
        2016: "https://mpgu.su/z/prohodnoy-ball-v-2016-godu/",
    }
