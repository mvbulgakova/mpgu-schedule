"""Тесты парсера конкурсного списка epk25 (маппинг колонок по заголовкам).

Запуск: python -m pytest scraper/tests/test_competitive_list_parser.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.parsers.competitive_list_parser import parse_view

# Бюджетный список: колонка «Наличие согласия…». «Количество баллов за каждое ВИ» — colspan=3.
BUDGET = """
<HTML><BODY><TABLE>
<TR CLASS=R16><TD>№</TD><TD>Уникальный код</TD><TD>Наличие согласия на зачисление</TD>
<TD>ПЗ</TD><TD>ОВП</TD><TD>ВПП</TD><TD>Основание приема БВИ</TD>
<TD>Сумма конкурсных баллов</TD><TD>Сумма баллов за ВИ</TD>
<TD COLSPAN=3>Количество баллов за каждое ВИ</TD>
<TD>ИД</TD><TD>ПП</TD><TD>Информация о рассмотрении заявления</TD><TD>Причина отказа</TD>
<TD>Высший проходной приоритет</TD></TR>
<TR CLASS=R18><TD>1</TD><TD>1281839</TD><TD>+</TD><TD>28</TD><TD><SPAN></SPAN></TD><TD><SPAN></SPAN></TD>
<TD><SPAN></SPAN></TD><TD>290</TD><TD>290</TD><TD>96</TD><TD>94</TD><TD>100</TD><TD>0</TD>
<TD><SPAN></SPAN></TD><TD>На рассмотрении</TD><TD><SPAN></SPAN></TD><TD><SPAN></SPAN></TD></TR>
<TR CLASS=R19><TD>2</TD><TD>1300500</TD><TD><SPAN></SPAN></TD><TD>1</TD><TD><SPAN></SPAN></TD><TD><SPAN></SPAN></TD>
<TD>Есть</TD><TD>310</TD><TD>300</TD><TD>100</TD><TD>100</TD><TD>100</TD><TD>10</TD>
<TD><SPAN></SPAN></TD><TD>Рекомендован</TD><TD><SPAN></SPAN></TD><TD><SPAN></SPAN></TD></TR>
</TABLE></BODY></HTML>
"""

# Платный список: вместо «согласия» две колонки «Заключен договор» + «Оплачено» (сдвиг на 1).
PAID = """
<HTML><BODY><TABLE>
<TR CLASS=R14><TD>№</TD><TD>Уникальный код</TD><TD>Заключен договор об образовании</TD><TD>Оплачено</TD>
<TD>ПЗ</TD><TD>ОВП</TD><TD>ВПП</TD><TD>Основание приема БВИ</TD>
<TD>Сумма конкурсных баллов</TD><TD>Сумма баллов за ВИ</TD>
<TD COLSPAN=3>Количество баллов за каждое ВИ</TD>
<TD>ИД</TD><TD>ПП</TD><TD>Информация о рассмотрении заявления о приеме</TD></TR>
<TR CLASS=R16><TD>1</TD><TD>1288886</TD><TD><SPAN></SPAN></TD><TD><SPAN></SPAN></TD><TD>1</TD><TD>&#10003;</TD>
<TD><SPAN></SPAN></TD><TD><SPAN></SPAN></TD><TD>205</TD><TD>205</TD><TD>64</TD><TD>63</TD><TD>78</TD><TD>0</TD>
<TD><SPAN></SPAN></TD><TD>Участвует в конкурсе</TD></TR>
</TABLE></BODY></HTML>
"""


def test_budget_layout():
    rows = parse_view(BUDGET)
    assert len(rows) == 2
    r = rows[0]
    assert r["position"] == 1
    assert r["unique_code"] == "1281839"
    assert r["consent"] is True
    assert r["priority_pz"] == 28
    assert r["score_total"] == 290
    assert r["id_points"] == 0
    assert r["status"] == "На рассмотрении"
    assert r["ovp"] is False
    assert r["vpp"] is False
    assert rows[1]["consent"] is False
    assert rows[1]["score_total"] == 310


def test_paid_layout_column_shift():
    # у платного списка колонки сдвинуты — маппинг по заголовкам обязан взять верные баллы
    rows = parse_view(PAID)
    assert len(rows) == 1
    r = rows[0]
    assert r["unique_code"] == "1288886"
    assert r["priority_pz"] == 1
    assert r["score_total"] == 205       # не None и не из соседней колонки
    assert r["score_vi"] == 205
    assert r["id_points"] == 0
    assert r["status"] == "Участвует в конкурсе"
    assert r["consent"] is False         # в платном нет колонки согласия
    # Регрессия: ОВП/ВПП — отметка «✓», не число. _int("✓") молча даёт None
    # вместо True — раньше это никак не проверялось.
    assert r["ovp"] is True
    assert r["vpp"] is False


def test_empty_table():
    assert parse_view("<HTML><BODY><TABLE></TABLE></BODY></HTML>") == []
