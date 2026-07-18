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


def _fake_places(monkeypatch):
    import scraper.abitur.lists as LM
    monkeypatch.setattr(LM, "_places_for",
                        lambda m: {"44.03.01 История": 30,
                                   "44.03.01 География": 25}.get(m.get("direction")))


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
    assert "Сейчас проход" in out and "География" in out
    # квоты вернутся после приоритетного этапа — сноска присутствует
    assert "приоритетного этапа" in out


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
    # позиция в малом (квотном) списке не сравнивается с полным КЦП
    assert "мест: 30" not in out
    assert "квотн" in out.lower()


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


def test_short_format_is_compact_and_sorted_by_priority():
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
    assert "пройдёте на" in out or "проходите на" in out
    # компакт: без огромных сносок
    assert "КЦП" not in out


def test_short_format_has_consent_warning_one_liner():
    out = L.format_positions_short(META3, SHARD3, "777")
    assert "5 августа" in out and "огласие" in out


def test_short_not_found_same_as_full():
    out = L.format_positions_short(META3, {"updated_at": "t", "codes": {}}, "999")
    assert "не найден" in out.lower()
