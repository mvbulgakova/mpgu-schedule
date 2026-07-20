"""Тесты сборки индекса конкурсных списков (чисто, без сети).

Запуск: python -m pytest scraper/tests/test_build_lists_index.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.build_lists_index import build_index, _guard_incomplete

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


_OK_STATS = {"levels_failed": [], "directions_total": 100, "directions_failed": 0,
             "views_total": 300, "views_failed": 0}


def _md(n):  # meta_doc с n списками
    return {"lists": {str(i): {} for i in range(n)}}


def test_guard_blocks_failed_level():
    stats = dict(_OK_STATS, levels_failed=["basic_higher_education"])
    assert _guard_incomplete(_md(600), stats, _md(600)) is not None


def test_guard_blocks_many_failed_directions():
    stats = dict(_OK_STATS, directions_failed=20)  # 20% > 10%
    assert _guard_incomplete(_md(600), stats, _md(600)) is not None


def test_guard_blocks_big_count_drop_only_with_failures():
    # 378 < 85% от 667 ПРИ сетевых сбоях → отказ
    stats = dict(_OK_STATS, directions_failed=5)  # <10%, но сбои есть
    assert _guard_incomplete(_md(378), stats, _md(667)) is not None


def test_guard_allows_legit_shrink_on_clean_crawl():
    # то же падение 667→378, но обход ЧИСТЫЙ (сбоев нет) → это честное сокращение,
    # публикуем (квотные списки закрылись)
    assert _guard_incomplete(_md(378), _OK_STATS, _md(667)) is None


def test_guard_allows_normal_update():
    # небольшой рост, обход полный → публикуем
    assert _guard_incomplete(_md(670), _OK_STATS, _md(667)) is None


def test_guard_allows_when_no_previous():
    assert _guard_incomplete(_md(600), _OK_STATS, None) is None


# ── Симуляция «реального конкурса» (согласия + высшие приоритеты) ────────────

from scraper.build_lists_index import simulate_admission


def test_simulate_person_occupies_only_highest_priority():
    # A проходит в L1 (приоритет 1) и лидирует в L2 — но займёт только L1;
    # его место в L2 достаётся B.
    cands = {"A": [(1, "L1", 1), (2, "L2", 1)],
             "B": [(1, "L2", 2)]}
    adm = simulate_admission(cands, {"L1": 1, "L2": 1})
    assert adm["L1"] == {"A"} and adm["L2"] == {"B"}


def test_simulate_bumped_person_cascades():
    # C сильнее B в L2: B вытеснен из L2 → уходит в свой приоритет 2 (L1)
    cands = {"B": [(1, "L2", 3), (2, "L1", 5)],
             "C": [(1, "L2", 2)]}
    adm = simulate_admission(cands, {"L1": 1, "L2": 1})
    assert adm["L2"] == {"C"} and adm["L1"] == {"B"}


def test_simulate_capacity_respected():
    cands = {p: [(1, "L", i + 1)] for i, p in enumerate("abcde")}
    adm = simulate_admission(cands, {"L": 3})
    assert adm["L"] == {"a", "b", "c"}


VIEW_SIM = """
<TABLE>
<TR><TD>№</TD><TD>Уникальный код</TD><TD>Наличие согласия на зачисление</TD><TD>ПЗ</TD><TD>ОВП</TD><TD>ВПП</TD>
<TD>Основание приема БВИ</TD><TD>Сумма конкурсных баллов</TD><TD>Сумма баллов за ВИ</TD>
<TD COLSPAN=3>Количество баллов за каждое ВИ</TD><TD>ИД</TD><TD>ПП</TD>
<TD>Информация о рассмотрении заявления</TD><TD>Причина отказа</TD></TR>
<TR><TD>1</TD><TD>111</TD><TD>+</TD><TD>1</TD><TD></TD><TD></TD><TD></TD><TD>290</TD><TD>290</TD>
<TD>96</TD><TD>94</TD><TD>100</TD><TD>0</TD><TD></TD><TD>Участвует</TD><TD></TD></TR>
<TR><TD>2</TD><TD>222</TD><TD></TD><TD>2</TD><TD></TD><TD></TD><TD></TD><TD>250</TD><TD>250</TD>
<TD>80</TD><TD>80</TD><TD>90</TD><TD>0</TD><TD></TD><TD>Участвует</TD><TD></TD></TR>
<TR><TD>3</TD><TD>333</TD><TD>+</TD><TD>1</TD><TD></TD><TD></TD><TD></TD><TD>240</TD><TD>240</TD>
<TD>80</TD><TD>80</TD><TD>80</TD><TD>0</TD><TD></TD><TD>Участвует</TD><TD></TD></TR>
</TABLE>
"""


def test_build_index_sim_fields():
    pages = {"G1": VIEW_SIM}
    meta = {"G1": {"direction": "44.03.01 История", "form": "очная", "kind": "бюджет"}}
    meta_doc, shards = build_index(pages, meta, updated_at="t",
                                   places_fn=lambda m: 1)
    lm = meta_doc["lists"]["G1"]
    assert lm["general"] is True and lm["places"] == 1
    # 111 (согласие, поз.1) зачислен; 222 без согласия: выше него 1 согласившийся-зачисленный
    e222 = shards["22"]["codes"]["222"][0]
    assert e222["cons_above"] == 1
    assert e222["sim_above"] == 1      # место с согласием было бы ~2-е из 1 → не проходит
    e111 = shards["11"]["codes"]["111"][0]
    assert e111["sim_above"] == 0      # он первый
    # 333 (согласие, поз.3): 111 занял единственное место → выше один зачисленный
    e333 = shards["33"]["codes"]["333"][0]
    assert e333["sim_above"] == 1


def test_build_index_code_alias_marks_general(monkeypatch):
    # кампус-дубль (филиал): список меньше московского, но с привязкой по коду
    # — это свой отдельный общий конкурс, а не квотный список
    import scraper.abitur.lists as LM
    monkeypatch.setattr(LM, "alias_list_codes", lambda: {"B"})
    big = VIEW.replace("</TABLE>",
                       "<TR><TD>3</TD><TD>333</TD><TD></TD><TD>1</TD><TD></TD><TD></TD>"
                       "<TD></TD><TD>240</TD><TD>240</TD><TD>80</TD><TD>80</TD><TD>80</TD>"
                       "<TD>0</TD><TD></TD><TD>На рассмотрении</TD><TD></TD></TR></TABLE>")
    meta = {"A": {"direction": "44.04.01 Менеджмент", "form": "очная", "kind": "бюджет"},
            "B": {"direction": "44.04.01 Менеджмент", "form": "очная", "kind": "бюджет"}}
    md, _ = build_index({"A": big, "B": VIEW}, meta, updated_at="t",
                        places_fn=lambda m: 10)
    assert md["lists"]["A"]["general"] is True    # крупнейший — как раньше
    assert md["lists"]["B"]["general"] is True    # принудительно по привязке
    assert md["lists"]["B"]["places"] == 10


def test_build_index_reports_coverage():
    pages = {"G1": VIEW_SIM}
    meta = {"G1": {"direction": "44.03.01 История", "form": "очная", "kind": "бюджет"}}
    # места известны → покрытие 1.0
    md, _ = build_index(pages, meta, updated_at="t", places_fn=lambda m: 30)
    assert md["coverage"]["general_budget_lists"] == 1
    assert md["coverage"]["with_places"] == 1
    assert md["coverage"]["match_rate"] == 1.0
    # места неизвестны → покрытие 0.0 (сигнал сломанного матчинга)
    md2, _ = build_index(pages, meta, updated_at="t", places_fn=lambda m: None)
    assert md2["coverage"]["match_rate"] == 0.0
