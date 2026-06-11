"""Telegram-бот расписания МПГУ на long-polling (для запуска в GitHub Actions).

Без внешнего хостинга и вебхуков: воркфлоу периодически запускает этот скрипт,
он опрашивает getUpdates ~55 минут и отвечает почти мгновенно, затем выходит;
крон перезапускает. Нужен только секрет BOT_TOKEN.

Данные берёт с публичного CDN jsDelivr (data-ветка) — ничего деплоить не надо.

Локальный прогон логики (без Telegram):
    python -m scraper.telegram_bot --selftest ВОП40-ПФК2501
    python -m scraper.telegram_bot --selftest-adm programs
    python -m scraper.telegram_bot --selftest-adm calendar
    python -m scraper.telegram_bot --selftest-adm docs budget
    python -m scraper.telegram_bot --selftest-adm snils 12345678901
    python -m scraper.telegram_bot --selftest-adm qa "Какие документы нужны?"
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import datetime as dt
from typing import Any

DATA_BASE = os.environ.get(
    "DATA_BASE", "https://cdn.jsdelivr.net/gh/mvbulgakova/mpgu-schedule@data")
RUN_SECONDS = int(os.environ.get("RUN_SECONDS", "3300"))  # ~55 минут

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_RU = {"monday": "Понедельник", "tuesday": "Вторник", "wednesday": "Среда",
          "thursday": "Четверг", "friday": "Пятница", "saturday": "Суббота",
          "sunday": "Воскресенье"}
TYPE_RU = {"lecture": "ЛК", "practice": "ПЗ", "lab": "ЛР", "seminar": "СЕМ", "other": ""}
_HOMO = str.maketrans({
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У"})

# Состояние диалога: chat_id → {"mode": str|None, ...}
_STATE: dict[int, dict] = {}

# Кэш данных о приёмной кампании на время сессии
_ADM_CONTEXT_CACHE: str | None = None


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def search_key(s: str) -> str:
    return re.sub(r"[\s\-_]", "", s.strip().upper().translate(_HOMO))


def _get_json(path: str) -> Any:
    url = f"{DATA_BASE}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "MPGU-Schedule-Bot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _esc(s: Any) -> str:
    return (str("" if s is None else s)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _iso_week_even(d: dt.date) -> bool:
    return d.isocalendar()[1] % 2 == 0


def _make_keyboard(buttons: list[list[tuple[str, str]]]) -> str:
    """Возвращает JSON-строку inline keyboard для Telegram API."""
    return json.dumps({
        "inline_keyboard": [
            [{"text": t, "callback_data": d} for t, d in row]
            for row in buttons
        ]
    }, ensure_ascii=False)


MAIN_MENU_KB = _make_keyboard([
    [("🎓 Направления", "adm_programs"), ("📅 Сроки", "adm_calendar")],
    [("📋 Документы", "adm_docs"),       ("🔍 Найти себя", "adm_snils")],
    [("💬 Задать вопрос", "adm_qa")],
])

_DOCS_MENU_KB = _make_keyboard([
    [("Бюджет", "adm_docs_budget"), ("Платное", "adm_docs_contract")],
    [("Целевое", "adm_docs_target")],
    [("◀ Назад", "adm_main")],
])

_BACK_KB = _make_keyboard([[("◀ Главное меню", "adm_main")]])


# ---------------------------------------------------------------------------
# Расписание (существующая логика)
# ---------------------------------------------------------------------------

def _format_today(group: dict, meta: dict) -> str:
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=3)))  # Москва
    day = DAYS[now.weekday()]
    even = _iso_week_even(now.date())
    wk = "even_week" if even else "odd_week"
    lessons = ((group.get("schedule") or {}).get(wk) or {}).get(day) or []
    head = (f"📅 <b>{_esc(group.get('name') or meta['code'])}</b> · "
            f"{DAY_RU[day]} · {'чётная' if even else 'нечётная'} неделя")
    if not lessons:
        return f"{head}\n\nЗанятий нет 🎉"
    lessons = sorted(lessons, key=lambda l: l.get("time_start") or "")
    parts = []
    for l in lessons:
        t = f" ({TYPE_RU[l['type']]})" if TYPE_RU.get(l.get("type")) else ""
        tm = f"{l.get('time_start') or ''}{'–' + l['time_end'] if l.get('time_end') else ''}"
        extra = ", ".join(_esc(x) for x in (l.get("teacher"), l.get("room")) if x)
        parts.append(f"🕐 <b>{tm}</b> {_esc(l.get('subject') or '')}{t}"
                     + (f"\n   {extra}" if extra else ""))
    return head + "\n\n" + "\n\n".join(parts)


def _looks_like_group_code(text: str) -> bool:
    k = search_key(text)
    return bool(re.match(r"[А-ЯA-Z]{2,4}\d{2}", k))


def handle_schedule(text: str) -> str:
    """Поиск расписания по коду группы. Возвращает HTML-текст."""
    text = text.strip()
    q = search_key(re.sub(r"^/\S+\s*", "", text))
    if len(q) < 3:
        return "Пришлите код группы (минимум 3 символа), например ВОП40-ПФК2501."
    groups = (_get_json("meta/groups.json") or {}).get("groups", [])
    exact = [g for g in groups if g["key"] == q]
    matches = exact or [g for g in groups if q in g["key"]]
    if not matches:
        return f"Группа «{_esc(text)}» не найдена. Проверьте код."
    if len(matches) > 1 and len(exact) != 1:
        lst = "\n".join(f"• <b>{_esc(g['code'])}</b> — {_esc(g['institute_short'])}"
                        for g in matches[:12])
        more = f"\n…и ещё {len(matches) - 12}" if len(matches) > 12 else ""
        return f"Нашёл несколько групп — уточните код:\n{lst}{more}"
    g = matches[0]
    grp = _get_json(f"institutes/{g['institute']}/groups/"
                    f"{urllib.parse.quote(g['file'])}.json")
    return _format_today(grp, g)


# ---------------------------------------------------------------------------
# Данные о приёмной кампании
# ---------------------------------------------------------------------------

def _adm_json(path: str) -> Any:
    return _get_json(f"admissions/{path}")


def _build_llm_context() -> str:
    parts: list[str] = []
    try:
        cal = _adm_json("calendar.json")
        parts.append("КЛЮЧЕВЫЕ ДАТЫ ПРИЁМА:")
        for ev in (cal if isinstance(cal, list) else cal.get("events", [])):
            parts.append(f"  {ev.get('date', '')} — {ev.get('event') or ev.get('title', '')}")
    except Exception:
        pass
    try:
        docs = _adm_json("documents.json")
        parts.append("\nДОКУМЕНТЫ:")
        if isinstance(docs, dict):
            for key, items in docs.items():
                label = {"budget": "Бюджет", "contract": "Платное", "target": "Целевое"}.get(key, key)
                parts.append(f"  {label}: {'; '.join(str(i) for i in items[:5])}")
        elif isinstance(docs, list):
            for cat in docs[:3]:
                parts.append(f"  {cat.get('title','')}: {'; '.join(cat.get('documents',[][:4]))}")
    except Exception:
        pass
    try:
        programs = _adm_json("programs.json")
        plist = programs if isinstance(programs, list) else programs.get("programs", [])
        parts.append("\nНАПРАВЛЕНИЯ ПОДГОТОВКИ (выборка):")
        for p in plist[:25]:
            parts.append(
                f"  {p.get('code','?')} {p.get('name','?')} — "
                f"бюджет: {p.get('budget_seats','?')}, "
                f"стоимость: {p.get('tuition_cost') or p.get('cost_per_year','?')} руб/год, "
                f"ЕГЭ: {', '.join(p.get('ege_subjects') or p.get('exams',[]))}"
            )
    except Exception:
        pass
    return "\n".join(parts) if parts else "Данные о приёмной кампании временно недоступны."


# ---------------------------------------------------------------------------
# Обработчики абитуриентского раздела
# ---------------------------------------------------------------------------

def _send_programs(token: str | None, chat_id: int) -> dict:
    try:
        programs = _adm_json("programs.json")
        plist = programs if isinstance(programs, list) else programs.get("programs", [])
    except Exception:
        return {"text": "Данные о направлениях временно недоступны. Попробуйте позже.",
                "keyboard": _BACK_KB}

    if not plist:
        return {"text": "Список направлений пока не опубликован.", "keyboard": _BACK_KB}

    lines = ["🎓 <b>Направления подготовки МПГУ</b>\n"]
    for p in plist[:30]:
        seats = p.get("budget_seats")
        cost = p.get("tuition_cost") or p.get("cost_per_year")
        exams = ", ".join(p.get("ege_subjects") or p.get("exams", []))
        seat_str = f"бюджет: {seats} мест" if seats else ""
        cost_str = f"платное: {cost:,} р/год".replace(",", " ") if cost else ""
        meta = " | ".join(x for x in [seat_str, cost_str] if x)
        lines.append(f"<b>{_esc(p.get('code',''))} {_esc(p.get('name',''))}</b>"
                     + (f"\n   {_esc(meta)}" if meta else "")
                     + (f"\n   ЕГЭ: {_esc(exams)}" if exams else ""))

    if len(plist) > 30:
        lines.append(f"\n…и ещё {len(plist) - 30} направлений. Полный список: mpgu.su/abiturientam/")

    return {"text": "\n\n".join(lines), "keyboard": _BACK_KB}


def _send_calendar(token: str | None, chat_id: int) -> dict:
    try:
        cal = _adm_json("calendar.json")
        events = cal if isinstance(cal, list) else cal.get("events", [])
    except Exception:
        return {"text": "Даты приёмной кампании временно недоступны.", "keyboard": _BACK_KB}

    if not events:
        return {"text": "Календарь приёма пока не опубликован.", "keyboard": _BACK_KB}

    today = dt.date.today().isoformat()
    lines = ["📅 <b>Ключевые даты приёмной кампании МПГУ</b>\n"]
    for ev in events:
        d = ev.get("date", "")
        title = ev.get("event") or ev.get("title", "")
        desc = ev.get("description", "")
        marker = "✅" if d < today else ("⏳" if d == today else "📌")
        lines.append(f"{marker} <b>{_esc(d)}</b> — {_esc(title)}"
                     + (f"\n   {_esc(desc)}" if desc else ""))

    return {"text": "\n\n".join(lines), "keyboard": _BACK_KB}


def _send_documents(token: str | None, chat_id: int, category: str | None = None) -> dict:
    labels = {"budget": "Бюджет", "contract": "Платное обучение", "target": "Целевое обучение"}

    if category is None:
        return {
            "text": "📋 Выберите форму поступления для списка документов:",
            "keyboard": _DOCS_MENU_KB,
        }

    try:
        docs = _adm_json("documents.json")
    except Exception:
        return {"text": "Список документов временно недоступен.", "keyboard": _BACK_KB}

    if isinstance(docs, dict):
        items = docs.get(category, [])
    else:
        cat_map = {"budget": 0, "contract": 1, "target": 2}
        idx = cat_map.get(category, 0)
        items = (docs[idx].get("documents", []) if idx < len(docs) else [])

    if not items:
        return {"text": f"Документы для «{labels.get(category, category)}» не найдены.",
                "keyboard": _DOCS_MENU_KB}

    label = labels.get(category, category)
    lines = [f"📋 <b>Документы — {label}</b>\n"]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {_esc(item)}")

    return {"text": "\n".join(lines), "keyboard": _BACK_KB}


# ---------------------------------------------------------------------------
# Поиск по СНИЛС
# ---------------------------------------------------------------------------

_SNILS_RE = re.compile(r"(\d{3}[\s\-]?\d{3}[\s\-]?\d{3}[\s\-]?\d{2})")


def _snils_norm(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def search_by_snils(raw: str) -> dict:
    raw = raw.strip()
    m = _SNILS_RE.search(raw)
    if not m:
        return {"text": "Не распознал СНИЛС. Формат: 123-456-789 01 (11 цифр).",
                "keyboard": _BACK_KB}
    query = _snils_norm(m.group(1))
    if len(query) != 11:
        return {"text": "СНИЛС должен содержать 11 цифр.", "keyboard": _BACK_KB}

    # Загружаем индекс рейтинговых списков
    try:
        idx = _adm_json("ranked_lists/index.json")
        list_entries = idx.get("lists", []) if isinstance(idx, dict) else []
    except Exception:
        return {"text": "Рейтинговые списки ещё не опубликованы или временно недоступны.\n"
                        "Следите за обновлениями на mpgu.su/abiturientam/rating/",
                "keyboard": _BACK_KB}

    if not list_entries:
        return {"text": "Рейтинговые списки пока не опубликованы.",
                "keyboard": _BACK_KB}

    results: list[dict] = []
    for entry in list_entries:
        code = entry.get("code") or entry.get("file", "")
        if not code:
            continue
        try:
            rl = _adm_json(f"ranked_lists/{urllib.parse.quote(code)}.json")
            applicants = rl if isinstance(rl, list) else rl.get("applicants", [])
            budget_seats = (rl.get("budget_seats") if isinstance(rl, dict) else None) or 0
            direction_name = (rl.get("direction_name") if isinstance(rl, dict) else None) or code
        except Exception:
            continue
        for i, appl in enumerate(applicants, 1):
            snils_val = appl.get("snils", "")
            if _snils_norm(snils_val) == query:
                results.append({
                    "name": direction_name,
                    "rank": appl.get("rank", i),
                    "total": len(applicants),
                    "score": appl.get("score_total") or appl.get("score", "?"),
                    "budget_seats": budget_seats,
                    "status": appl.get("status", ""),
                })

    if not results:
        return {
            "text": "По данному СНИЛС ничего не найдено в опубликованных конкурсных списках.\n\n"
                    "Убедитесь, что правильно ввели номер (11 цифр без пробелов: 12345678901).",
            "keyboard": _BACK_KB,
        }

    lines = ["🔍 <b>Ваши позиции в конкурсных списках:</b>\n"]
    for r in results:
        within = r["rank"] <= r["budget_seats"] if r["budget_seats"] else None
        status_icon = "✅" if within else ("⚠️" if within is False else "📊")
        budget_note = (f"в пределах {r['budget_seats']} бюджетных мест" if within
                       else (f"за чертой ({r['budget_seats']} мест)" if within is False
                             else ""))
        lines.append(
            f"{status_icon} <b>{_esc(r['name'])}</b>\n"
            f"   Место: <b>{r['rank']}</b> из {r['total']}"
            + (f" ({budget_note})" if budget_note else "")
            + f"\n   Баллы: {r['score']}"
            + (f"\n   Статус: {_esc(r['status'])}" if r.get("status") else "")
        )

    return {"text": "\n\n".join(lines), "keyboard": _BACK_KB}


# ---------------------------------------------------------------------------
# LLM Q&A
# ---------------------------------------------------------------------------

_LLM_SYSTEM = (
    "Ты — помощник абитуриента МПГУ (Московский педагогический государственный университет). "
    "Отвечай ТОЛЬКО по данным, предоставленным в сообщении пользователя (раздел ДАННЫЕ О ПРИЁМЕ). "
    "Если информации в данных нет — так и скажи, не выдумывай. "
    "Отвечай по-русски, кратко и конкретно. "
    "Форматируй для Telegram: <b>жирный</b> для важного. "
    "Максимум 350 слов."
)


def ask_llm(question: str) -> dict:
    global _ADM_CONTEXT_CACHE
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"text": "LLM-режим недоступен (нет ключа ANTHROPIC_API_KEY).",
                "keyboard": _BACK_KB}

    if _ADM_CONTEXT_CACHE is None:
        _ADM_CONTEXT_CACHE = _build_llm_context()

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=_LLM_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"ДАННЫЕ О ПРИЁМЕ:\n{_ADM_CONTEXT_CACHE}\n\nВОПРОС АБИТУРИЕНТА: {question}"
            }],
        )
        answer = resp.content[0].text.strip()[:3800]
    except Exception as e:
        answer = f"Не удалось получить ответ: {e}"

    qa_kb = _make_keyboard([
        [("💬 Ещё вопрос", "adm_qa"), ("◀ Главное меню", "adm_main")]
    ])
    return {"text": answer, "keyboard": qa_kb}


# ---------------------------------------------------------------------------
# Роутер callback-запросов
# ---------------------------------------------------------------------------

def handle_callback(data: str, chat_id: int) -> dict:
    if data == "adm_main":
        return {"text": "Главное меню абитуриента:", "keyboard": MAIN_MENU_KB}
    if data == "adm_programs":
        return _send_programs(None, chat_id)
    if data == "adm_calendar":
        return _send_calendar(None, chat_id)
    if data == "adm_docs":
        return _send_documents(None, chat_id, category=None)
    if data == "adm_docs_budget":
        return _send_documents(None, chat_id, category="budget")
    if data == "adm_docs_contract":
        return _send_documents(None, chat_id, category="contract")
    if data == "adm_docs_target":
        return _send_documents(None, chat_id, category="target")
    if data == "adm_snils":
        _STATE[chat_id] = {"mode": "snils_wait"}
        return {"text": "🔍 Введите ваш СНИЛС для поиска в конкурсных списках.\n\n"
                        "Формат: <code>123-456-789 01</code> или <code>12345678901</code>",
                "keyboard": _BACK_KB}
    if data == "adm_qa":
        _STATE[chat_id] = {"mode": "qa_wait"}
        return {"text": "💬 Задайте любой вопрос о поступлении в МПГУ — "
                        "расскажу про документы, сроки, направления и баллы.",
                "keyboard": _BACK_KB}
    return {"text": "Неизвестная команда.", "keyboard": MAIN_MENU_KB}


# ---------------------------------------------------------------------------
# Роутер текстовых сообщений
# ---------------------------------------------------------------------------

def handle(text: str, chat_id: int = 0) -> dict:
    """Основной диспетчер текстовых сообщений. Возвращает dict с text и keyboard."""
    text = text.strip()

    # /start и /help
    if re.match(r"/start|/help", text, re.I):
        return {
            "text": (
                "👋 <b>Привет! Я бот МПГУ.</b>\n\n"
                "📚 <b>Расписание</b> — введите код группы, например <code>ВОП40-ПФК2501</code>\n\n"
                "🎓 <b>Абитуриентам</b> — кнопки ниже:"
            ),
            "keyboard": MAIN_MENU_KB,
        }

    # Абитуриентские команды
    if re.match(r"/abiturient|/абитуриент", text, re.I):
        return {"text": "Раздел абитуриента МПГУ:", "keyboard": MAIN_MENU_KB}

    # Состояние: ожидание СНИЛС
    state = _STATE.get(chat_id, {})
    if state.get("mode") == "snils_wait":
        _STATE.pop(chat_id, None)
        return search_by_snils(text)

    # Состояние: режим Q&A
    if state.get("mode") == "qa_wait":
        _STATE.pop(chat_id, None)
        return ask_llm(text)

    # Код группы → расписание
    if _looks_like_group_code(text) or re.match(r"^/", text):
        schedule_text = handle_schedule(text)
        return {"text": schedule_text, "keyboard": None}

    # Прочий текст → попытка найти группу
    q = search_key(text)
    if len(q) >= 3:
        schedule_text = handle_schedule(text)
        return {"text": schedule_text, "keyboard": None}

    return {
        "text": "Пришлите код группы для расписания или воспользуйтесь меню абитуриента:",
        "keyboard": MAIN_MENU_KB,
    }


# ---------------------------------------------------------------------------
# Telegram API
# ---------------------------------------------------------------------------

def _api(token: str, method: str, **params):
    data = urllib.parse.urlencode(
        {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
         for k, v in params.items() if v is not None}
    ).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _send(token: str, chat_id: int, reply: dict) -> None:
    text = reply.get("text", "")
    keyboard = reply.get("keyboard")
    try:
        _api(token, "sendMessage",
             chat_id=chat_id,
             text=text,
             parse_mode="HTML",
             disable_web_page_preview="true",
             reply_markup=keyboard)
    except Exception as e:
        print(f"sendMessage error: {e}")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> int:
    # Selftest для расписания (существующий)
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        result = handle(sys.argv[2], chat_id=0)
        print(result["text"])
        return 0

    # Selftest для абитуриентского раздела
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest-adm":
        cmd = sys.argv[2]
        arg = sys.argv[3] if len(sys.argv) > 3 else ""
        if cmd == "programs":
            r = _send_programs(None, 0)
        elif cmd == "calendar":
            r = _send_calendar(None, 0)
        elif cmd == "docs":
            r = _send_documents(None, 0, category=arg or None)
        elif cmd == "snils":
            r = search_by_snils(arg)
        elif cmd == "qa":
            r = ask_llm(arg or "Какие документы нужны для поступления?")
        elif cmd == "callback":
            r = handle_callback(arg, 0)
        else:
            r = {"text": f"Неизвестная команда selftest: {cmd}"}
        print(r["text"])
        return 0

    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN не задан — пропускаю (добавь секрет репозитория). Выход.")
        return 0

    deadline = time.time() + RUN_SECONDS
    offset = None
    print(f"Бот запущен на {RUN_SECONDS}s")

    while time.time() < deadline:
        try:
            resp = _api(token, "getUpdates",
                        offset=offset or "",
                        timeout=30,
                        allowed_updates='["message","callback_query"]')
        except Exception as e:
            print(f"getUpdates error: {e}")
            time.sleep(3)
            continue

        for upd in resp.get("result", []):
            offset = upd["update_id"] + 1

            # Обработка нажатия inline-кнопки
            if "callback_query" in upd:
                cq = upd["callback_query"]
                cq_id = cq["id"]
                data = cq.get("data", "")
                chat = cq["message"]["chat"]["id"]
                try:
                    _api(token, "answerCallbackQuery", callback_query_id=cq_id)
                    reply = handle_callback(data, chat)
                    _send(token, chat, reply)
                except Exception as e:
                    print(f"callback error ({data}): {e}")
                continue

            # Обработка текстового сообщения
            msg = upd.get("message") or {}
            text = (msg.get("text") or "").strip()
            chat = (msg.get("chat") or {}).get("id")
            if not chat or not text:
                continue
            try:
                reply = handle(text, chat)
            except Exception as e:
                reply = {"text": "Что-то пошло не так, попробуйте позже.", "keyboard": None}
                print(f"handle error: {e}")
            _send(token, chat, reply)

    print("Время вышло, выход")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
