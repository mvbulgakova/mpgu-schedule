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
        self.assertIn("adm_programs", cbs)
        self.assertIn("adm_calendar", cbs)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
