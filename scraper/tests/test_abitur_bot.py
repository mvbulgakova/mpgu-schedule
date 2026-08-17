"""Тесты диспетчеризации бота (без сети).

Запуск: python -m pytest scraper/tests/test_abitur_bot.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scraper.telegram_bot as bot


def setup_function(_):
    bot.SESSIONS.clear()
    bot.AWAITING_SCORES.clear()
    bot.AWAITING_PLAN.clear()


def test_start_returns_greeting_with_menu():
    out = bot.handle_message(chat_id=1, text="/start")
    assert out.keyboard, "ожидается меню тем"
    assert "абитур" in out.text.lower() or "поступл" in out.text.lower()


def test_menu_lists_topics():
    out = bot.handle_message(chat_id=1, text="/abitur")
    data = [cb for row in out.keyboard for (_, cb) in row]
    assert any(cb.startswith("t:") for cb in data)


def test_calc_command_starts_dialog():
    out = bot.handle_message(chat_id=1, text="/bally")
    assert 1 in bot.SESSIONS
    assert "уровень" in out.text.lower()


def test_volunteer_hours_message_during_calc():
    bot.handle_message(chat_id=2, text="/bally")
    bot.handle_callback(chat_id=2, data="c:level:base")
    bot.handle_callback(chat_id=2, data="c:pedagogical:1")
    bot.handle_callback(chat_id=2, data="c:target:0")
    out = bot.handle_message(chat_id=2, text="200")
    assert bot.SESSIONS[2].volunteer_hours == 200
    assert "200" in out.text or "Шаг" in out.text


def test_topic_callback_returns_answer():
    out = bot.handle_callback(chat_id=3, data="t:contacts")
    assert "priem@mpgu.su" in out.text


def test_free_question_without_credentials_falls_back(monkeypatch):
    # фабрика клиента бросает → деградация без падения
    monkeypatch.setattr(bot, "_answer_free",
                        lambda cid, q: "Спросите кнопками /abitur или у приёмной комиссии: priem@mpgu.su")
    out = bot.handle_message(chat_id=4, text="а когда подавать документы?")
    assert "priem@mpgu.su" in out.text


def test_dates_route_via_callback_and_command():
    out = bot.handle_message(chat_id=7, text="/sroki")
    data = [cb for row in out.keyboard for (_, cb) in row]
    assert "d:base" in data
    out = bot.handle_callback(chat_id=7, data="d:base:budget:ege")
    assert "25 июля" in out.text


def test_menu_has_dates_button():
    out = bot.handle_message(chat_id=8, text="/abitur")
    data = [cb for row in out.keyboard for (_, cb) in row]
    assert "d:" in data


def test_shansy_command_asks_for_scores():
    out = bot.handle_message(chat_id=9, text="/shansy")
    assert bot.AWAITING_SCORES.get(9) is True
    assert "русский 78" in out.text


def test_shansy_scores_after_prompt(monkeypatch):
    monkeypatch.setattr(bot, "_shansy_answer", lambda t: f"MATCHES for {t}")
    bot.handle_message(chat_id=10, text="/shansy")
    out = bot.handle_message(chat_id=10, text="русский 78, история 90")
    assert "MATCHES for" in out.text
    assert 10 not in bot.AWAITING_SCORES


def test_volunteer_hours_beat_scores_state(monkeypatch):
    monkeypatch.setattr(bot, "_shansy_answer", lambda t: "SHOULD_NOT_APPEAR")
    bot.handle_message(chat_id=11, text="/bally")
    bot.handle_callback(chat_id=11, data="c:level:base")
    bot.handle_callback(chat_id=11, data="c:pedagogical:1")
    bot.handle_callback(chat_id=11, data="c:target:0")
    bot.AWAITING_SCORES[11] = True
    out = bot.handle_message(chat_id=11, text="200")
    assert bot.SESSIONS[11].volunteer_hours == 200
    assert "SHOULD_NOT_APPEAR" not in out.text


def test_vybor_starts_consultation_with_history():
    import scraper.telegram_bot as bot
    bot.HISTORY.clear()
    out = bot.handle_message(chat_id=55, text="/vybor")
    assert "подбер" in out.text.lower()
    assert bot.HISTORY[55][0]["role"] == "assistant"


def test_free_answer_keeps_rolling_history(monkeypatch):
    import scraper.telegram_bot as bot
    bot.HISTORY.clear()
    calls = []
    def fake_answer(q, history=None, **kw):
        calls.append(list(history or []))
        return f"ответ на {q}"
    monkeypatch.setattr(bot.llm, "answer", fake_answer)
    bot.handle_message(chat_id=56, text="хочу учить детей языкам")
    bot.handle_message(chat_id=56, text="а какие экзамены?")
    # второй вызов видит первый обмен
    assert any("хочу учить детей языкам" in m.get("content", "") for m in calls[1])
    # история ограничена
    for i in range(10):
        bot.handle_message(chat_id=56, text=f"вопрос {i}")
    assert len(bot.HISTORY[56]) <= bot._HISTORY_MAX


def test_llm_error_not_saved_to_history(monkeypatch):
    import scraper.telegram_bot as bot
    bot.HISTORY.clear()
    monkeypatch.setattr(bot.llm, "answer",
                        lambda q, history=None, **kw: "Не удалось ответить автоматически. X")
    bot.handle_message(chat_id=57, text="вопрос")
    assert 57 not in bot.HISTORY or bot.HISTORY[57] == []


def test_menu_button_on_every_reply_and_escape():
    bot.AWAITING_CODE.clear(); bot.AWAITING_SCORES.clear()
    # у обычного ответа есть кнопка возврата в меню
    out = bot.handle_message(chat_id=91, text="/spisok")
    data = [cb for row in out.keyboard for (_, cb) in row]
    assert "open:menu" in data
    assert bot.AWAITING_CODE.get(91) is True
    # нажатие «Меню» выходит из режима ожидания кода
    out2 = bot.handle_callback(chat_id=91, data="open:menu")
    assert 91 not in bot.AWAITING_CODE
    d2 = [cb for row in out2.keyboard for (_, cb) in row]
    assert "open:calc" in d2          # это само меню
    assert "open:menu" not in d2      # в меню кнопки «Меню» нет


def test_start_menu_has_no_menu_button():
    out = bot.handle_message(chat_id=92, text="/start")
    data = [cb for row in out.keyboard for (_, cb) in row]
    assert "open:menu" not in data


def test_split_text_short_is_single_chunk():
    assert bot._split_text("привет") == ["привет"]


def test_split_text_respects_limit_on_line_boundaries():
    text = "\n".join(f"строка номер {i} с текстом" for i in range(400))
    chunks = bot._split_text(text, limit=1000)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
    # склейка обратно даёт исходный текст (границы — переносы строк)
    assert "\n".join(chunks) == text


def test_split_text_hard_splits_overlong_line():
    chunks = bot._split_text("x" * 5000, limit=1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks) == "x" * 5000


def test_long_shansy_answer_sends_multiple_chunks(monkeypatch):
    # реальный баг: ответ >4096 → Telegram 400. Теперь режется на части.
    sent = []
    monkeypatch.setattr(bot, "_api",
                        lambda token, method, **p: sent.append(p) or {"ok": True})
    big = bot.Reply("\n".join(f"строка {i}" for i in range(2000)),
                    [[("🏠 Меню", "open:menu")]])
    bot._send("tok", 1, big)
    assert len(sent) >= 2                          # разбилось на несколько сообщений
    assert all(len(p["text"]) <= 4000 for p in sent)
    # клавиатура только на последней части
    assert "reply_markup" in sent[-1]
    assert not any("reply_markup" in p for p in sent[:-1])


def test_plan_command_prompts_and_awaits():
    bot.AWAITING_PLAN.clear()
    r = bot._handle_message(500, "/plan")
    assert "направление" in r.text.lower()
    assert bot.AWAITING_PLAN.get(500)


def test_plan_search_returns_candidate_buttons():
    r = bot._handle_message(501, "/plan начальное образование")
    assert r.document is None
    assert len(r.keyboard) >= 2
    assert all(cb.startswith("plan:") for row in r.keyboard for _, cb in row)


def test_plan_unknown_query_graceful():
    r = bot._handle_message(502, "/plan абырвалг несуществующее")
    assert "не нашёл" in r.text.lower()
    assert r.document is None


def test_plan_send_missing_share_id_is_graceful():
    r = bot._handle_callback(503, "plan:ZZZnotreal")
    assert r.document is None
    assert "не удалось" in r.text.lower() or "меню" in r.text.lower()


def test_content_type_by_extension():
    assert bot._content_type("plan.pdf") == "application/pdf"
    assert bot._content_type("feedback.csv") == "text/csv"


def test_plan_pick_shows_chooser_menu(monkeypatch):
    from scraper.abitur import study_plans as SP
    monkeypatch.setattr(SP, "_PLANS", [
        {"code": "44.03.01", "form": "очная", "profile": "История",
         "level": "базовое высшее образование", "year": "2026",
         "plan": "https://oc.mpgu.su/s/SID1"}])
    monkeypatch.setattr(SP, "_SEMS", {"SID1": [
        {"index": "Б1.О.01.01", "name": "История России", "semesters": [1, 2]}]})
    r = bot._handle_callback(600, "plan:SID1")
    labels = [b[0][0] for b in r.keyboard]
    assert any("Скачать план" in x for x in labels)
    assert any("семестрам" in x for x in labels)      # есть данные → есть кнопка


def test_plan_semesters_output(monkeypatch):
    from scraper.abitur import study_plans as SP
    monkeypatch.setattr(SP, "_SEMS", {"SID2": [
        {"index": "Б1.О.01.01", "name": "История России", "semesters": [1, 2]},
        {"index": "Б1.О.02.01", "name": "Зоология", "semesters": [2]}]})
    r = bot._handle_callback(601, "sem:SID2")
    assert "Семестр 1" in r.text and "История России" in r.text
    assert "Семестр 2" in r.text and "Зоология" in r.text


def test_plan_semesters_absent_offers_file(monkeypatch):
    from scraper.abitur import study_plans as SP
    monkeypatch.setattr(SP, "_SEMS", {})
    r = bot._handle_callback(602, "sem:NOPE")
    assert "недоступна" in r.text.lower()
    assert any("Скачать план" in b[0][0] for b in r.keyboard)


def test_bare_code_triggers_lookup(monkeypatch):
    # треть сообщений в выгрузке — просто код; раньше он уходил в ИИ,
    # тот отвечал «воспользуйтесь /spisok», и человек слал код снова
    called = {}

    def fake_lookup(code, detailed=False):
        called["code"] = code
        return bot.Reply("позиции", [])

    monkeypatch.setattr(bot, "_lookup_code", fake_lookup)
    bot.handle_message(910, "1199043")
    assert called["code"] == "1199043"
    called.clear()
    bot.handle_message(910, " 954894 ")          # с пробелами
    assert called["code"] == "954894"


def test_long_number_hints_not_a_code(monkeypatch):
    monkeypatch.setattr(bot, "_answer_free", lambda cid, q: "ИИ")
    r = bot.handle_message(911, "7561783051")     # это Telegram ID, не код
    assert "уникальный код" in r.text and "ИИ" not in r.text


def test_short_number_still_goes_to_llm(monkeypatch):
    monkeypatch.setattr(bot, "_answer_free", lambda cid, q: "ИИ-ответ")
    assert "ИИ-ответ" in bot.handle_message(912, "169").text


def test_bare_code_does_not_break_calc_session():
    # во время калькулятора цифры — это часы волонтёрства, не код
    bot.handle_message(913, "/bally")
    bot.handle_callback(913, "c:level:base")
    bot.handle_callback(913, "c:pedagogical:1")
    bot.handle_callback(913, "c:target:0")
    bot.handle_message(913, "200")
    assert bot.SESSIONS[913].volunteer_hours == 200


def test_broadcast_silent_for_non_admin():
    r = bot.handle_message(chat_id=999999, text="/broadcast привет всем")
    assert r.text == "" and r.keyboard == []


def test_broadcast_shows_usage_without_text(monkeypatch):
    monkeypatch.setattr(bot, "ADMIN_CHAT_ID", 42)
    monkeypatch.setattr(bot, "SUBS", {"1": {}, "2": {}})
    r = bot.handle_message(chat_id=42, text="/broadcast")
    assert "Использование" in r.text and "2" in r.text


def test_broadcast_sends_to_all_subscribers(monkeypatch):
    monkeypatch.setattr(bot, "ADMIN_CHAT_ID", 42)
    monkeypatch.setattr(bot, "SUBS", {"111": {}, "222": {}, "333": {}})
    monkeypatch.setattr(bot.os.environ, "get", lambda k, d=None: "tok" if k == "BOT_TOKEN" else d)
    sent = []
    monkeypatch.setattr(bot, "_send", lambda token, chat, reply: sent.append((chat, reply.text)))
    r = bot.handle_message(chat_id=42, text="/broadcast баг починили, всё ок")
    assert sorted(c for c, _ in sent) == [111, 222, 333]
    assert all(t == "баг починили, всё ок" for _, t in sent)
    assert "3 успешно" in r.text


def test_broadcast_counts_failures_and_continues(monkeypatch):
    monkeypatch.setattr(bot, "ADMIN_CHAT_ID", 42)
    monkeypatch.setattr(bot, "SUBS", {"111": {}, "222": {}})
    monkeypatch.setattr(bot.os.environ, "get", lambda k, d=None: "tok" if k == "BOT_TOKEN" else d)
    def fake_send(token, chat, reply):
        if chat == 111:
            raise RuntimeError("boom")
    monkeypatch.setattr(bot, "_send", fake_send)
    r = bot.handle_message(chat_id=42, text="/broadcast текст")
    assert "1 успешно, 1 с ошибкой" in r.text
