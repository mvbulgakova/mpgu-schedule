"""Тесты сборки индекса конкурсных списков (чисто, без сети).

Запуск: python -m pytest scraper/tests/test_build_lists_index.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.build_lists_index import build_index

VIEW = """
<TABLE>
<TR><TD>№</TD><TD>Уникальный код</TD><TD>Наличие согласия на зачисление</TD><TD>ПЗ</TD><TD>ОВП</TD><TD>ВПП</TD>
<TD>Основание приема БВИ</TD><TD>Сумма конкурсных баллов</TD><TD>Сумма баллов за ВИ</TD>
<TD COLSPAN=3>Количество баллов за каждое ВИ</TD><TD>ИД</TD><TD>ПП</TD>
<TD>Информация о рассмотрении заявления</TD><TD>Причина отказа</TD></TR>
<TR><TD>1</TD><TD>111</TD><TD>+</TD><TD>1</TD><TD></TD><TD></TD><TD></TD><TD>290</TD><TD>290</TD>
<TD>96</TD><TD>94</TD><TD>100</TD><TD>0</TD><TD></TD><TD>Рекомендован</TD><TD></TD></TR>
<TR><TD>2</TD><TD>222</TD><TD></TD><TD>2</TD><TD></TD><TD></TD><TD></TD><TD>250</TD><TD>250</TD>
<TD>80</TD><TD>80</TD><TD>90</TD><TD>0</TD><TD></TD><TD>На рассмотрении</TD><TD></TD></TR>
</TABLE>
"""


def test_build_index_maps_codes_to_shards():
    pages = {"000000672": VIEW}
    meta = {"000000672": {"direction": "44.03.01 История", "form": "заочная",
                          "kind": "бюджет", "level": "basic_higher_education"}}
    meta_doc, shards = build_index(pages, meta, updated_at="2026-07-01T20:00:00+03:00")
    assert meta_doc["updated_at"] == "2026-07-01T20:00:00+03:00"
    lm = meta_doc["lists"]["000000672"]
    assert lm["count"] == 2
    assert lm["direction"] == "44.03.01 История"
    assert lm["totals"] == [290, 250]      # для /shansy
    # код 111 → шард "11"
    e = shards["11"]["codes"]["111"][0]
    assert e["list"] == "000000672"
    assert e["position"] == 1
    assert e["score_total"] == 290
    assert e["consent"] is True
    assert shards["22"]["codes"]["222"][0]["position"] == 2
    assert meta_doc["codes_total"] == 2


def test_build_index_code_in_multiple_lists():
    pages = {"A": VIEW, "B": VIEW}
    meta = {"A": {"direction": "d1"}, "B": {"direction": "d2"}}
    meta_doc, shards = build_index(pages, meta, updated_at="t")
    entries = shards["11"]["codes"]["111"]
    assert len(entries) == 2
    assert {e["list"] for e in entries} == {"A", "B"}
