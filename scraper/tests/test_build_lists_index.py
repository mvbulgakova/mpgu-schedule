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


def _md(n, codes=10000):  # meta_doc с n списками; codes_total фиксирован,
    # если явно не задан — не завязан на n, иначе старые тесты про число
    # списков нечаянно попадали бы под новую проверку кодов.
    return {"lists": {str(i): {} for i in range(n)}, "codes_total": codes}


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


def test_guard_blocks_codes_collapse_even_without_network_errors():
    # Живой инцидент 29.07: epk25 под нагрузкой отдал HTTP 200 с валидной, но
    # УРЕЗАННОЙ таблицей на почти каждый список. Число списков не изменилось
    # (667), сетевых ошибок не было (_OK_STATS) — но codes_total рухнул
    # 27470→2097, и абитуриенты реально пропали из индекса, хотя оставались
    # в списках на epk25/Госуслугах. Это блокируется НЕЗАВИСИМО от stats.
    prev = _md(667, codes=27470)
    corrupted = _md(667, codes=2097)
    reason = _guard_incomplete(corrupted, _OK_STATS, prev)
    assert reason is not None
    assert "2097" in reason and "27470" in reason


def test_guard_allows_recovery_after_incident():
    # как только сайт отдал полные страницы снова — публикуем без вмешательства
    prev = _md(667, codes=27470)
    recovered = _md(667, codes=27490)
    assert _guard_incomplete(recovered, _OK_STATS, prev) is None


def test_guard_allows_stable_codes_despite_fewer_lists():
    # честное закрытие квотных списков: списков стало меньше, но затронутые
    # абитуриенты остаются в других своих списках — codes_total не рушится
    prev = _md(667, codes=27000)
    shrunk = _md(600, codes=26800)
    assert _guard_incomplete(shrunk, _OK_STATS, prev) is None


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
    # без отметок ВПП на странице — vpp у всех False, vpp_above всех 0
    assert e111["vpp"] is False and e111["vpp_above"] == 0
    assert e222["vpp_above"] == 0


VIEW_VPP = """
<TABLE>
<TR><TD>№</TD><TD>Уникальный код</TD><TD>Наличие согласия на зачисление</TD><TD>ПЗ</TD><TD>ОВП</TD><TD>ВПП</TD>
<TD>Основание приема БВИ</TD><TD>Сумма конкурсных баллов</TD><TD>Сумма баллов за ВИ</TD>
<TD COLSPAN=3>Количество баллов за каждое ВИ</TD><TD>ИД</TD><TD>ПП</TD>
<TD>Информация о рассмотрении заявления</TD><TD>Причина отказа</TD></TR>
<TR><TD>1</TD><TD>111</TD><TD>+</TD><TD>1</TD><TD></TD><TD>&#10003;</TD><TD></TD><TD>290</TD><TD>290</TD>
<TD>96</TD><TD>94</TD><TD>100</TD><TD>0</TD><TD></TD><TD>Участвует</TD><TD></TD></TR>
<TR><TD>2</TD><TD>222</TD><TD>+</TD><TD>2</TD><TD></TD><TD></TD><TD></TD><TD>250</TD><TD>250</TD>
<TD>80</TD><TD>80</TD><TD>90</TD><TD>0</TD><TD></TD><TD>Участвует</TD><TD></TD></TR>
<TR><TD>3</TD><TD>333</TD><TD>+</TD><TD>1</TD><TD></TD><TD>&#10003;</TD><TD></TD><TD>240</TD><TD>240</TD>
<TD>80</TD><TD>80</TD><TD>80</TD><TD>0</TD><TD></TD><TD>Участвует</TD><TD></TD></TR>
</TABLE>
"""


def test_build_index_vpp_above_counts_official_marks_ahead():
    # Регрессия 2026-08-04: vpp_above — официальная альтернатива sim_above,
    # накопительный счётчик реальных отметок ВПП epk25 выше по позиции.
    pages = {"G1": VIEW_VPP}
    meta = {"G1": {"direction": "44.03.01 История", "form": "очная", "kind": "бюджет"}}
    meta_doc, shards = build_index(pages, meta, updated_at="t",
                                   places_fn=lambda m: 1)
    e111 = shards["11"]["codes"]["111"][0]
    assert e111["vpp"] is True and e111["vpp_above"] == 0    # первый с ВПП
    e222 = shards["22"]["codes"]["222"][0]
    assert e222["vpp"] is False and e222["vpp_above"] == 1   # 111 уже был выше
    e333 = shards["33"]["codes"]["333"][0]
    assert e333["vpp"] is True and e333["vpp_above"] == 1    # 111 выше, 222 без ВПП не считается


def test_build_index_excludes_codes_already_enrolled_by_order():
    # Регрессия 2026-08-05: код, зачисленный официальным приказом (квота/БВИ)
    # не в общем конкурсе, остаётся в конкурсном списке epk25 с consent=true
    # — без исключения симуляция считает его живым конкурентом общего
    # конкурса и занижает шансы того, кто реально идёт следующим (см. код
    # 1319710: зачислен по квоте 03.08, но без этого исключения "отъедал"
    # бы место у кандидата на позиции 551 в списке 000000602).
    pages = {"G1": VIEW_SIM}
    meta = {"G1": {"direction": "44.03.01 История", "form": "очная", "kind": "бюджет"}}
    meta_doc, shards = build_index(pages, meta, updated_at="t",
                                   places_fn=lambda m: 1,
                                   enrolled_elsewhere={"111"})
    # без исключения (test_build_index_sim_fields) единственное место в
    # симуляции занимал 111, а 333 не проходил (sim_above == 1). Раз 111
    # уже зачислен приказом не сюда — место освобождается для 333.
    e333 = shards["33"]["codes"]["333"][0]
    assert e333["sim_above"] == 0


# 4 строки, все с согласием — 4-я служит индикатором: её sim_above равен
# числу зачисленных выше, т.е. напрямую показывает, сколько мест раздала
# симуляция.
VIEW_SEATS = """
<TABLE>
<TR><TD>№</TD><TD>Уникальный код</TD><TD>Наличие согласия на зачисление</TD><TD>ПЗ</TD><TD>ОВП</TD><TD>ВПП</TD>
<TD>Основание приема БВИ</TD><TD>Сумма конкурсных баллов</TD><TD>Сумма баллов за ВИ</TD>
<TD COLSPAN=3>Количество баллов за каждое ВИ</TD><TD>ИД</TD><TD>ПП</TD>
<TD>Информация о рассмотрении заявления</TD><TD>Причина отказа</TD></TR>
<TR><TD>1</TD><TD>111</TD><TD>+</TD><TD>1</TD><TD></TD><TD></TD><TD></TD><TD>290</TD><TD>290</TD>
<TD>96</TD><TD>94</TD><TD>100</TD><TD>0</TD><TD></TD><TD>Участвует</TD><TD></TD></TR>
<TR><TD>2</TD><TD>222</TD><TD>+</TD><TD>1</TD><TD></TD><TD></TD><TD></TD><TD>280</TD><TD>280</TD>
<TD>96</TD><TD>94</TD><TD>90</TD><TD>0</TD><TD></TD><TD>Участвует</TD><TD></TD></TR>
<TR><TD>3</TD><TD>333</TD><TD>+</TD><TD>1</TD><TD></TD><TD></TD><TD></TD><TD>270</TD><TD>270</TD>
<TD>90</TD><TD>90</TD><TD>90</TD><TD>0</TD><TD></TD><TD>Участвует</TD><TD></TD></TR>
<TR><TD>4</TD><TD>444</TD><TD>+</TD><TD>1</TD><TD></TD><TD></TD><TD></TD><TD>260</TD><TD>260</TD>
<TD>90</TD><TD>90</TD><TD>80</TD><TD>0</TD><TD></TD><TD>Участвует</TD><TD></TD></TR>
</TABLE>
"""


def test_sim_capacity_uses_seats_open_not_full_kcp():
    # Регрессия 2026-08-05: симуляция раздавала полный КЦП, хотя часть мест
    # уже занята зачисленными приказом. «Мест для зачисления» (seats_open) —
    # это КЦП минус зачисленные, т.е. сколько реально разыгрывается сейчас.
    # На живых данных: число отметок ВПП совпадает с seats_open на 97
    # бакалаврских списках из 99, а с полным КЦП — только на 70.
    page = VIEW_SEATS + "\nКонтрольные цифры приема: 3\nМест для зачисления: 2\nЗачислено: 1\n"
    meta = {"G1": {"direction": "44.03.01 История", "form": "очная", "kind": "бюджет"}}
    meta_doc, shards = build_index({"G1": page}, meta, updated_at="t",
                                   places_fn=lambda m: 3)
    lm = meta_doc["lists"]["G1"]
    assert lm["places"] == 3 and lm["seats_open"] == 2 and lm["enrolled"] == 1
    # разыгрывается 2 места, а не 3 → выше 4-й строки зачислены только двое
    assert shards["44"]["codes"]["444"][0]["sim_above"] == 2


def test_sim_capacity_falls_back_to_places_without_seats_open():
    # Магистратура: epk25 не публикует «Мест для зачисления» — остаёмся на КЦП.
    meta = {"G1": {"direction": "44.03.01 История", "form": "очная", "kind": "бюджет"}}
    meta_doc, shards = build_index({"G1": VIEW_SEATS}, meta, updated_at="t",
                                   places_fn=lambda m: 3)
    assert meta_doc["lists"]["G1"].get("seats_open") is None
    # без seats_open раздаём полный КЦП=3 → выше 4-й строки зачислены трое
    assert shards["44"]["codes"]["444"][0]["sim_above"] == 3


def test_build_index_prediction_signals(monkeypatch):
    # sim_cutoff = мин балл зачисленного в симуляции; cap = G-й сверху балл
    import scraper.abitur.lists as LM
    monkeypatch.setattr(LM, "_quota_for", lambda m: None)
    pages = {"G1": VIEW_SIM}                       # баллы 290,250,240; согласны 111,333
    meta = {"G1": {"direction": "44.03.01 История", "form": "очная", "kind": "бюджет"}}
    md, _ = build_index(pages, meta, updated_at="t", places_fn=lambda m: 2)
    lm = md["lists"]["G1"]
    assert lm["general_seats"] == 2               # квот нет → все места общие
    assert lm["cap"] == 250                        # 2-й сверху балл из [290,250,240]
    # зачислены (согласившиеся) 111(290) и 333(240) на 2 места → нижний = 240
    assert lm["sim_cutoff"] == 240


def test_build_index_prediction_seats_subtract_quota(monkeypatch):
    import scraper.abitur.lists as LM
    monkeypatch.setattr(LM, "_quota_for", lambda m: 1)   # 1 квотное место
    pages = {"G1": VIEW_SIM}
    meta = {"G1": {"direction": "44.03.01 История", "form": "очная", "kind": "бюджет"}}
    md, _ = build_index(pages, meta, updated_at="t", places_fn=lambda m: 3)
    lm = md["lists"]["G1"]
    assert lm["general_seats"] == 2               # 3 КЦП − 1 квота
    assert lm["cap"] == 250                        # 2-й сверху балл


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


def test_build_index_uses_epk_kcp_as_seats(monkeypatch):
    # КЦП со страницы epk25 («Контрольные цифры приёма: 62») важнее каталога (85)
    # и НЕ вычитает квоты (в т.ч. целевую) — epk уже даёт общий конкурс.
    import scraper.abitur.lists as LM
    monkeypatch.setattr(LM, "_quota_for", lambda m: 18)   # была бы 62−18=44 — не должно
    view = VIEW_SIM.replace("<TABLE>",
        "Вид мест: основные места в рамках КЦП Контрольные цифры приёма: 62 "
        "Мест для зачисления: 62 <TABLE>")
    meta = {"G1": {"direction": "44.03.01 Информатика", "form": "очная", "kind": "бюджет"}}
    md, _ = build_index({"G1": view}, meta, updated_at="t", places_fn=lambda m: 85)
    lm = md["lists"]["G1"]
    assert lm["kcp_epk"] == 62
    assert lm["places"] == 62 and lm.get("kcp_from_epk") is True
    assert lm["general_seats"] == 62          # без вычета квот — epk уже общий конкурс


def test_build_index_falls_back_to_catalog_without_epk_kcp():
    meta = {"G1": {"direction": "44.03.01 X", "form": "очная", "kind": "бюджет"}}
    md, _ = build_index({"G1": VIEW_SIM}, meta, updated_at="t", places_fn=lambda m: 30)
    lm = md["lists"]["G1"]
    assert lm["places"] == 30 and "kcp_from_epk" not in lm


def _view_with(vid, kcp=""):
    return VIEW_SIM.replace("<TABLE>",
        f"Вид мест: {vid} Контрольные цифры приёма: {kcp} <TABLE>")


def test_catalog_fallback_subtracts_all_quotas_incl_target():
    # Реальный кейс: КЦП каталога 85, квоты особая 9 + отдельная 9 + целевая 5
    # = 23 → общий конкурс 62 (как на epk25). Раньше целевую не вычитали (67).
    pages = {"G": _view_with("основные места в рамках КЦП"),          # КЦП пуст
             "Q1": _view_with("особая квота", "9"),
             "Q2": _view_with("отдельная квота", "9"),
             "Q3": _view_with("целевая детализированная квота", "5")}
    base = {"direction": "44.03.01 Информатика", "form": "очная", "kind": "платное"}
    meta = {k: dict(base) for k in pages}
    md, _ = build_index(pages, meta, updated_at="t", places_fn=lambda m: 85)
    g = md["lists"]["G"]
    assert g["quota_seats"] == 23
    assert g["places"] == 62                    # 85 − 23, а не 85 − 18
    assert g["general_seats"] == 62


def test_partial_quota_data_does_not_produce_false_zero():
    # Реальный кейс (Анапский филиал): каталог даёт полный КЦП 15, известна
    # только отдельная квота 15 (особая квота на странице не заполнена вузом,
    # kcp_epk=None) — 15−15=0 выглядело бы как «мест нет», хотя на самом деле
    # мы просто не знаем размер особой квоты. При НЕПОЛНЫХ квотных данных
    # группы вычитание не делаем вовсе — берём полный каталожный КЦП.
    pages = {"G": _view_with("основные места в рамках КЦП"),           # КЦП пуст
             "Q1": _view_with("отдельная квота", "15"),
             "Q2": _view_with("особая квота", "")}                     # не заполнено
    base = {"direction": "44.03.01 Физическая культура", "form": "очно-заочная",
            "kind": "платное"}
    meta = {k: dict(base) for k in pages}
    md, _ = build_index(pages, meta, updated_at="t", places_fn=lambda m: 15)
    g = md["lists"]["G"]
    assert "quota_seats" not in g               # неполные данные — не считаем
    assert g["places"] == 15                    # полный каталожный КЦП, не 0


def test_quota_lists_are_budget_not_paid():
    # квотные списки приезжают с карточки как «платное» — «Вид мест» это чинит,
    # иначе льготник видит свою квотную позицию помеченной платной
    pages = {"Q": _view_with("особая квота", "9")}
    meta = {"Q": {"direction": "44.03.01 X", "form": "очная", "kind": "платное"}}
    md, _ = build_index(pages, meta, updated_at="t", places_fn=lambda m: 85)
    q = md["lists"]["Q"]
    assert q["kind"] == "бюджет" and q["quota"] is True
    assert q["general"] is False               # но не общий конкурс
    assert q["kcp_epk"] == 9


def test_build_index_parses_seats_open_enrolled_and_updated_at():
    # Реальный формат страницы epk25 (проверено вручную 03.08.26):
    # "Контрольные цифры приёма: 33 Зачислено: 3 Мест для зачисления: 30
    #  &nbsp; Дата и время обновления: 03.08.2026. 18:00 &nbsp; ..."
    view = VIEW_SIM.replace("<TABLE>",
        "Вид мест: основные места в рамках КЦП Контрольные цифры приёма: 33 "
        "Зачислено: 3 Мест для зачисления: 30 &nbsp; "
        "Дата и время обновления: 03.08.2026. 18:00 &nbsp; <TABLE>")
    meta = {"G": {"direction": "44.03.01 Тест", "form": "очная", "kind": "бюджет"}}
    md, _ = build_index({"G": view}, meta, updated_at="t", places_fn=lambda m: 33)
    g = md["lists"]["G"]
    assert g["seats_open"] == 30
    assert g["enrolled"] == 3
    assert g["page_updated_at"] == "2026-08-03T18:00:00+03:00"


def test_build_index_missing_new_fields_are_absent():
    meta = {"G": {"direction": "44.03.01 Тест", "form": "очная", "kind": "бюджет"}}
    md, _ = build_index({"G": VIEW_SIM}, meta, updated_at="t", places_fn=lambda m: 10)
    g = md["lists"]["G"]
    assert "seats_open" not in g
    assert "enrolled" not in g
    assert "page_updated_at" not in g


def test_build_index_ignores_invalid_placeholder_date():
    # epk25 иногда отдаёт незаполненную дату-плейсхолдер (00.00.0000. 00:00)
    # до того, как список реально обновился — это должно деградировать в
    # отсутствие page_updated_at, а не ронять build_index на всей выгрузке.
    view = VIEW_SIM.replace("<TABLE>",
        "Вид мест: основные места в рамках КЦП "
        "Дата и время обновления: 00.00.0000. 00:00 <TABLE>")
    meta = {"G": {"direction": "44.03.01 Тест", "form": "очная", "kind": "бюджет"}}
    md, _ = build_index({"G": view}, meta, updated_at="t", places_fn=lambda m: 10)
    g = md["lists"]["G"]
    assert "page_updated_at" not in g
