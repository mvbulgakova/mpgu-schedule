"""Тесты матчинга/поиска учебных планов (карта из study_plans_2026.json)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import study_plans as SP


def test_plans_loaded_and_have_links():
    plans = SP.load_plans()
    assert len(plans) > 100
    assert all(p.get("disc", "").startswith("https://oc.mpgu.su/s/") for p in plans)


def test_share_id_roundtrip():
    p = SP.load_plans()[0]
    sid = SP.share_id(p)
    assert sid and SP.by_share_id(sid) is p


def test_find_by_text_ranks_and_dedupes():
    cands = SP.find_by_text("начальное образование")
    assert cands and cands[0]["code"].startswith("44.03")
    # без дублей (код, профиль, форма)
    keys = [(c["code"], c["profile"], c["form"]) for c in cands]
    assert len(keys) == len(set(keys))


def test_find_by_text_respects_code_filter():
    cands = SP.find_by_text("45.03.02 перевод")
    assert cands and all(c["code"] == "45.03.02" for c in cands)


def test_find_by_text_unknown_returns_empty():
    assert SP.find_by_text("квантовая телепортация драконов") == []


def test_match_plan_prefers_specific_and_base_higher(monkeypatch):
    fake = [
        {"code": "44.03.01", "form": "очная", "profile": "История",
         "level": "высшее образование - бакалавриат", "disc": "https://oc.mpgu.su/s/A"},
        {"code": "44.03.01", "form": "очная", "profile": "История",
         "level": "базовое высшее образование", "disc": "https://oc.mpgu.su/s/B"},
        {"code": "44.03.01", "form": "очная", "profile": "История и Обществознание",
         "level": "базовое высшее образование", "disc": "https://oc.mpgu.su/s/C"},
    ]
    monkeypatch.setattr(SP, "_PLANS", fake)
    got = SP.match_plan("44.03.01", "очная",
                        "Педагогическое образование, направленность История")
    assert got["disc"].endswith("/B")            # точный профиль + базовое высшее
