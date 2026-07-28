"""Тесты чтения шардированного индекса списков (lookup/format), без сети.

Запуск: python -m pytest scraper/tests/test_abitur_lists.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import lists as L

META = {
    "updated_at": "2026-07-02T20:00:00+03:00", "campaign": "2026",
    "lists": {"000000672": {"direction": "44.03.01 Педагогическое образование. История",
                            "form": "заочная", "kind": "бюджет", "count": 40,
                            "totals": [290, 250]}},
}
SHARD = {
    "updated_at": "2026-07-02T20:00:00+03:00",
    "codes": {"1281839": [{"list": "000000672", "position": 1, "score_total": 290,
                           "consent": False, "priority_pz": 28, "bvi": False,
                           "status": "На рассмотрении"}]},
}


def test_lookup_found_and_missing():
    assert L.lookup(SHARD, "1281839")
    assert L.lookup(SHARD, "0000") == []
    assert L.lookup(SHARD, " 1281839 ") != []  # нормализация


def test_format_positions_found():
    out = L.format_positions(META, SHARD, "1281839")
    assert "История" in out
    assert "заочная" in out and "бюджет" in out   # форма и вид мест в названии
    assert "290" in out
    assert "2026-07-02" in out
    assert "epk25.mpgu.su" in out


def test_format_positions_not_found():
    out = L.format_positions(META, SHARD, "9999")
    assert "не найден" in out.lower()
    assert "epk25.mpgu.su" in out


def test_format_positions_survives_missing_meta():
    out = L.format_positions(None, SHARD, "1281839")
    assert "000000672" in out  # fallback на код списка


def test_consent_warning_when_no_consent_on_budget():
    # в бюджетном списке согласие не отмечено → предупреждаем про 5 августа
    out = L.format_positions(META, SHARD, "1281839")
    assert "согласие" in out.lower()
    assert "5 августа" in out


def test_no_consent_warning_when_consent_given():
    shard = {"updated_at": "t", "codes": {"111": [
        {"list": "000000672", "position": 1, "score_total": 290,
         "consent": True, "priority_pz": 1, "bvi": False, "status": "Участвует"}]}}
    out = L.format_positions(META, shard, "111")
    assert "не отмечено" not in out


def test_no_consent_warning_for_paid_only():
    meta = {"updated_at": "t", "lists": {"P1": {"direction": "44.03.01 X",
                                                "form": "очная", "kind": "платное"}}}
    shard = {"updated_at": "t", "codes": {"222": [
        {"list": "P1", "position": 3, "score_total": 200,
         "consent": False, "priority_pz": 1, "bvi": False, "status": "Участвует"}]}}
    out = L.format_positions(meta, shard, "222")
    # для чисто платных позиций напоминание про согласие-до-5-августа не показываем
    assert "не отмечено" not in out


# ── «Прохожу ли сейчас»: место из N, бюджетные места, вывод по приоритетам ───

META2 = {
    "updated_at": "t", "campaign": "2026",
    "lists": {
        "L1": {"direction": "44.03.01 История", "form": "очная",
               "kind": "бюджет", "count": 300},
        "L2": {"direction": "44.03.01 География", "form": "очная",
               "kind": "бюджет", "count": 200},
        "P1": {"direction": "44.03.01 История", "form": "очная",
               "kind": "платное", "count": 50},
    },
}
SHARD2 = {"updated_at": "t", "codes": {"555": [
    {"list": "L1", "position": 45, "score_total": 250, "consent": True,
     "priority_pz": 1, "bvi": False, "status": "Участвует в конкурсе"},
    {"list": "L2", "position": 12, "score_total": 250, "consent": True,
     "priority_pz": 2, "bvi": False, "status": "Участвует в конкурсе"},
    {"list": "P1", "position": 3, "score_total": 250, "consent": True,
     "priority_pz": 3, "bvi": False, "status": "Участвует в конкурсе"},
]}}


def _fake_places(monkeypatch, quota=None):
    import scraper.abitur.lists as LM
    LM._PLACES_CACHE.clear(); LM._QUOTA_CACHE.clear()
    monkeypatch.setattr(LM, "_places_for",
                        lambda m: {"44.03.01 История": 30,
                                   "44.03.01 География": 25}.get(m.get("direction")))
    monkeypatch.setattr(LM, "_quota_for", lambda m: quota)


def test_positions_show_out_of_and_places(monkeypatch):
    _fake_places(monkeypatch)
    out = L.format_positions(META2, SHARD2, "555")
    assert "45 из 300" in out          # место из всех подавших
    assert "мест: 30" in out           # бюджетные места программы
    assert "12 из 200" in out and "мест: 25" in out


def test_passing_marks_and_priority_summary(monkeypatch):
    _fake_places(monkeypatch)
    out = L.format_positions(META2, SHARD2, "555")
    # L1: 45 > 30 мест → за чертой; L2: 12 ≤ 25 → проходит
    assert "⏳" in out and "✅" in out
    # итог по приоритетам: проходит на География (приоритет 2)
    assert "прошли на" in out and "География" in out
    # честная оговорка про долю согласий и дедлайн
    assert "предварительно" in out.lower() and "5 августа" in out
    assert "приоритетного этапа" in out


def test_general_seats_subtract_quota(monkeypatch):
    # КЦП 25, квота 6 → в общем конкурсе 19 (как на Госуслугах), не 25
    _fake_places(monkeypatch, quota=6)
    meta = {"updated_at": "t", "lists": {"L": {
        "direction": "44.03.01 География", "form": "очная", "kind": "бюджет",
        "count": 300, "consented": 40, "general": True, "places": 25}}}
    shard = {"updated_at": "t", "codes": {"555": [
        {"list": "L", "position": 90, "score_total": 250, "consent": True,
         "priority_pz": 1, "bvi": False, "status": "Участвует",
         "cons_above": 30, "sim_above": 11}]}}
    out = L.format_positions(meta, shard, "555")
    assert "~12-е из 19" in out          # 25 − 6 квотных = 19
    assert "КЦП 25" in out               # полное число тоже упомянуто
    # оговорка показывает долю согласий
    assert "40 из 300" in out


def test_summary_when_passing_nowhere(monkeypatch):
    _fake_places(monkeypatch)
    shard = {"updated_at": "t", "codes": {"777": [
        {"list": "L1", "position": 145, "score_total": 200, "consent": True,
         "priority_pz": 1, "bvi": False, "status": "Участвует в конкурсе"}]}}
    out = L.format_positions(META2, shard, "777")
    assert "⏳" in out
    assert "не все выше" in out.lower() or "линия" in out.lower() or "черт" in out.lower()


def test_quota_list_not_compared_with_full_places(monkeypatch):
    _fake_places(monkeypatch)
    meta = {"updated_at": "t", "lists": {
        "G": {"direction": "44.03.01 История", "form": "очная",
              "kind": "бюджет", "count": 300},
        "Q": {"direction": "44.03.01 История", "form": "очная",
              "kind": "бюджет", "count": 18}}}
    shard = {"updated_at": "t", "codes": {"888": [
        {"list": "Q", "position": 5, "score_total": 210, "consent": True,
         "priority_pz": 1, "bvi": False, "status": "Участвует в конкурсе"}]}}
    out = L.format_positions(meta, shard, "888")
    # позиция в неосновном списке не сравнивается с полным КЦП
    assert "мест: 30" not in out
    assert "особый вид мест" in out.lower()


def test_vid_mest_from_page_used_as_label(monkeypatch):
    _fake_places(monkeypatch)
    meta = {"updated_at": "t", "lists": {
        "Q": {"direction": "44.03.01 История", "form": "очная", "kind": "бюджет",
              "count": 18, "vid_mest": "места в пределах особой квоты"}}}
    shard = {"updated_at": "t", "codes": {"888": [
        {"list": "Q", "position": 5, "score_total": 210, "consent": True,
         "priority_pz": 1, "bvi": False, "status": "Участвует"}]}}
    out = L.format_positions(meta, shard, "888")
    assert "особой квоты" in out          # берём формулировку с epk25


def test_branch_shown_in_labels(monkeypatch):
    # у филиала то же название направления, но свой КЦП — филиал обязан быть виден
    import scraper.abitur.lists as LM
    LM._PLACES_CACHE.clear(); LM._QUOTA_CACHE.clear()
    monkeypatch.setattr(LM, "_quota_for", lambda m: None)
    meta = {"updated_at": "t", "lists": {
        "F": {"direction": "44.03.01 Педагогическое образование. Физическая культура",
              "form": "очная", "kind": "бюджет", "count": 56, "general": True,
              "places": 16, "kcp_from_epk": True, "consented": 10,
              "unit": "Покровский филиал"}}}
    shard = {"updated_at": "t", "codes": {"777": [
        {"list": "F", "position": 9, "score_total": 230, "consent": True,
         "priority_pz": 1, "bvi": False, "status": "Участвует",
         "cons_above": 3, "sim_above": 4}]}}
    full = L.format_positions(meta, shard, "777")
    short = L.format_positions_short(meta, shard, "777")
    assert "Покровский филиал" in full
    assert "Покровский ф-л" in short
    assert "~5-е из 16" in full and "~5-е из 16" in short   # свой КЦП филиала


def test_no_places_known_degrades_gracefully(monkeypatch):
    import scraper.abitur.lists as LM
    monkeypatch.setattr(LM, "_places_for", lambda m: None)
    out = L.format_positions(META2, SHARD2, "555")
    assert "45 из 300" in out          # «из N» остаётся
    assert "мест:" not in out          # мест не выдумываем


# ── Компактный вид /spisok (короткие строки + вердикт) ───────────────────────

META3 = {"updated_at": "2026-07-18T16:38:29+03:00", "campaign": "2026", "lists": {
    "G1": {"direction": "44.03.01 Педагогическое образование. География",
           "form": "заочная", "kind": "бюджет", "count": 287,
           "general": True, "places": 15},
    "G2": {"direction": "44.03.02 Психолого-педагогическое образование. Практическая психология. Профессиональное консультирование",
           "form": "очная", "kind": "бюджет", "count": 945,
           "general": True, "places": 25},
    "P1": {"direction": "44.03.01 Педагогическое образование. География",
           "form": "заочная", "kind": "платное", "count": 51},
}}
SHARD3 = {"updated_at": "t", "codes": {"777": [
    {"list": "G2", "position": 77, "score_total": 241, "consent": False,
     "priority_pz": 3, "bvi": False, "status": "Участвует в конкурсе",
     "cons_above": 4, "sim_above": 1},
    {"list": "G1", "position": 12, "score_total": 250, "consent": False,
     "priority_pz": 1, "bvi": False, "status": "Участвует в конкурсе",
     "cons_above": 2, "sim_above": 2},
    {"list": "P1", "position": 3, "score_total": 250, "consent": False,
     "priority_pz": 2, "bvi": False, "status": "Участвует в конкурсе"},
]}}


def test_short_format_is_compact_and_sorted_by_priority(monkeypatch):
    import scraper.abitur.lists as LM
    LM._QUOTA_CACHE.clear()
    monkeypatch.setattr(LM, "_quota_for", lambda m: None)   # без вычета квот в тесте
    out = L.format_positions_short(META3, SHARD3, "777")
    lines = [l for l in out.split("\n") if l.startswith(("✅", "⏳", "▫️", "💳"))]
    assert len(lines) == 3
    # сортировка по приоритету: П1 (география) первым
    assert "П1" in lines[0] and "География" in lines[0]
    assert "~3-е из 15" in lines[0]           # sim_above=2 → ~3-е
    assert "П2" in lines[1] and "💳" in lines[1]   # платное с маркером
    # длинное название обрезано, «Педагогическое образование.» убрано
    assert "Психолого-педагогическое образование." not in out
    # вердикт есть
    assert "прошли бы на" in out
    # честная оговорка
    assert "предварительно" in out.lower()


def test_short_format_has_consent_warning_one_liner(monkeypatch):
    import scraper.abitur.lists as LM
    monkeypatch.setattr(LM, "_quota_for", lambda m: None)
    out = L.format_positions_short(META3, SHARD3, "777")
    assert "5 августа" in out and "огласие" in out


def test_short_not_found_same_as_full():
    out = L.format_positions_short(META3, {"updated_at": "t", "codes": {}}, "999")
    assert "не найден" in out.lower()


# ── Матчинг списка → программа: специфичность и ручные привязки ──────────────

def _progs(monkeypatch, progs):
    import scraper.abitur.shansy as S
    import scraper.abitur.lists as LM
    LM._PLACES_CACHE.clear(); LM._QUOTA_CACHE.clear()
    monkeypatch.setattr(S, "load_programs", lambda: progs)


def test_specific_group_beats_generic_short_name(monkeypatch):
    # «История» (32) совпадает «заодно» с группой «История и Воспитательная
    # работа/…» (58) — берём группу, а не молчим из-за неоднозначности
    _progs(monkeypatch, [
        {"code": "44.03.01", "form": "очная", "paid_only": False, "places": 58,
         "name": "Педагогическое образование, направленность История и Воспитательная работа/Обществознание и Экономико-правовое образование"},
        {"code": "44.03.01", "form": "очная", "paid_only": False, "places": 32,
         "name": "Педагогическое образование, направленность История"},
    ])
    m = {"direction": "44.03.01 Педагогическое образование. История и "
                      "Воспитательная работа/Обществознание и Экономико-правовое образование",
         "form": "очная", "kind": "бюджет"}
    assert L._places_for(m) == 58


def test_ambiguity_without_nesting_still_silent(monkeypatch):
    # два кандидата с разными местами, ни один не вложен в другой → честный None
    _progs(monkeypatch, [
        {"code": "44.03.01", "form": "очная", "paid_only": False, "places": 20,
         "name": "Педагогическое образование, направленность Химия и Экология"},
        {"code": "44.03.01", "form": "очная", "paid_only": False, "places": 30,
         "name": "Педагогическое образование, направленность Биология и Экология"},
    ])
    m = {"direction": "44.03.01 Педагогическое образование. Химия и Биология и Экология",
         "form": "очная", "kind": "бюджет"}
    assert L._places_for(m) is None


def test_alias_map_resolves_abbreviated_direction():
    # реальная привязка из list_aliases_2026.json: «Доп» на epk25 ≠ «Дополнительное»
    import scraper.abitur.lists as LM
    LM._PLACES_CACHE.clear(); LM._QUOTA_CACHE.clear()
    m = {"direction": "44.03.01 Педагогическое образование. Изобразительное "
                      "искусство и Доп образование",
         "form": "очная", "kind": "бюджет"}
    assert L._places_for(m) == 30
    assert L._quota_for(m) == 6


def test_alias_file_targets_exist_in_catalog():
    # каждая привязка указывает ровно на одну программу каталога (code+form)
    import json as J
    from pathlib import Path
    from scraper.abitur import shansy
    doc = J.loads((Path(L.__file__).parent / "list_aliases_2026.json")
                  .read_text(encoding="utf-8"))
    progs = shansy.load_programs() + L._mag_programs()
    assert doc["aliases"], "файл привязок пуст"
    for a in doc["aliases"]:
        code = a["direction"].split()[0]
        hits = {L._norm_text(p["name"]) for p in progs
                if p["code"] == code and not p.get("paid_only")
                and L._norm_text(p["name"]) == L._norm_text(a["program"])}
        assert len(hits) == 1, f"привязка не находит программу: {a['direction'][:60]}"


# ── Магистратура: каталог мест и кампус-дубли ────────────────────────────────

def test_mag_places_by_word_match():
    import scraper.abitur.lists as LM
    LM._PLACES_CACHE.clear(); LM._QUOTA_CACHE.clear()
    m = {"direction": "45.04.02 Лингвистика. Теория и практика перевода "
                      "(английский язык)", "form": "очная", "kind": "бюджет"}
    assert L._places_for(m) == 20
    assert L._quota_for(m) is None   # в магистратуре нет особой/отдельной квоты


def test_mag_campus_duplicate_resolved_by_list_code():
    # Москва и Покровский филиал: направление+форма одинаковы, места разные
    import scraper.abitur.lists as LM
    LM._PLACES_CACHE.clear(); LM._QUOTA_CACHE.clear()
    base = {"direction": "44.04.01 Педагогическое образование. Менеджмент "
                         "в образовании", "form": "очная", "kind": "бюджет"}
    msk = dict(base, url="https://epk25.mpgu.su/competitive-list/view?code=000000217")
    fil = dict(base, url="https://epk25.mpgu.su/competitive-list/view?code=000000255")
    assert L._places_for(msk) == 25
    assert L._places_for(fil) == 15


def test_mag_catalog_totals_pinned():
    # приказ КЦП (спец. уровни ВО): 52 программы главного кампуса на 1476 мест
    progs = L._mag_programs()
    main = [p for p in progs if "филиал" not in p["name"]]
    assert len(main) == 52
    assert sum(p["places"] for p in main) == 1476


def test_spisok_detail_shows_prediction_block(monkeypatch):
    import scraper.abitur.lists as LM
    LM._PLACES_CACHE.clear(); LM._QUOTA_CACHE.clear()
    monkeypatch.setattr(LM, "_quota_for", lambda m: None)
    monkeypatch.setattr(LM, "_history_for", lambda m: {"2024": 242, "2025": 244})
    meta = {"updated_at": "t", "lists": {"L": {
        "direction": "44.03.01 История", "form": "очная", "kind": "бюджет",
        "count": 300, "general": True, "places": 20, "consented": 40,
        "sim_cutoff": 230, "cap": 270, "general_seats": 20}}}
    shard = {"updated_at": "t", "codes": {"555": [
        {"list": "L", "position": 5, "score_total": 260, "consent": True,
         "priority_pz": 1, "bvi": False, "status": "Участвует",
         "cons_above": 3, "sim_above": 4}]}}
    out = L.format_positions(meta, shard, "555")
    assert "Примерный проходной-2026: ориентир ~242–244" in out
    assert "по согласиям проходят от ~230" in out
    assert "топ-20" in out and "~270" in out


def test_branch_gets_no_moscow_history():
    # у филиала своё КЦП и свой конкурс — московскую историю подставлять нельзя
    branch = {"direction": "44.03.01 Педагогическое образование. Физическая культура",
              "form": "очная", "kind": "бюджет", "unit": "Дербентский филиал"}
    assert L._history_for(branch) is None
    assert L._prediction_line(branch) is None or "ориентир" not in L._prediction_line(branch)


def test_quota_list_shows_own_seats_and_position(monkeypatch):
    # льготник должен видеть позицию в СВОЁМ квотном конкурсе, а не «платное»
    import scraper.abitur.lists as LM
    LM._PLACES_CACHE.clear(); LM._QUOTA_CACHE.clear()
    meta = {"updated_at": "t", "lists": {"Q": {
        "direction": "44.03.01 Информатика", "form": "очная", "kind": "бюджет",
        "count": 40, "vid_mest": "особая квота", "quota": True,
        "main_kcp": False, "general": False, "kcp_epk": 9}}}
    shard = {"updated_at": "t", "codes": {"321": [
        {"list": "Q", "position": 3, "score_total": 210, "consent": True,
         "priority_pz": 1, "bvi": False, "status": "Участвует"}]}}
    out = L.format_positions(meta, shard, "321")
    assert "особая квота: место 3 из 9" in out
    assert "✅" in out
    assert "платное" not in out
