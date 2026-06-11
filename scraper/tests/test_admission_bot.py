"""Тесты для абитуриентского раздела бота.

python -m pytest scraper/tests/test_admission_bot.py -v
"""
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.telegram_bot import (
    _make_keyboard,
    _snils_norm,
    _SNILS_RE,
    _calc_volunteer_score,
    _calc_id_scores,
    _format_id_result,
    _parse_scores,
    _is_border_region,
    check_border_region,
    handle,
    handle_callback,
    search_by_snils,
    _send_calendar,
    _send_documents,
    _STATE,
)


# ---------------------------------------------------------------------------
# СНИЛС — формат и нормализация
# ---------------------------------------------------------------------------

class TestSnilsNorm(unittest.TestCase):
    def test_strips_dashes_and_spaces(self):
        self.assertEqual(_snils_norm("123-456-789 01"), "12345678901")

    def test_strips_dashes_only(self):
        self.assertEqual(_snils_norm("123-456-789-01"), "12345678901")

    def test_digits_only_unchanged(self):
        self.assertEqual(_snils_norm("12345678901"), "12345678901")

    def test_empty_string(self):
        self.assertEqual(_snils_norm(""), "")

    def test_re_matches_standard(self):
        self.assertIsNotNone(_SNILS_RE.search("123-456-789 01"))

    def test_re_matches_digits_only(self):
        self.assertIsNotNone(_SNILS_RE.search("12345678901"))

    def test_re_no_match_short(self):
        self.assertIsNone(_SNILS_RE.search("12345"))


# ---------------------------------------------------------------------------
# Поиск по СНИЛС
# ---------------------------------------------------------------------------

_MOCK_INDEX = {"lists": [{"code": "44_03_01", "count": 3}]}
_MOCK_LIST_FOUND = {
    "direction_name": "Педагогическое образование",
    "budget_seats": 2,
    "applicants": [
        {"snils": "123-456-789 01", "score_total": 268, "rank": 1, "status": "recommended"},
        {"snils": "987-654-321 00", "score_total": 250, "rank": 2, "status": ""},
        {"snils": "111-222-333 44", "score_total": 200, "rank": 3, "status": ""},
    ],
}


def _mock_adm_json(path: str):
    if path == "ranked_lists/index.json":
        return _MOCK_INDEX
    if "ranked_lists/44_03_01" in path:
        return _MOCK_LIST_FOUND
    raise Exception(f"not found: {path}")


class TestSnilsSearch(unittest.TestCase):
    def test_found_within_budget(self):
        with patch("scraper.telegram_bot._adm_json", side_effect=_mock_adm_json):
            result = search_by_snils("123-456-789 01")
        self.assertIn("Педагогическое образование", result["text"])
        self.assertIn("268", result["text"])
        self.assertIn("✅", result["text"])

    def test_found_outside_budget(self):
        with patch("scraper.telegram_bot._adm_json", side_effect=_mock_adm_json):
            result = search_by_snils("111-222-333 44")
        self.assertIn("⚠️", result["text"])

    def test_not_found(self):
        with patch("scraper.telegram_bot._adm_json", side_effect=_mock_adm_json):
            result = search_by_snils("00000000000")
        self.assertIn("не найдено", result["text"].lower())

    def test_invalid_format(self):
        result = search_by_snils("abc def")
        self.assertIn("Не распознал СНИЛС", result["text"])

    def test_too_short(self):
        result = search_by_snils("12345")
        self.assertIn("Не распознал СНИЛС", result["text"])

    def test_index_unavailable(self):
        def raise_err(path):
            raise Exception("network error")
        with patch("scraper.telegram_bot._adm_json", side_effect=raise_err):
            result = search_by_snils("12345678901")
        self.assertIn("не опубликованы", result["text"].lower())

    def test_empty_index(self):
        with patch("scraper.telegram_bot._adm_json", return_value={"lists": []}):
            result = search_by_snils("12345678901")
        self.assertIn("не опубликованы", result["text"].lower())


# ---------------------------------------------------------------------------
# Inline keyboard
# ---------------------------------------------------------------------------

class TestKeyboard(unittest.TestCase):
    def test_structure(self):
        kb_str = _make_keyboard([
            [("Кнопка 1", "cb_1"), ("Кнопка 2", "cb_2")],
            [("Назад", "back")],
        ])
        kb = json.loads(kb_str)
        self.assertIn("inline_keyboard", kb)
        self.assertEqual(len(kb["inline_keyboard"]), 2)
        self.assertEqual(kb["inline_keyboard"][0][0]["text"], "Кнопка 1")
        self.assertEqual(kb["inline_keyboard"][0][0]["callback_data"], "cb_1")
        self.assertEqual(kb["inline_keyboard"][1][0]["callback_data"], "back")

    def test_single_row(self):
        kb = json.loads(_make_keyboard([[("OK", "ok")]]))
        self.assertEqual(len(kb["inline_keyboard"]), 1)
        self.assertEqual(kb["inline_keyboard"][0][0]["text"], "OK")


# ---------------------------------------------------------------------------
# Обработчик callback-запросов
# ---------------------------------------------------------------------------

class TestHandleCallback(unittest.TestCase):
    def test_main_menu(self):
        result = handle_callback("adm_main", 0)
        self.assertIn("keyboard", result)
        kb = json.loads(result["keyboard"])
        cbs = [btn["callback_data"]
               for row in kb["inline_keyboard"] for btn in row]
        self.assertIn("adm_calendar", cbs)
        self.assertIn("adm_calculator", cbs)
        self.assertIn("adm_snils", cbs)
        self.assertIn("adm_qa", cbs)

    def test_snils_sets_state(self):
        _STATE.clear()
        result = handle_callback("adm_snils", 42)
        self.assertEqual(_STATE.get(42, {}).get("mode"), "snils_wait")
        self.assertIn("СНИЛС", result["text"])

    def test_qa_sets_state(self):
        _STATE.clear()
        result = handle_callback("adm_qa", 99)
        self.assertEqual(_STATE.get(99, {}).get("mode"), "qa_wait")

    def test_docs_menu(self):
        result = handle_callback("adm_docs", 0)
        kb = json.loads(result["keyboard"])
        cbs = [btn["callback_data"]
               for row in kb["inline_keyboard"] for btn in row]
        self.assertIn("adm_docs_budget", cbs)

    def test_unknown_callback(self):
        result = handle_callback("totally_unknown", 0)
        self.assertIn("text", result)


# ---------------------------------------------------------------------------
# Обработчик текстовых сообщений
# ---------------------------------------------------------------------------

class TestHandleText(unittest.TestCase):
    def setUp(self):
        _STATE.clear()

    def test_start_returns_menu(self):
        result = handle("/start", chat_id=1)
        self.assertIn("keyboard", result)
        self.assertIsNotNone(result["keyboard"])

    def test_help_returns_menu(self):
        result = handle("/help", chat_id=1)
        self.assertIsNotNone(result.get("keyboard"))

    def test_snils_wait_dispatches(self):
        _STATE[7] = {"mode": "snils_wait"}
        result = handle("12345678901", chat_id=7)
        # state должно быть сброшено
        self.assertNotIn(7, _STATE)
        # Результат — из search_by_snils
        self.assertIn("text", result)

    def test_qa_wait_dispatches(self):
        _STATE[8] = {"mode": "qa_wait"}
        # Без ANTHROPIC_API_KEY вернёт сообщение об ошибке
        with patch.dict("os.environ", {}, clear=False):
            os_env = __import__("os").environ
            os_env.pop("ANTHROPIC_API_KEY", None)
            result = handle("Какие документы нужны?", chat_id=8)
        self.assertNotIn(8, _STATE)
        self.assertIn("text", result)

    def test_unknown_text_returns_menu(self):
        result = handle("привет как дела", chat_id=0)
        self.assertIn("text", result)


# ---------------------------------------------------------------------------
# Данные о приёмной кампании
# ---------------------------------------------------------------------------

_MOCK_CALENDAR = [
    {"date": "2026-06-20", "event": "Начало приёма", "description": ""},
    {"date": "2026-08-09", "event": "Конец приёма", "description": "Бюджет"},
]

_MOCK_DOCS = {
    "budget": ["Паспорт", "Аттестат", "СНИЛС"],
    "contract": ["Паспорт", "Аттестат"],
    "target": ["Паспорт", "Аттестат", "Целевой договор"],
}


class TestCalendar(unittest.TestCase):
    def test_events_in_text(self):
        with patch("scraper.telegram_bot._adm_json", return_value=_MOCK_CALENDAR):
            result = _send_calendar(None, 0)
        self.assertIn("2026-06-20", result["text"])
        self.assertIn("Начало приёма", result["text"])

    def test_returns_keyboard(self):
        with patch("scraper.telegram_bot._adm_json", return_value=_MOCK_CALENDAR):
            result = _send_calendar(None, 0)
        self.assertIsNotNone(result.get("keyboard"))

    def test_error_fallback(self):
        with patch("scraper.telegram_bot._adm_json", side_effect=Exception("err")):
            result = _send_calendar(None, 0)
        self.assertIn("недоступ", result["text"].lower())


class TestDocuments(unittest.TestCase):
    def test_budget_list(self):
        with patch("scraper.telegram_bot._adm_json", return_value=_MOCK_DOCS):
            result = _send_documents(None, 0, category="budget")
        self.assertIn("Паспорт", result["text"])
        self.assertIn("Аттестат", result["text"])
        self.assertIn("СНИЛС", result["text"])

    def test_no_category_shows_menu(self):
        result = _send_documents(None, 0, category=None)
        kb = json.loads(result["keyboard"])
        cbs = [btn["callback_data"]
               for row in kb["inline_keyboard"] for btn in row]
        self.assertIn("adm_docs_budget", cbs)

    def test_error_fallback(self):
        with patch("scraper.telegram_bot._adm_json", side_effect=Exception("err")):
            result = _send_documents(None, 0, category="budget")
        self.assertIn("недоступ", result["text"].lower())


# ---------------------------------------------------------------------------
# Волонтёрство — точный расчёт баллов
# ---------------------------------------------------------------------------

class TestVolunteerScore(unittest.TestCase):
    def test_high_hours_profile(self):
        pts, label = _calc_volunteer_score("волонтёр 500 часов педагогическое")
        self.assertEqual(pts, 10)

    def test_high_hours_general(self):
        pts, label = _calc_volunteer_score("волонтёр 500 часов спорт")
        self.assertEqual(pts, 8)

    def test_mid_hours_profile(self):
        pts, label = _calc_volunteer_score("волонтёрство 200 часов учитель")
        self.assertEqual(pts, 6)

    def test_mid_hours_general(self):
        pts, label = _calc_volunteer_score("волонтёр 200 часов медицина")
        self.assertEqual(pts, 5)

    def test_low_hours(self):
        pts, label = _calc_volunteer_score("волонтёр 30 часов")
        self.assertEqual(pts, 2)

    def test_no_hours(self):
        pts, label = _calc_volunteer_score("есть волонтёрская книжка")
        self.assertEqual(pts, 2)

    def test_300_hours_profile(self):
        pts, label = _calc_volunteer_score("300 часов образование детей")
        self.assertEqual(pts, 8)

    def test_label_contains_hours(self):
        pts, label = _calc_volunteer_score("волонтёр 240 часов педагоги")
        self.assertIn("240", label)


# ---------------------------------------------------------------------------
# Калькулятор ИД
# ---------------------------------------------------------------------------

class TestIdCalc(unittest.TestCase):
    def test_gto_gold(self):
        result = _calc_id_scores("у меня есть золотой значок ГТО")
        labels = [it["label"] for it in result["items"]]
        self.assertTrue(any("ГТО" in l for l in labels))
        pts = next(it["points"] for it in result["items"] if "ГТО" in it["label"])
        self.assertEqual(pts, 5)

    def test_gto_silver(self):
        result = _calc_id_scores("серебряный значок гто")
        pts = next(it["points"] for it in result["items"] if "ГТО" in it["label"])
        self.assertEqual(pts, 4)

    def test_diploma_honors(self):
        result = _calc_id_scores("аттестат с отличием")
        self.assertEqual(result["total"], 10)

    def test_cap_at_10(self):
        # золотой ГТО (5) + волонтёрство 500ч профильное (10) → лимит 10
        result = _calc_id_scores("золотой ГТО и волонтёрская книжка 500 часов педагогических")
        self.assertLessEqual(result["total"], 10)

    def test_volunteer_only(self):
        result = _calc_id_scores("волонтёрская книжка 150 часов")
        self.assertTrue(any("олон" in it["label"].lower() for it in result["items"]))

    def test_format_nonempty(self):
        result = _calc_id_scores("золотой ГТО")
        text = _format_id_result(result)
        self.assertIn("ГТО", text)
        self.assertIn("балл", text.lower())

    def test_format_empty(self):
        text = _format_id_result({"items": [], "total": 0, "note": ""})
        self.assertIn("описать", text.lower())


# ---------------------------------------------------------------------------
# Парсер баллов ЕГЭ
# ---------------------------------------------------------------------------

class TestScoreParser(unittest.TestCase):
    def test_standard_format(self):
        scores = _parse_scores("Русский 87, Математика профиль 72, Обществознание 80")
        self.assertEqual(scores.get("Русский язык"), 87)
        self.assertEqual(scores.get("Математика (профиль)"), 72)
        self.assertEqual(scores.get("Обществознание"), 80)

    def test_short_aliases(self):
        scores = _parse_scores("рус 90, общ 75, история 68")
        self.assertIn("Русский язык", scores)
        self.assertIn("Обществознание", scores)
        self.assertIn("История", scores)

    def test_ignores_out_of_range(self):
        scores = _parse_scores("Русский 150, Математика 85")
        self.assertNotIn("Русский язык", scores)  # 150 вне диапазона
        self.assertIn("Математика (профиль)", scores)

    def test_empty_input(self):
        scores = _parse_scores("привет как дела")
        self.assertEqual(scores, {})

    def test_biology(self):
        scores = _parse_scores("Биология 91, Химия 79, Русский 88")
        self.assertIn("Биология", scores)
        self.assertIn("Химия", scores)


# ---------------------------------------------------------------------------
# Новые callback-обработчики
# ---------------------------------------------------------------------------

class TestNewCallbacks(unittest.TestCase):
    def test_calculator_menu(self):
        result = handle_callback("adm_calculator", 0)
        kb = json.loads(result["keyboard"])
        cbs = [btn["callback_data"]
               for row in kb["inline_keyboard"] for btn in row]
        self.assertIn("calc_ege", cbs)
        self.assertIn("calc_vi_info", cbs)
        self.assertIn("calc_bvi", cbs)

    def test_calc_ege_sets_state(self):
        from scraper.telegram_bot import _STATE
        _STATE.clear()
        handle_callback("calc_ege", 55)
        self.assertEqual(_STATE.get(55, {}).get("mode"), "calc_ege_waiting")

    def test_id_calc_sets_state(self):
        from scraper.telegram_bot import _STATE
        _STATE.clear()
        handle_callback("id_calc", 66)
        self.assertEqual(_STATE.get(66, {}).get("mode"), "id_waiting")

    def test_paid_menu(self):
        result = handle_callback("adm_paid", 0)
        kb = json.loads(result["keyboard"])
        cbs = [btn["callback_data"]
               for row in kb["inline_keyboard"] for btn in row]
        self.assertIn("paid_cost", cbs)
        self.assertIn("paid_credit", cbs)
        self.assertIn("paid_maternkap", cbs)

    def test_vi_menu(self):
        result = handle_callback("adm_vi", 0)
        kb = json.loads(result["keyboard"])
        cbs = [btn["callback_data"]
               for row in kb["inline_keyboard"] for btn in row]
        self.assertIn("vi_spo", cbs)
        self.assertIn("vi_creative", cbs)

    def test_paid_credit_text(self):
        result = handle_callback("paid_credit", 0)
        self.assertIn("кредит", result["text"].lower())
        self.assertIn("dg@mpgu.su", result["text"])

    def test_paid_maternkap_text(self):
        result = handle_callback("paid_maternkap", 0)
        self.assertIn("материнск", result["text"].lower())
        self.assertIn("econom@mpgu.su", result["text"])

    def test_vi_spo_text(self):
        result = handle_callback("vi_spo", 0)
        self.assertIn("колледж", result["text"].lower())

    def test_vi_creative_text(self):
        result = handle_callback("vi_creative", 0)
        self.assertIn("21 балл", result["text"])

    def test_calc_bvi_text(self):
        result = handle_callback("calc_bvi", 0)
        self.assertIn("олимпиад", result["text"].lower())


# ---------------------------------------------------------------------------
# Приграничные регионы
# ---------------------------------------------------------------------------

class TestBorderRegion(unittest.TestCase):
    def test_belgorod_is_border(self):
        self.assertTrue(_is_border_region("белгородская область"))

    def test_belgorod_city_is_border(self):
        self.assertTrue(_is_border_region("белгород"))

    def test_kursk_is_border(self):
        self.assertTrue(_is_border_region("курская область"))

    def test_lnr_is_border(self):
        self.assertTrue(_is_border_region("лнр"))

    def test_lugansk_is_border(self):
        self.assertTrue(_is_border_region("луганск"))

    def test_dnr_is_border(self):
        self.assertTrue(_is_border_region("днр"))

    def test_crimea_is_border(self):
        self.assertTrue(_is_border_region("республика крым"))

    def test_moscow_not_border(self):
        self.assertFalse(_is_border_region("москва"))

    def test_kazan_not_border(self):
        self.assertFalse(_is_border_region("казань"))

    def test_novosibirsk_not_border(self):
        self.assertFalse(_is_border_region("новосибирская область"))

    def test_check_border_result_is_positive(self):
        # Без LLM (нет ключа): fallback → просто lower() от ввода
        with patch.dict("os.environ", {}, clear=False):
            os_env = __import__("os").environ
            os_env.pop("ANTHROPIC_API_KEY", None)
            result = check_border_region("белгород")
        self.assertIn("✅", result["text"])
        self.assertIn("право сдавать", result["text"].lower())

    def test_check_border_result_is_negative(self):
        with patch.dict("os.environ", {}, clear=False):
            os_env = __import__("os").environ
            os_env.pop("ANTHROPIC_API_KEY", None)
            result = check_border_region("москва")
        self.assertIn("ℹ️", result["text"])
        self.assertIn("общих основаниях", result["text"].lower())

    def test_vi_menu_has_border_button(self):
        result = handle_callback("adm_vi", 0)
        kb = json.loads(result["keyboard"])
        cbs = [btn["callback_data"]
               for row in kb["inline_keyboard"] for btn in row]
        self.assertIn("vi_border", cbs)

    def test_vi_border_sets_state(self):
        from scraper.telegram_bot import _STATE
        _STATE.clear()
        handle_callback("vi_border", 77)
        self.assertEqual(_STATE.get(77, {}).get("mode"), "border_region_waiting")

    def test_border_region_state_dispatches(self):
        from scraper.telegram_bot import _STATE
        _STATE[88] = {"mode": "border_region_waiting"}
        with patch.dict("os.environ", {}, clear=False):
            os_env = __import__("os").environ
            os_env.pop("ANTHROPIC_API_KEY", None)
            result = handle("курск", chat_id=88)
        self.assertNotIn(88, _STATE)
        self.assertIn("✅", result["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
