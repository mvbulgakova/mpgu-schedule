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
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from scraper.abitur import dialog, faq, follow, llm, lists, shansy

RUN_SECONDS = int(os.environ.get("RUN_SECONDS", "3300"))
MAX_MSG_LEN = 1000
# Файл подписок «следи за кодом» (переживает рестарты через actions/cache).
SUBS_PATH = os.environ.get("SUBS_PATH", "")
SUBS_CHECK_SECONDS = 600

# In-memory состояние калькулятора по chat_id (эфемерно, теряется при рестарте).
SESSIONS: Dict[int, dialog.CalcSession] = {}
# Ожидание уникального кода после /spisok (отдельно от калькулятора).
AWAITING_CODE: Dict[int, bool] = {}
# Ожидание сообщения с баллами ЕГЭ после /shansy.
AWAITING_SCORES: Dict[int, bool] = {}
# Подписки: chat_id(str) -> {"code", "last": {list: pos}, "updated_at"}.
SUBS: Dict[str, dict] = {}
# Память свободного диалога (консультация по выбору): chat_id -> реплики.
HISTORY: Dict[int, List[dict]] = {}
_HISTORY_MAX = 8  # последних реплик (4 обмена)


@dataclass
class Reply:
    text: str
    keyboard: List[List[Tuple[str, str]]] = field(default_factory=list)
    is_menu: bool = False   # сам экран меню — к нему кнопку «Меню» не добавляем


_MENU_ROW = [("🏠 Меню", "open:menu")]


def _finalize(r: Reply) -> Reply:
    """Дописывает кнопку возврата в меню ко всем ответам, кроме самого меню."""
    if r.is_menu:
        return r
    return Reply(r.text, list(r.keyboard) + [_MENU_ROW], r.is_menu)


def _menu_keyboard() -> List[List[Tuple[str, str]]]:
    rows, row = [[("📅 Сроки поступления", "d:")]], []
    for tid, (label, _) in faq.TOPICS.items():
        row.append((label, f"t:{tid}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([("🧭 Помочь выбрать направление", "open:vybor")])
    rows.append([("➕ Калькулятор баллов", "open:calc")])
    rows.append([("🧮 Подбор по ЕГЭ", "open:shansy"), ("🔎 Мои списки", "open:spisok")])
    return rows


_GREETING = ("👋 Я помощник абитуриента МПГУ.\n\n"
             "Спросите про поступление или выберите тему ниже.\n"
             "• /spisok — позиция в конкурсных списках, 🔔 можно следить за изменениями\n"
             "• /shansy — подбор программ по вашим баллам ЕГЭ\n"
             "• /bally — калькулятор дополнительных баллов\n"
             "• /sroki — сроки и ближайшие дедлайны")


def _answer_free(chat_id: int, question: str) -> str:
    hist = HISTORY.get(chat_id, [])
    ans = llm.answer(question, history=hist)
    if not ans.startswith("Не удалось ответить"):
        hist = hist + [{"role": "user", "content": question},
                       {"role": "assistant", "content": ans}]
        HISTORY[chat_id] = hist[-_HISTORY_MAX:]
    return ans


_VYBOR_START = (
    "🧭 <b>Давайте подберём направление!</b> Расскажите о себе одним сообщением:\n"
    "1️⃣ какие предметы ЕГЭ сдаёте (или уже сдали) и что из школьного нравится;\n"
    "2️⃣ с кем хотите работать: малыши, школьники, подростки, взрослые — или вообще "
    "не с людьми;\n"
    "3️⃣ что вам интересно: языки, IT, наука, спорт, искусство, психология, история…\n"
    "4️⃣ кем видите себя после вуза (если пока не знаете — так и напишите).\n\n"
    "Я предложу подходящие направления МПГУ, а точные шансы посчитаем через /shansy.")


_SHANSY_PROMPT = ("Пришлите ваши предметы ЕГЭ и баллы одним сообщением, например:\n"
                  "<b>русский 78, обществознание 84, история 90</b>\n"
                  "(математика учитывается только ПРОФИЛЬНАЯ — базовая для конкурса "
                  "не подходит)")


def _shansy_answer(text: str) -> str:
    return shansy.answer(text, lists_meta=lists.fetch_meta(),
                         history=shansy.fetch_history())


def _lookup_code(code: str) -> Reply:
    meta = lists.fetch_meta()
    if meta is None:  # реально недоступен индекс, а не просто редкий код
        return Reply("Индекс списков сейчас недоступен. Официальные списки: "
                     "https://epk25.mpgu.su/competitive-list", [])
    # shard может быть None, если кодов с таким префиксом нет — это «не найден»
    shard = lists.fetch_shard(code)
    text = lists.format_positions(meta, shard, code)
    kb: List[List[Tuple[str, str]]] = []
    if lists.lookup(shard, code):
        kb = [[("🔔 Следить за этим кодом", f"f:{lists._norm(code)}")]]
    return Reply(text, kb)


def _save_subs():
    if SUBS_PATH:
        follow.save(SUBS_PATH, SUBS)


def _follow_code(chat_id: int, code: str) -> Reply:
    meta = lists.fetch_meta()
    shard = lists.fetch_shard(code)
    entries = lists.lookup(shard, code)
    if not entries:
        return Reply("Код не найден в списках — подписка не оформлена. "
                     "Проверьте номер через /spisok.", [])
    SUBS[str(chat_id)] = {"code": lists._norm(code),
                          "last": follow.positions_of(entries),
                          "updated_at": (meta or {}).get("updated_at", "")}
    _save_subs()
    return Reply(f"🔔 Слежу за кодом <b>{lists._norm(code)}</b>. Пришлю сообщение, когда "
                 "ваши позиции в списках изменятся (проверяю несколько раз в час; "
                 "в начале каждого часа возможна пауза ~5 минут). Отписаться: /unfollow", [])


def _unfollow(chat_id: int) -> Reply:
    if SUBS.pop(str(chat_id), None) is not None:
        _save_subs()
        return Reply("🔕 Подписка отключена.", [])
    return Reply("Активной подписки нет. Оформить: /spisok → кнопка «Следить».", [])


def handle_message(chat_id: int, text: str) -> Reply:
    return _finalize(_handle_message(chat_id, text))


def _handle_message(chat_id: int, text: str) -> Reply:
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
        return _lookup_code(text)

    # 3) ожидаем баллы ЕГЭ после /shansy
    if AWAITING_SCORES.get(chat_id) and any(ch.isdigit() for ch in text) and not text.startswith("/"):
        AWAITING_SCORES.pop(chat_id, None)
        return Reply(_shansy_answer(text), [])

    intent, payload = faq.route(text)
    if intent in ("start", "help"):
        return Reply(_GREETING, _menu_keyboard(), is_menu=True)
    if intent == "menu":
        return Reply("Выберите тему:", _menu_keyboard(), is_menu=True)
    if intent == "calc":
        s = dialog.start()
        SESSIONS[chat_id] = s
        v = dialog.render(s)
        return Reply(v.text, v.keyboard)
    if intent == "spisok":
        if payload:  # /spisok 12345
            return _lookup_code(payload)
        AWAITING_CODE[chat_id] = True
        return Reply("Пришлите ваш <b>уникальный код</b> (номер заявления) одним сообщением.", [])
    if intent == "dates":
        text_d, kb = faq.dates_step("")
        return Reply(text_d, kb)
    if intent == "shansy":
        if payload:  # /shansy русский 78 ...
            return Reply(_shansy_answer(payload), [])
        AWAITING_SCORES[chat_id] = True
        return Reply(_SHANSY_PROMPT, [])
    if intent == "follow":
        if payload:
            return _follow_code(chat_id, payload)
        return Reply("Пришлите команду с кодом: <b>/follow 1234567</b> — или найдите свой "
                     "код через /spisok и нажмите «🔔 Следить».", [])
    if intent == "unfollow":
        return _unfollow(chat_id)
    if intent == "vybor":
        HISTORY[chat_id] = [{"role": "assistant", "content": _VYBOR_START}]
        return Reply(_VYBOR_START, [])
    # свободный вопрос — логируем обрезанно и без длинных цифр (коды/телефоны),
    # чтобы по логам закрывать пробелы базы знаний
    print(f"Q: {re.sub(r'[0-9]{5,}', '<код>', payload)[:120]}", flush=True)
    return Reply(_answer_free(chat_id, payload), [])


def handle_callback(chat_id: int, data: str) -> Reply:
    return _finalize(_handle_callback(chat_id, data))


def _handle_callback(chat_id: int, data: str) -> Reply:
    if data == "open:menu":
        # выход из любых режимов ожидания — «спасательная» кнопка
        AWAITING_CODE.pop(chat_id, None)
        AWAITING_SCORES.pop(chat_id, None)
        return Reply("Выберите тему:", _menu_keyboard(), is_menu=True)
    if data.startswith("d:"):
        text_d, kb = faq.dates_step(data[2:])
        return Reply(text_d, kb)
    if data.startswith("f:"):
        arg = data[2:]
        if arg == "off":
            return _unfollow(chat_id)
        return _follow_code(chat_id, arg)
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
    if data == "open:vybor":
        HISTORY[chat_id] = [{"role": "assistant", "content": _VYBOR_START}]
        return Reply(_VYBOR_START, [])
    if data == "open:shansy":
        AWAITING_SCORES[chat_id] = True
        return Reply(_SHANSY_PROMPT, [])
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


def _check_subs(token: str):
    """Сверяет позиции подписчиков со свежими данными; шлёт диффы."""
    if not SUBS:
        return
    meta = lists.fetch_meta(force=True)
    if not meta:
        return
    upd = meta.get("updated_at", "")
    changed = False
    for chat, sub in list(SUBS.items()):
        if sub.get("updated_at") == upd:
            continue  # данные не менялись с прошлой сверки этого подписчика
        shard = lists.fetch_shard(sub["code"])
        if shard is None:
            continue  # сеть/CDN моргнули — попробуем в следующий проход
        entries = lists.lookup(shard, sub["code"])
        txt = follow.diff_text(sub["code"], sub.get("last") or {}, entries, meta)
        sub["last"] = follow.positions_of(entries)
        sub["updated_at"] = upd
        changed = True
        if txt:
            try:
                _send(token, int(chat), Reply(txt, []))
            except Exception as e:
                print(f"notify error {chat}: {e}")
    if changed:
        _save_subs()


# Оформление бота: команды и описания регистрируются самим ботом при старте
# (Bot API setMyCommands/setMyDescription) — BotFather не нужен, кроме аватарки.
_BOT_COMMANDS = [
    {"command": "start", "description": "главное меню"},
    {"command": "spisok", "description": "моя позиция: прохожу ли я и на что"},
    {"command": "follow", "description": "следить за изменением позиции"},
    {"command": "unfollow", "description": "отключить слежение"},
    {"command": "shansy", "description": "подбор программ по баллам ЕГЭ"},
    {"command": "vybor", "description": "консультация по выбору направления"},
    {"command": "bally", "description": "калькулятор доп. баллов"},
    {"command": "sroki", "description": "сроки и ближайшие дедлайны"},
    {"command": "help", "description": "помощь"},
]
_BOT_DESCRIPTION = (
    "Помогаю поступающим в МПГУ:\n"
    "🔎 /spisok — позиция в списках: прохожу ли я и на что\n"
    "🔔 слежение — сообщу, когда позиция изменится\n"
    "🧮 /shansy — подбор программ по баллам ЕГЭ\n"
    "🧭 /vybor — консультация по выбору направления\n"
    "➕ /bally — калькулятор доп. баллов\n"
    "📅 /sroki — дедлайны кампании 2026\n"
    "И отвечаю на свободные вопросы по Правилам приёма.")
_BOT_SHORT_DESCRIPTION = ("Помощник абитуриента МПГУ: списки и «прохожу ли я», "
                          "подбор по ЕГЭ, доп. баллы, сроки-2026.")


def _setup_profile(token: str):
    """Идемпотентная регистрация команд и описаний (раз в запуск, ~раз в час)."""
    try:
        _api(token, "setMyCommands", commands=json.dumps(_BOT_COMMANDS))
        _api(token, "setMyDescription", description=_BOT_DESCRIPTION)
        _api(token, "setMyShortDescription",
             short_description=_BOT_SHORT_DESCRIPTION)
        print("Профиль бота обновлён (команды/описания)")
    except Exception as e:
        print(f"setup profile error (не критично): {e}")


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
    try:
        _api(token, "sendMessage", **params)
    except Exception:
        # Telegram отверг HTML-разметку (нередко в свободном AI-ответе) —
        # лучше доставить без форматирования, чем не доставить вовсе.
        params.pop("parse_mode", None)
        _api(token, "sendMessage", **params)


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        print(handle_message(0, sys.argv[2]).text)
        return 0
    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN не задан — пропускаю. Выход.")
        return 0
    # Гарантируем доставку через getUpdates: снимаем возможный вебхук от старого
    # бота расписания (webhook и long-polling на одном токене несовместимы — иначе
    # getUpdates отдаёт 409 Conflict и бот молчит). drop_pending_updates не ставим,
    # чтобы не потерять сообщения, накопившиеся между запусками воркфлоу.
    try:
        info = _api(token, "deleteWebhook")
        print(f"deleteWebhook: {info.get('ok')}")
    except Exception as e:
        print(f"deleteWebhook error (продолжаю): {e}")
    _setup_profile(token)
    if SUBS_PATH:
        SUBS.update(follow.load(SUBS_PATH))
        print(f"Подписок загружено: {len(SUBS)}")
    deadline = time.time() + RUN_SECONDS
    offset = None
    last_subs_check = 0.0
    print(f"Бот запущен на {RUN_SECONDS}s")
    while time.time() < deadline:
        if time.time() - last_subs_check > SUBS_CHECK_SECONDS:
            last_subs_check = time.time()
            try:
                _check_subs(token)
            except Exception as e:
                print(f"subs check error: {e}")
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
