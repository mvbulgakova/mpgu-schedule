"""Проходные баллы 2026: поиск и вывод. Без сети.

Запуск: python -m pytest scraper/tests/test_cutoffs.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scraper.telegram_bot as bot
from scraper.abitur import cutoffs


def _rows():
    return [
        {"list": "1", "direction": "45.03.02 Лингвистика. Теория и методика",
         "form": "очная", "kind": "бюджет", "level": "basic_higher_education",
         "unit": "Институт иностранных языков", "seats": 5, "vpp": 5, "bvi": 0,
         "cutoff": 290, "exact": True},
        {"list": "2", "direction": "44.03.01 Педагогическое образование. Математика и Экономика",
         "form": "очная", "kind": "бюджет", "level": "basic_higher_education",
         "unit": "ИМИ", "seats": 16, "vpp": 14, "bvi": 0,
         "cutoff": 150, "exact": False},
        {"list": "3", "direction": "45.04.02 Лингвистика. Теория и практика перевода",
         "form": "очная", "kind": "бюджет", "level": "specialized_higher_education",
         "unit": "ИИЯ", "seats": 20, "vpp": 3, "bvi": 0, "cutoff": 56, "exact": False},
        {"list": "4", "direction": "44.03.01 Педагогическое образование. Химия",
         "form": "очная", "kind": "платное", "level": "basic_higher_education",
         "unit": "ИБХ", "seats": 100, "vpp": 2, "bvi": 0, "cutoff": 120, "exact": False},
        {"list": "5", "direction": "44.03.01 Педагогическое образование. Математика и Экономика",
         "form": "заочная", "kind": "бюджет", "level": "basic_higher_education",
         "unit": "Анапский филиал", "seats": 16, "vpp": 14, "bvi": 0,
         "cutoff": 137, "exact": False},
    ]


def _wire(monkeypatch):
    monkeypatch.setattr(cutoffs, "_DATA", _rows())


def test_only_budget_lists_count_as_cutoffs(monkeypatch):
    """«Проходной» люди спрашивают про бюджет; платные места — другой разговор."""
    _wire(monkeypatch)
    assert {r["list"] for r in cutoffs.budget(with_branches=True)} == {"1", "2", "3", "5"}


def test_bachelor_ranking_does_not_mix_in_masters(monkeypatch):
    """У магистратуры своя шкала — вступительный экзамен вуза, а не ЕГЭ.

    В общем рейтинге магистерские 56 вставали рядом с бакалаврскими 137 и
    выглядели как «самое доступное направление МПГУ».
    """
    _wire(monkeypatch)
    txt = cutoffs.format_extremes(2)
    assert "Теория и практика перевода" not in txt   # магистерская — не здесь
    assert "56" not in txt                            # и её балл тоже
    assert "бакалавриат, <b>Москва</b> — 2 списков" in txt   # только бакалавриат
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


def test_unreliable_number_is_marked(monkeypatch):
    """Где отметок ВПП меньше, чем мест, проходной — верхняя оценка."""
    _wire(monkeypatch)
    txt = cutoffs.format_results(cutoffs.find("математика экономика"))
    assert "приблизительная" in txt


def test_search_by_code(monkeypatch):
    _wire(monkeypatch)
    assert {r["list"] for r in cutoffs.find("45.03.02")} == {"1"}


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
    assert {r["list"] for r in cutoffs.budget()} == {"1", "2", "3"}
    txt = cutoffs.format_extremes(2)
    assert "Москва" in txt
    assert "137" not in txt          # филиальский балл в московский рейтинг не лезет


def test_search_shows_moscow_and_branches_in_separate_blocks(monkeypatch):
    _wire(monkeypatch)
    txt = cutoffs.format_results(cutoffs.find("математика экономика"))
    assert "<b>Москва:</b>" in txt and "<b>Филиалы:</b>" in txt
    assert txt.index("<b>Москва:</b>") < txt.index("<b>Филиалы:</b>")


def test_branch_entry_names_the_city(monkeypatch):
    """«· Анапский» — прилагательное без существительного, читается обрубком."""
    _wire(monkeypatch)
    txt = cutoffs.format_results(cutoffs.find("математика экономика"))
    assert "Анапа" in txt and "Анапский" not in txt


def test_overview_tells_where_the_branches_went(monkeypatch):
    _wire(monkeypatch)
    assert "Анапа" in cutoffs.format_extremes(1)
