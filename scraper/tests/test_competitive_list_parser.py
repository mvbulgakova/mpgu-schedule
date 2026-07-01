"""Тесты парсера конкурсного списка epk25.

Запуск: python -m pytest scraper/tests/test_competitive_list_parser.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.parsers.competitive_list_parser import parse_view

# Минимальная фикстура структуры epk25 (uppercase-теги, R-классы, пустые ячейки как <SPAN>).
FIXTURE = """
<HTML><BODY>
<TABLE>
<TR CLASS=R16><TD>№</TD><TD>Уникальный код</TD><TD>Наличие согласия на зачисление</TD>
<TD>ПЗ</TD><TD>ОВП</TD><TD>ВПП</TD><TD>Основание приема БВИ</TD>
<TD>Сумма конкурсных баллов</TD><TD>Сумма баллов за ВИ</TD><TD>ВИ 1</TD><TD>ВИ 2</TD><TD>ВИ 3</TD>
<TD>ИД</TD><TD>ПП</TD><TD>Информация о рассмотрении заявления</TD><TD>Причина отказа</TD>
<TD>Высший проходной приоритет</TD></TR>
<TR CLASS=R18><TD>1</TD><TD>1281839</TD><TD>+</TD><TD>28</TD><TD><SPAN></SPAN></TD><TD><SPAN></SPAN></TD>
<TD><SPAN></SPAN></TD><TD>290</TD><TD>290</TD><TD>96</TD><TD>94</TD><TD>100</TD><TD>0</TD>
<TD><SPAN></SPAN></TD><TD>На рассмотрении</TD><TD><SPAN></SPAN></TD><TD><SPAN></SPAN></TD></TR>
<TR CLASS=R19><TD>2</TD><TD>1300500</TD><TD><SPAN></SPAN></TD><TD>1</TD><TD><SPAN></SPAN></TD><TD><SPAN></SPAN></TD>
<TD>Без ВИ</TD><TD>310</TD><TD>300</TD><TD>100</TD><TD>100</TD><TD>100</TD><TD>10</TD>
<TD><SPAN></SPAN></TD><TD>Рекомендован</TD><TD><SPAN></SPAN></TD><TD><SPAN></SPAN></TD></TR>
</TABLE>
</BODY></HTML>
"""


def test_parse_view_returns_rows():
    rows = parse_view(FIXTURE)
    assert len(rows) == 2
    r = rows[0]
    assert r["position"] == 1
    assert r["unique_code"] == "1281839"
    assert r["consent"] is True
    assert r["priority_pz"] == 28
    assert r["score_total"] == 290
    assert r["id_points"] == 0
    assert r["bvi"] is False
    assert r["status"] == "На рассмотрении"


def test_parse_view_second_row_bvi_and_no_consent():
    rows = parse_view(FIXTURE)
    r = rows[1]
    assert r["unique_code"] == "1300500"
    assert r["consent"] is False
    assert r["bvi"] is True
    assert r["score_total"] == 310
    assert r["status"] == "Рекомендован"


def test_parse_view_empty_table():
    assert parse_view("<HTML><BODY><TABLE></TABLE></BODY></HTML>") == []
