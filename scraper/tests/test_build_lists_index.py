"""Тесты сборки индекса конкурсных списков (чисто, без сети).

Запуск: python -m pytest scraper/tests/test_build_lists_index.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.build_lists_index import build_index

VIEW = """
<TABLE>
<TR><TD>№</TD><TD>Уникальный код</TD><TD>Согласие</TD><TD>ПЗ</TD><TD>ОВП</TD><TD>ВПП</TD>
<TD>БВИ</TD><TD>Сумма</TD><TD>ВИсум</TD><TD>ВИ1</TD><TD>ВИ2</TD><TD>ВИ3</TD><TD>ИД</TD><TD>ПП</TD>
<TD>Статус</TD><TD>Отказ</TD></TR>
<TR><TD>1</TD><TD>111</TD><TD>+</TD><TD>1</TD><TD></TD><TD></TD><TD></TD><TD>290</TD><TD>290</TD>
<TD>96</TD><TD>94</TD><TD>100</TD><TD>0</TD><TD></TD><TD>Рекомендован</TD><TD></TD></TR>
<TR><TD>2</TD><TD>222</TD><TD></TD><TD>2</TD><TD></TD><TD></TD><TD></TD><TD>250</TD><TD>250</TD>
<TD>80</TD><TD>80</TD><TD>90</TD><TD>0</TD><TD></TD><TD>На рассмотрении</TD><TD></TD></TR>
</TABLE>
"""


def test_build_index_maps_codes_to_positions():
    pages = {"000000672": VIEW}
    meta = {"000000672": {"direction": "44.03.01 История",
                          "level": "basic_higher_education", "university": "main_university"}}
    idx = build_index(pages, meta, updated_at="2026-07-01T20:00:00+03:00")
    assert idx["updated_at"] == "2026-07-01T20:00:00+03:00"
    assert idx["lists"]["000000672"]["count"] == 2
    assert idx["lists"]["000000672"]["direction"] == "44.03.01 История"
    e = idx["codes"]["111"][0]
    assert e["list"] == "000000672"
    assert e["position"] == 1
    assert e["score_total"] == 290
    assert e["consent"] is True
    assert idx["codes"]["222"][0]["position"] == 2


def test_build_index_code_in_multiple_lists():
    pages = {"A": VIEW, "B": VIEW}
    meta = {"A": {"direction": "d1"}, "B": {"direction": "d2"}}
    idx = build_index(pages, meta, updated_at="t")
    assert len(idx["codes"]["111"]) == 2
    assert {e["list"] for e in idx["codes"]["111"]} == {"A", "B"}
