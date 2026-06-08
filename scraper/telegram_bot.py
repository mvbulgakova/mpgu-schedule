"""Telegram-бот расписания МПГУ на long-polling (для запуска в GitHub Actions).

Без внешнего хостинга и вебхуков: воркфлоу периодически запускает этот скрипт,
он опрашивает getUpdates ~55 минут и отвечает почти мгновенно, затем выходит;
крон перезапускает. Нужен только секрет BOT_TOKEN.

Данные берёт с публичного CDN jsDelivr (data-ветка) — ничего деплоить не надо.

Локальный прогон логики (без Telegram):
    python -m scraper.telegram_bot --selftest ВОП40-ПФК2501
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import datetime as dt

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


def search_key(s: str) -> str:
    return re.sub(r"[\s\-_]", "", s.strip().upper().translate(_HOMO))


def _get_json(path: str):
    url = f"{DATA_BASE}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "MPGU-Schedule-Bot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _esc(s) -> str:
    return (str("" if s is None else s)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _iso_week_even(d: dt.date) -> bool:
    return d.isocalendar()[1] % 2 == 0


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


def handle(text: str) -> str:
    text = text.strip()
    if text.startswith("/start") or text.startswith("/help"):
        return ("👋 Бот расписания МПГУ.\n\nПришлите код группы — например "
                "<b>ВОП40-ПФК2501</b> (можно часть) — покажу пары на сегодня.")
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


def _api(token: str, method: str, **params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        print(handle(sys.argv[2]))
        return 0
    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN не задан"); return 1
    deadline = time.time() + RUN_SECONDS
    offset = None
    print(f"Бот запущен на {RUN_SECONDS}s")
    while time.time() < deadline:
        try:
            resp = _api(token, "getUpdates",
                        offset=offset or "", timeout=30, allowed_updates='["message"]')
        except Exception as e:
            print(f"getUpdates error: {e}"); time.sleep(3); continue
        for upd in resp.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            text = (msg.get("text") or "").strip()
            chat = (msg.get("chat") or {}).get("id")
            if not chat or not text:
                continue
            try:
                reply = handle(text)
            except Exception as e:
                reply = "Что-то пошло не так, попробуйте позже."
                print(f"handle error: {e}")
            try:
                _api(token, "sendMessage", chat_id=chat, text=reply,
                     parse_mode="HTML", disable_web_page_preview="true")
            except Exception as e:
                print(f"sendMessage error: {e}")
    print("Время вышло, выход")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
