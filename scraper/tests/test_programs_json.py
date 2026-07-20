"""Инварианты справочника программ 2026 (Приложение 1 + КЦП).

Запуск: python -m pytest scraper/tests/test_programs_json.py -v
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

P = Path(__file__).resolve().parents[1] / "abitur" / "programs_2026.json"


def _load():
    return json.loads(P.read_text(encoding="utf-8"))


def test_file_exists_and_nonempty():
    data = _load()
    assert len(data["programs"]) > 80  # в Приложении 1 их сотни
    assert data["campaign"] == "2026/27"


def test_every_program_shape():
    for p in _load()["programs"]:
        assert re.match(r"\d{2}\.\d{2}\.\d{2}$", p["code"]), p
        assert p["name"] and p["form"] in ("очная", "очно-заочная", "заочная")
        assert 2 <= len(p["exam_slots"]) <= 3, p["name"]
        subs = [s for slot in p["exam_slots"] for s in slot]
        assert any("русский" in s.lower() for s in subs), p["name"]


def test_kcp_matched_for_most_budget_programs():
    progs = _load()["programs"]
    budget = [p for p in progs if not p.get("paid_only")]
    with_places = [p for p in budget if p.get("places")]
    assert len(with_places) >= 0.7 * len(budget)


def test_known_program_spot_checks():
    """Ручная сверка с PDF (Приложение 1 / КЦП): география и журналистика."""
    by = {(p["code"], p["form"], p["name"][:20]): p for p in _load()["programs"]}
    geo = next(p for p in _load()["programs"]
               if p["code"] == "05.03.02" and p["form"] == "очная")
    assert geo["places"] == 20
    assert ["Русский язык"] in geo["exam_slots"]
    assert any("География" in s for slot in geo["exam_slots"] for s in slot)

    zhur = next(p for p in _load()["programs"] if p["code"] == "42.03.02")
    assert zhur["dvi"] is True and zhur["paid_only"] is True


def test_dvi_flag_consistency():
    for p in _load()["programs"]:
        has_ispytanie = any("испытание" in s.lower()
                            for slot in p["exam_slots"] for s in slot)
        assert p["dvi"] == has_ispytanie, p["name"]


def test_places_pinned_to_kcp_order():
    """Регресс-пины мест по приказу КЦП (групповой файл kcpbvobacspec_1)."""
    import json
    from pathlib import Path
    progs = json.loads((Path(__file__).resolve().parents[1] / "abitur"
                        / "programs_2026.json").read_text(encoding="utf-8"))["programs"]

    def places(pred):
        vals = {p.get("places") for p in progs
                if pred(p) and not p.get("paid_only")}
        assert len(vals) == 1, vals
        return vals.pop()

    # у платных программ мест КЦП не бывает
    assert all(p.get("places") is None for p in progs if p.get("paid_only"))

    assert places(lambda p: p["form"] == "очная"
                  and p["name"].endswith("направленность Химия")) == 15
    assert places(lambda p: p["form"] == "очная" and p["name"].endswith(
        "направленность Иностранный язык (английский)")) == 20
    assert places(lambda p: p["form"] == "очная"
                  and "История и Воспитательная работа/Обществознание" in p["name"]) == 58
    assert places(lambda p: p["form"] == "очная"
                  and "Психология и педагогика. Профессиональное консультирование/"
                  in p["name"].replace(" /", "/")) in (100,)


def test_no_duplicate_programs():
    """Полные дубли (включая одинаковые ВИ с точностью до порядка) — запрещены.

    Одноимённые программы с РАЗНЫМИ ВИ допустимы (разные конкурсные группы).
    """
    import json
    from pathlib import Path
    progs = json.loads((Path(__file__).resolve().parents[1] / "abitur"
                        / "programs_2026.json").read_text(encoding="utf-8"))["programs"]
    keys = [(p["code"], p.get("form"), p["name"], bool(p.get("paid_only")),
             frozenset(frozenset(s) for s in p["exam_slots"]))
            for p in progs]
    assert len(keys) == len(set(keys)), "полные дубли программ в каталоге"
