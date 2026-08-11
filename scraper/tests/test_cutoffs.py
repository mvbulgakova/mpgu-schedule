"""Проходные баллы 2026: поиск и вывод. Без сети.

Запуск: python -m pytest scraper/tests/test_cutoffs.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scraper.telegram_bot as bot
from scraper.abitur import cutoffs


def _rows():
    """Схема приказа: вид конкурса, зачисленные, из них БВИ."""
    return [
        {"direction": "45.03.02 Лингвистика. Теория и методика", "form": "очная",
         "kind": "бюджет", "competition": "общий конкурс",
         "level": "basic_higher_education", "unit": "Институт иностранных языков",
         "enrolled": 5, "bvi": 0, "counted": 5, "cutoff": 290, "exact": True},
        {"direction": "44.03.01 Педагогическое образование. Математика и Экономика",
         "form": "очная", "kind": "бюджет", "competition": "общий конкурс",
         "level": "basic_higher_education", "unit": "ИМИ",
         "enrolled": 16, "bvi": 0, "counted": 16, "cutoff": 150, "exact": True},
        {"direction": "45.04.02 Лингвистика. Теория и практика перевода",
         "form": "очная", "kind": "бюджет", "competition": "общий конкурс",
         "level": "specialized_higher_education", "unit": "ИИЯ",
         "enrolled": 20, "bvi": 0, "counted": 20, "cutoff": 56, "exact": True},
        {"direction": "44.03.01 Педагогическое образование. Химия", "form": "очная",
         "kind": "платное", "competition": "общий конкурс",
         "level": "basic_higher_education", "unit": "ИБХ",
         "enrolled": 100, "bvi": 0, "counted": 2, "cutoff": 120, "exact": False},
        {"direction": "44.03.01 Педагогическое образование. Математика и Экономика",
         "form": "заочная", "kind": "бюджет", "competition": "общий конкурс",
         "level": "basic_higher_education", "unit": "Анапский филиал",
         "enrolled": 16, "bvi": 0, "counted": 14, "cutoff": 137, "exact": True},
        # та же программа, но по квоте: свои места и совсем другой порог
        {"direction": "44.03.01 Педагогическое образование. Математика и Экономика",
         "form": "очная", "kind": "бюджет", "competition": "отдельная квота",
         "level": "basic_higher_education", "unit": "ИМИ",
         "enrolled": 4, "bvi": 2, "counted": 2, "cutoff": 63, "exact": True},
        {"direction": "44.03.01 Педагогическое образование. Математика и Экономика",
         "form": "очная", "kind": "бюджет", "competition": "особая квота",
         "level": "basic_higher_education", "unit": "ИМИ",
         "enrolled": 3, "bvi": 0, "counted": 3, "cutoff": 129, "exact": True},
    ]


def _wire(monkeypatch):
    monkeypatch.setattr(cutoffs, "_DATA", _rows())


def test_only_budget_lists_count_as_cutoffs(monkeypatch):
    """«Проходной» люди спрашивают про бюджет; платные места — другой разговор."""
    _wire(monkeypatch)
    kinds = {r["kind"] for r in cutoffs.budget(with_branches=True)}
    assert kinds == {"бюджет"}


def test_bachelor_ranking_does_not_mix_in_masters(monkeypatch):
    """У магистратуры своя шкала — вступительный экзамен вуза, а не ЕГЭ.

    В общем рейтинге магистерские 56 вставали рядом с бакалаврскими 137 и
    выглядели как «самое доступное направление МПГУ».
    """
    _wire(monkeypatch)
    txt = cutoffs.format_extremes(2)
    assert "Теория и практика перевода" not in txt   # магистерская — не здесь
    assert "56" not in txt                            # и её балл тоже
    assert "290" in txt and "150" in txt


def test_search_orders_results_by_score(monkeypatch):
    """Подборку читают, чтобы сравнить, — вперемешку она нечитаема."""
    _wire(monkeypatch)
    got = cutoffs.find("лингвистика")
    assert [r["cutoff"] for r in got] == sorted(
        (r["cutoff"] for r in got), reverse=True)


def test_masters_are_labelled_when_they_show_up_in_search(monkeypatch):
    _wire(monkeypatch)
    txt = cutoffs.format_results(cutoffs.find("лингвистика"))
    assert "магистратура" in txt


def test_quotas_are_shown_apart_from_the_general_competition(monkeypatch):
    """У квоты свои места и свой порог: 63 против 150 на той же программе.

    В одном столбце это читается как один конкурс — человек решает, что
    прошёл бы со своими 70 баллами.
    """
    _wire(monkeypatch)
    txt = cutoffs.format_results(cutoffs.find("математика экономика"))
    for title in ("Общий конкурс", "Особая квота", "Отдельная квота"):
        assert f"<b>{title}</b>" in txt, title
    assert txt.index("Общий конкурс") < txt.index("Отдельная квота")


def test_quotas_stay_out_of_the_main_ranking(monkeypatch):
    """Иначе «самое доступное направление МПГУ» — это квотные 63 балла."""
    _wire(monkeypatch)
    assert {r["competition"] for r in cutoffs.budget()} == {"общий конкурс"}
    assert "63" not in cutoffs.format_extremes(3)


def test_bvi_enrollees_are_named_and_not_counted(monkeypatch):
    """БВИ проходят вне конкурса: в порог их брать нельзя, но сказать надо."""
    _wire(monkeypatch)
    txt = cutoffs.format_results(cutoffs.find("математика экономика"))
    assert "2 по БВИ" in txt and "не взяты" in txt


def test_search_by_code(monkeypatch):
    _wire(monkeypatch)
    got = cutoffs.find("45.03.02")
    assert [r["direction"] for r in got] == ["45.03.02 Лингвистика. Теория и методика"]


def test_nothing_found_suggests_how_to_ask(monkeypatch):
    _wire(monkeypatch)
    txt = cutoffs.format_results(cutoffs.find("квантовая телепортация"),
                                 "квантовая телепортация")
    assert "Попробуйте" in txt


# ── Кнопка и команда в боте ──────────────────────────────────────────────────

def test_menu_has_the_button():
    labels = [b[0] for row in bot._menu_keyboard() for b in row]
    assert any("Проходные" in x for x in labels)


def test_button_shows_the_overview_and_waits_for_a_direction(monkeypatch):
    _wire(monkeypatch)
    bot.AWAITING_CUTOFF.clear()
    out = bot.handle_callback(chat_id=7, data="open:cutoff")
    assert "Проходные баллы" in out.text
    assert bot.AWAITING_CUTOFF.get(7) is True
    # следующее сообщение — название направления
    ans = bot.handle_message(7, "лингвистика")
    assert "290" in ans.text
    assert 7 not in bot.AWAITING_CUTOFF


def test_command_with_an_argument_answers_at_once(monkeypatch):
    _wire(monkeypatch)
    bot.AWAITING_CUTOFF.clear()
    out = bot.handle_message(8, "/prohodnye лингвистика")
    assert "290" in out.text
    assert 8 not in bot.AWAITING_CUTOFF


def test_menu_button_cancels_waiting(monkeypatch):
    _wire(monkeypatch)
    bot.AWAITING_CUTOFF[9] = True
    bot.handle_callback(chat_id=9, data="open:menu")
    assert 9 not in bot.AWAITING_CUTOFF


# ── Филиалы отдельно от Москвы ───────────────────────────────────────────────

def test_branches_are_out_of_the_moscow_ranking(monkeypatch):
    """У филиала свой КЦП и свой конкурс, а название направления московское.

    Проходные там заметно ниже: на живых данных 2026 московский минимум по
    бакалавриату — 188, а все цифры ниже (137 Черняховск, 142 Дербент,
    150 Анапа) оказались филиальскими. В общем рейтинге они выглядели как
    «самые доступные направления МПГУ».
    """
    _wire(monkeypatch)
    assert all(not cutoffs.is_branch(r) for r in cutoffs.budget())
    txt = cutoffs.format_extremes(2)
    assert "Москва" in txt
    assert "137" not in txt          # филиальский балл в московский рейтинг не лезет


def test_search_shows_moscow_and_branches_in_separate_blocks(monkeypatch):
    _wire(monkeypatch)
    txt = cutoffs.format_results(cutoffs.find("математика экономика"))
    assert "Москва:" in txt and "Филиалы:" in txt
    assert txt.index("Москва:") < txt.index("Филиалы:")


def test_branch_entry_names_the_city(monkeypatch):
    """«· Анапский» — прилагательное без существительного, читается обрубком."""
    _wire(monkeypatch)
    txt = cutoffs.format_results(cutoffs.find("математика экономика"))
    assert "Анапа" in txt and "Анапский" not in txt


def test_overview_tells_where_the_branches_went(monkeypatch):
    _wire(monkeypatch)
    assert "Анапа" in cutoffs.format_extremes(1)
