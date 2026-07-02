"""Telegram-бот абитуриента МПГУ на long-polling (GitHub Actions).

Без хостинга/вебхуков: воркфлоу периодически запускает скрипт, он опрашивает getUpdates
~55 минут и отвечает почти мгновенно, затем выходит; крон перезапускает.
Нужны секреты: BOT_TOKEN (Telegram) и ANTHROPIC_API_KEY (для AI-ответов; без него
кнопки и калькулятор работают, AI-ветка деградирует).

Локальный прогон логики (без Telegram):
    python -m scraper.telegram_bot --selftest "/bally"
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from scraper.abitur import dialog, faq, llm, lists

RUN_SECONDS = int(os.environ.get("RUN_SECONDS", "3300"))
MAX_MSG_LEN = 1000

# In-memory состояние калькулятора по chat_id (эфемерно, теряется при рестарте).
SESSIONS: Dict[int, dialog.CalcSession] = {}
# Ожидание уникального кода после /spisok (отдельно от калькулятора).
AWAITING_CODE: Dict[int, bool] = {}


@dataclass
class Reply:
    text: str
    keyboard: List[List[Tuple[str, str]]] = field(default_factory=list)


def _menu_keyboard() -> List[List[Tuple[str, str]]]:
    rows, row = [[("📅 Сроки поступления", "d:")]], []
    for tid, (label, _) in faq.TOPICS.items():
        row.append((label, f"t:{tid}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([("➕ Калькулятор баллов", "open:calc")])
    rows.append([("🔎 Мои списки", "open:spisok")])
    return rows


_GREETING = ("👋 Я помощник абитуриента МПГУ.\n\n"
             "Спросите про поступление или выберите тему ниже. "
             "Команда /bally — калькулятор дополнительных баллов.")


def _answer_free(question: str) -> str:
    return llm.answer(question)


def _lookup_code(code: str) -> str:
    index = lists.fetch_index()
    if not index:
        return ("Индекс списков сейчас недоступен. Официальные списки: "
                "https://epk25.mpgu.su/competitive-list")
    return lists.format_positions(index, code)


def handle_message(chat_id: int, text: str) -> Reply:
    text = (text or "")[:MAX_MSG_LEN].strip()
    # 1) ввод часов волонтёрства во время калькулятора — высший приоритет для числа
    sess = SESSIONS.get(chat_id)
    if sess is not None and sess.step == dialog.STEP_ACHIEVE and text.isdigit():
        dialog.set_volunteer_hours(sess, int(text))
        v = dialog.render(sess)
        return Reply(f"Часы волонтёрства: {sess.volunteer_hours}.\n\n{v.text}", v.keyboard)

    # 2) ожидаем уникальный код после /spisok
    if AWAITING_CODE.get(chat_id) and any(ch.isdigit() for ch in text) and not text.startswith("/"):
        AWAITING_CODE.pop(chat_id, None)
        return Reply(_lookup_code(text), [])

    intent, payload = faq.route(text)
    if intent in ("start", "help"):
        return Reply(_GREETING, _menu_keyboard())
    if intent == "menu":
        return Reply("Выберите тему:", _menu_keyboard())
    if intent == "calc":
        s = dialog.start()
        SESSIONS[chat_id] = s
        v = dialog.render(s)
        return Reply(v.text, v.keyboard)
    if intent == "spisok":
        if payload:  # /spisok 12345
            return Reply(_lookup_code(payload), [])
        AWAITING_CODE[chat_id] = True
        return Reply("Пришлите ваш <b>уникальный код</b> (номер заявления) одним сообщением.", [])
    if intent == "dates":
        text_d, kb = faq.dates_step("")
        return Reply(text_d, kb)
    # свободный вопрос
    return Reply(_answer_free(payload), [])


def handle_callback(chat_id: int, data: str) -> Reply:
    if data.startswith("d:"):
        text_d, kb = faq.dates_step(data[2:])
        return Reply(text_d, kb)
    if data.startswith("t:"):
        ans = faq.topic_answer(data[2:])
        return Reply(ans or "Тема не найдена.", [])
    if data == "open:calc":
        s = dialog.start()
        SESSIONS[chat_id] = s
        v = dialog.render(s)
        return Reply(v.text, v.keyboard)
    if data == "open:spisok":
        AWAITING_CODE[chat_id] = True
        return Reply("Пришлите ваш <b>уникальный код</b> (номер заявления) одним сообщением.", [])
    if data.startswith("c:"):
        s = SESSIONS.get(chat_id) or dialog.start()
        SESSIONS[chat_id] = s
        s, done = dialog.handle(s, data)
        if done:
            result = dialog.compute(s)
            SESSIONS.pop(chat_id, None)
            return Reply(dialog.result_text(result), [])
        v = dialog.render(s)
        return Reply(v.text, v.keyboard)
    return Reply("Неизвестная команда.", [])


# ── Telegram I/O ──────────────────────────────────────────────────────────────

def _api(token: str, method: str, **params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _markup(keyboard: List[List[Tuple[str, str]]]) -> Optional[str]:
    if not keyboard:
        return None
    return json.dumps({"inline_keyboard": [
        [{"text": t, "callback_data": cb} for (t, cb) in row] for row in keyboard]})


def _send(token: str, chat_id: int, reply: Reply):
    params = {"chat_id": chat_id, "text": reply.text, "parse_mode": "HTML",
              "disable_web_page_preview": "true"}
    mk = _markup(reply.keyboard)
    if mk:
        params["reply_markup"] = mk
    _api(token, "sendMessage", **params)


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        print(handle_message(0, sys.argv[2]).text)
        return 0
    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN не задан — пропускаю. Выход.")
        return 0
    deadline = time.time() + RUN_SECONDS
    offset = None
    print(f"Бот запущен на {RUN_SECONDS}s")
    while time.time() < deadline:
        try:
            resp = _api(token, "getUpdates", offset=offset or "", timeout=30,
                        allowed_updates='["message","callback_query"]')
        except Exception as e:
            print(f"getUpdates error: {e}"); time.sleep(3); continue
        for upd in resp.get("result", []):
            offset = upd["update_id"] + 1
            try:
                if "message" in upd:
                    msg = upd["message"]
                    chat = (msg.get("chat") or {}).get("id")
                    text = msg.get("text") or ""
                    if chat and text:
                        _send(token, chat, handle_message(chat, text))
                elif "callback_query" in upd:
                    cq = upd["callback_query"]
                    chat = (((cq.get("message") or {}).get("chat")) or {}).get("id")
                    data = cq.get("data") or ""
                    try:
                        _api(token, "answerCallbackQuery", callback_query_id=cq["id"])
                    except Exception:
                        pass
                    if chat and data:
                        _send(token, chat, handle_callback(chat, data))
            except Exception as e:
                print(f"handle error: {e}")
    print("Время вышло, выход")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
