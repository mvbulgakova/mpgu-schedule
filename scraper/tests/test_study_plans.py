"""Тесты матчинга/поиска учебных планов (карта из study_plans_2026.json)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import study_plans as SP


def test_plans_loaded_and_have_links():
    plans = SP.load_plans()
    assert len(plans) > 100
    assert all(SP.share_url(p).startswith("https://oc.mpgu.su/s/") for p in plans)


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
         "level": "высшее образование - бакалавриат", "plan": "https://oc.mpgu.su/s/A"},
        {"code": "44.03.01", "form": "очная", "profile": "История",
         "level": "базовое высшее образование", "plan": "https://oc.mpgu.su/s/B"},
        {"code": "44.03.01", "form": "очная", "profile": "История и Обществознание",
         "level": "базовое высшее образование", "plan": "https://oc.mpgu.su/s/C"},
    ]
    monkeypatch.setattr(SP, "_PLANS", fake)
    got = SP.match_plan("44.03.01", "очная",
                        "Педагогическое образование, направленность История")
    assert SP.share_url(got).endswith("/B")       # точный профиль + базовое высшее


# ── Устаревшие планы не должны попадать в выбор ───────────────────────────────

def test_renumbered_programme_does_not_show_up_twice(monkeypatch):
    """МПГУ перенумеровал двухпрофильные: 44.03.05 (2023) → 44.03.01 (2026).

    Дедупликация шла по (код, профиль, форма), а код разный — и абитуриент
    видел две одинаковые с виду строки «Математика и Экономика (очная)»,
    одна из которых вела на план 2023 года по снятой с набора программе.
    """
    plans = [
        {"code": "44.03.01", "napr": "Педагогическое образование",
         "profile": "Математика и Экономика", "level": "базовое высшее образование",
         "form": "очная", "year": "2026", "plan": "https://oc.mpgu.su/s/NEW"},
        {"code": "44.03.05", "napr": "Педагогическое образование (с двумя профилями)",
         "profile": "Математика и Экономика", "level": "высшее образование - бакалавриат",
         "form": "очная", "year": "2023", "plan": "https://oc.mpgu.su/s/OLD"},
    ]
    monkeypatch.setattr(SP, "_PLANS", plans)
    got = SP.find_by_text("математика экономика")
    assert [p["code"] for p in got] == ["44.03.01"]


def test_a_different_level_with_the_same_name_survives(monkeypatch):
    """«Юриспруденция» есть и в СПО, и в высшем — это разные программы.

    Ступень задаёт средний сегмент кода ФГОС: 02 — СПО, 03 — бакалавриат.
    """
    plans = [
        {"code": "40.03.01", "napr": "Юриспруденция", "profile": "Юриспруденция",
         "level": "базовое высшее образование", "form": "очная", "year": "2026",
         "plan": "https://oc.mpgu.su/s/VO"},
        {"code": "40.02.04", "napr": "Юриспруденция", "profile": "Юриспруденция",
         "level": "Среднее профессиональное образование", "form": "очная",
         "year": "2024", "plan": "https://oc.mpgu.su/s/SPO"},
    ]
    monkeypatch.setattr(SP, "_PLANS", plans)
    assert {p["code"] for p in SP.find_by_text("юриспруденция")} == {"40.03.01",
                                                                     "40.02.04"}


def test_stale_year_is_shown_in_the_button(monkeypatch):
    """Если у программы нет плана текущего набора — год виден сразу."""
    import scraper.telegram_bot as bot
    plans = [
        {"code": "44.03.01", "napr": "X", "profile": "Свежая", "form": "очная",
         "level": "базовое высшее образование", "year": "2026",
         "plan": "https://oc.mpgu.su/s/A"},
        {"code": "44.03.02", "napr": "X", "profile": "Старая", "form": "очная",
         "level": "высшее образование - бакалавриат", "year": "2024",
         "plan": "https://oc.mpgu.su/s/B"},
    ]
    monkeypatch.setattr(SP, "_PLANS", plans)
    by_prof = {p["profile"]: bot._plan_label(p) for p in plans}
    assert "2026" not in by_prof["Свежая"]
    assert by_prof["Старая"].endswith("(очная, 2024)")
