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
    [("📅 Сроки и этапы", "adm_calendar"),   ("🎓 Подбор программ", "adm_calculator")],
    [("📄 Документы",     "adm_docs"),        ("🏆 Мои достижения", "adm_id")],
    [("💳 Платное обучение", "adm_paid"),     ("📝 ВИ и ДВИ",       "adm_vi")],
    [("🔍 Найти себя в списке", "adm_snils")],
    [("💬 Задать вопрос", "adm_qa")],
])

_DOCS_MENU_KB = _make_keyboard([
    [("Бюджет", "adm_docs_budget"), ("Платное", "adm_docs_contract")],
    [("Целевое", "adm_docs_target")],
    [("◀ Назад", "adm_main")],
])

_PAID_MENU_KB = _make_keyboard([
    [("💰 Стоимость по направлениям", "paid_cost")],
    [("🏦 Образовательный кредит",    "paid_credit")],
    [("🤱 Материнский капитал",        "paid_maternkap")],
    [("◀ Назад", "adm_main")],
])

_VI_MENU_KB = _make_keyboard([
    [("🏫 После школы (общеобразовательные ВИ)", "vi_school")],
    [("🛠 На базе СПО (после колледжа)",          "vi_spo")],
    [("🎨 Творческие и профессиональные ДВИ",      "vi_creative")],
    [("◀ Назад", "adm_main")],
])

_CALC_MENU_KB = _make_keyboard([
    [("📋 По результатам ЕГЭ",                "calc_ege")],
    [("📝 Сдаю внутренние экзамены МПГУ (ВИ)", "calc_vi_info")],
    [("🏆 У меня диплом олимпиады (БВИ)",       "calc_bvi")],
    [("◀ Назад", "adm_main")],
])

_ID_MENU_KB = _make_keyboard([
    [("🧮 Посчитать мои баллы за ИД", "id_calc")],
    [("📋 Что вообще даёт баллы",      "id_info")],
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
# Платное обучение
# ---------------------------------------------------------------------------

def _send_paid_main() -> dict:
    return {
        "text": (
            "💳 <b>Платное обучение в МПГУ</b>\n\n"
            "Ты можешь учиться на платной основе, если не проходишь на бюджет по конкурсу "
            "или хочешь поступить без учёта конкурса.\n\n"
            "Выбери, что тебя интересует:"
        ),
        "keyboard": _PAID_MENU_KB,
    }


def _send_paid_cost() -> dict:
    try:
        programs = _adm_json("programs.json")
        plist = programs if isinstance(programs, list) else programs.get("programs", [])
        paid = [p for p in plist if p.get("tuition_cost") or p.get("cost_per_year")]
    except Exception:
        paid = []

    if paid:
        lines = ["💰 <b>Стоимость обучения по направлениям</b>\n"]
        for p in paid[:25]:
            cost = p.get("tuition_cost") or p.get("cost_per_year", "?")
            cost_str = f"{cost:,}".replace(",", " ") if isinstance(cost, int) else str(cost)
            lines.append(f"• {_esc(p.get('name',''))} — <b>{cost_str} руб/год</b>")
        lines.append("\n📌 Актуальные цены: mpgu.su/postuplenie/platnoe-obuchenie/")
        return {"text": "\n".join(lines), "keyboard": _PAID_MENU_KB}

    return {
        "text": (
            "💰 <b>Стоимость обучения</b>\n\n"
            "Стоимость зависит от направления и формы обучения.\n\n"
            "📌 Актуальный прайс-лист: mpgu.su/postuplenie/platnoe-obuchenie/\n\n"
            "По вопросам оплаты:\n"
            "📞 +7 (495) 438-18-57\n"
            "✉️ dg@mpgu.su"
        ),
        "keyboard": _PAID_MENU_KB,
    }


def _send_paid_credit() -> dict:
    return {
        "text": (
            "🏦 <b>Образовательный кредит с господдержкой</b>\n\n"
            "В МПГУ можно оплатить обучение с помощью образовательного кредита.\n\n"
            "<b>Шаги для оформления:</b>\n"
            "1. Заключи договор об оказании платных образовательных услуг с МПГУ.\n"
            "2. Получи квитанцию на оплату.\n"
            "3. Дождись подписания договора со стороны вуза и забери свой экземпляр.\n"
            "4. Обратись с этими документами в банк для оформления кредита.\n"
            "5. Пришли на почту отдела договорного приема поручение владельца счета.\n\n"
            "⚠️ Если банк запрашивает дополнительное соглашение — свяжитесь с экономическим отделом.\n\n"
            "📞 +7 (495) 438-18-57\n"
            "✉️ dg@mpgu.su"
        ),
        "keyboard": _PAID_MENU_KB,
    }


def _send_paid_maternkap() -> dict:
    return {
        "text": (
            "🤱 <b>Оплата материнским капиталом</b>\n\n"
            "МПГУ принимает оплату за счёт средств федерального или регионального "
            "материнского (семейного) капитала.\n\n"
            "<b>Необходимые документы:</b>\n"
            "1. Сертификат на материнский (семейный) капитал\n"
            "2. Справка из СФР (Социального фонда России) об остатке средств\n"
            "3. Документ, удостоверяющий личность владельца сертификата\n"
            "4. Договор об обучении с МПГУ\n"
            "5. Заявление о распоряжении средствами МСК (подаётся в СФР)\n"
            "6. Справка о зачислении студента\n\n"
            "📨 Подтверждающие документы направить на: <b>econom@mpgu.su</b>\n\n"
            "⚠️ Материнский капитал нельзя использовать для оплаты общежития и других услуг — "
            "только за образовательную программу."
        ),
        "keyboard": _PAID_MENU_KB,
    }


# ---------------------------------------------------------------------------
# ВИ и ДВИ
# ---------------------------------------------------------------------------

def _send_vi_main() -> dict:
    return {
        "text": (
            "📝 <b>Вступительные испытания (ВИ и ДВИ)</b>\n\n"
            "Некоторые абитуриенты имеют право не сдавать ЕГЭ, а проходить экзамены (ВИ) "
            "прямо в МПГУ. Также на ряде направлений есть обязательные дополнительные "
            "испытания (ДВИ).\n\n"
            "Какая у тебя ситуация?"
        ),
        "keyboard": _VI_MENU_KB,
    }


def _send_vi_school() -> dict:
    return {
        "text": (
            "🏫 <b>Общеобразовательные ВИ в МПГУ</b>\n\n"
            "Право сдавать общеобразовательные вступительные испытания в вузе вместо ЕГЭ имеют:\n"
            "• Лица с ограниченными возможностями здоровья (ОВЗ) и инвалиды\n"
            "• Иностранные граждане\n"
            "• Выпускники иностранных учебных заведений\n"
            "• Граждане из приграничных территорий (при наличии документального подтверждения)\n\n"
            "Испытания проводятся по тем же предметам, что и ЕГЭ, но в очном формате в МПГУ.\n\n"
            "📌 Программы испытаний: mpgu.su/postuplenie/entrance-test-programs/\n\n"
            "❓ Если не уверен, имеешь ли ты право — напиши нам: <b>priem@mpgu.su</b>"
        ),
        "keyboard": _VI_MENU_KB,
    }


def _send_vi_spo() -> dict:
    return {
        "text": (
            "🛠 <b>Экзамены на базе СПО (после колледжа)</b>\n\n"
            "Выпускники колледжей и техникумов (СПО) сдают профильные внутренние экзамены "
            "МПГУ вместо ЕГЭ. Набор экзаменов зависит от выбранного направления.\n\n"
            "<b>Примеры вступительных испытаний:</b>\n"
            "• Основы педагогики и психологии\n"
            "• Русский язык и литература\n"
            "• Основы лингвистических знаний\n"
            "• Основы алгоритмизации и программирования\n"
            "• История государства и права России\n"
            "• Математика (для технических направлений)\n\n"
            "📌 Полный список по направлениям: mpgu.su/postuplenie/entrance-test-programs/\n\n"
            "⚠️ <b>Важно:</b> выпускники СПО могут поступать одновременно по ЕГЭ (если "
            "сдавали) и по ВИ — засчитывается лучший результат."
        ),
        "keyboard": _VI_MENU_KB,
    }


def _send_vi_creative() -> dict:
    return {
        "text": (
            "🎨 <b>Дополнительные вступительные испытания (ДВИ)</b>\n\n"
            "На ряде направлений есть обязательные творческие или профессиональные "
            "экзамены, которые сдаются в МПГУ независимо от наличия ЕГЭ.\n\n"
            "<b>Примеры ДВИ по направлениям:</b>\n"
            "• <b>Журналистика</b> — творческое испытание (сочинение/эссе)\n"
            "• <b>Художественное образование</b> — рисунок и живопись\n"
            "• <b>Музыкальное искусство</b> — исполнительство и теория музыки (сольфеджио)\n"
            "• <b>Физическая культура</b> — профессиональное испытание по физкультуре\n"
            "• <b>Хореографическое искусство</b> — практический экзамен\n\n"
            "⚠️ <b>Минимальный балл</b> для успешного прохождения творческого ДВИ — "
            "<b>21 балл</b> из 100. При результате ниже минимума — отказ в зачислении.\n\n"
            "📌 Программы для подготовки: mpgu.su/postuplenie/entrance-test-programs/"
        ),
        "keyboard": _VI_MENU_KB,
    }


# ---------------------------------------------------------------------------
# Индивидуальные достижения (ИД)
# ---------------------------------------------------------------------------

_ID_RULES = {
    "diploma_honors": {
        "label": "Аттестат/диплом с отличием",
        "points": 10,
        "keywords": ["отличием", "отличник", "медаль", "золотая медаль", "серебряная медаль",
                     "красный диплом"],
    },
    "gto_gold": {
        "label": "Значок ГТО (золотой)",
        "points": 5,
        "keywords": ["гто", "золот", "gold"],
    },
    "gto_silver": {
        "label": "Значок ГТО (серебряный/бронзовый)",
        "points": 4,
        "keywords": ["гто серебр", "гто бронз", "серебряный гто", "бронзовый гто"],
    },
    "olympiad_winner": {
        "label": "Победитель/призёр олимпиады (всероссийской)",
        "points": 5,
        "keywords": ["олимпиада", "всероссийская", "призёр", "победитель"],
    },
    "sport_champ": {
        "label": "Чемпион/призёр РФ, мира, Европы по спорту",
        "points": 10,
        "keywords": ["чемпион", "кмс", "мастер спорта", "мс рф", "чемпионат мира",
                     "чемпионат европы", "чемпионат рф"],
    },
}

# Баллы за волонтёрство по часам (по правилам МПГУ)
_VOLUNTEER_HOURS_TABLE = [
    (480, 10, 8),   # ≥480 ч: профильное 10, непрофильное 8
    (300, 8,  7),   # ≥300 ч: профильное 8,  непрофильное 7
    (150, 6,  5),   # ≥150 ч: профильное 6,  непрофильное 5
    (60,  4,  3),   # ≥60 ч:  профильное 4,  непрофильное 3
    (0,   3,  2),   # любые:  профильное 3,  непрофильное 2
]

_PROFILE_VOLUNTEER_KW = [
    "педагог", "учитель", "образован", "детей", "дети", "школьник", "вожатый",
    "наставник", "волонтёр-педагог", "социальн",
]


def _calc_volunteer_score(text: str) -> tuple[int, str]:
    """Определяет баллы за волонтёрство из свободного текста."""
    text_l = text.lower()
    hours_m = re.search(r"(\d+)\s*(час|ч\b|h\b)", text_l)
    hours = int(hours_m.group(1)) if hours_m else 0
    is_profile = any(kw in text_l for kw in _PROFILE_VOLUNTEER_KW)

    for threshold, profile_pts, general_pts in _VOLUNTEER_HOURS_TABLE:
        if hours >= threshold:
            pts = profile_pts if is_profile else general_pts
            profile_note = " (педагогическое/социальное направление)" if is_profile else ""
            hours_note = f"{hours} ч" if hours else "часы не указаны → минимум"
            return pts, f"Волонтёрская книжка ({hours_note}{profile_note})"
    return 2, "Волонтёрская книжка"


_ID_CALC_SYSTEM = """Ты разбираешь описание индивидуальных достижений абитуриента МПГУ.
Определи, что именно упомянуто, и назначь баллы по следующим правилам МПГУ:

• Аттестат/диплом СПО с отличием — 10 баллов
• Золотой значок ГТО — 5 баллов; серебряный/бронзовый — 4 балла
• Победитель олимпиады (всерос. уровень) — 5 баллов; призёр — 3 балла
• Чемпион/призёр страны, мира, Европы по спорту — 5-10 баллов
• Волонтёрство с книжкой — 2-10 баллов (в зависимости от часов и профиля)

ВАЖНО: суммарный лимит — 10 баллов (15 для целевого зачисления).

Верни ТОЛЬКО JSON (без markdown):
{"items": [{"label": "...", "points": N}], "total": N, "note": "..."}

"note" — краткий комментарий об ограничениях или уточнениях."""


def _calc_id_scores(text: str) -> dict:
    """Считает баллы ИД: сначала регулярками, при неоднозначности — LLM."""
    text_l = text.lower()
    items: list[dict] = []

    # Волонтёрство
    volunteer_kw = ["волонтёр", "волонтер", "волонт", "доброволец", "книжка волонт"]
    if any(kw in text_l for kw in volunteer_kw):
        pts, label = _calc_volunteer_score(text)
        items.append({"label": label, "points": pts})

    # Остальные категории (кроме волонтёрства и ГТО — они выше)
    for key, rule in _ID_RULES.items():
        if key in ("gto_gold", "gto_silver"):
            # ГТО: проверяем в нужном порядке
            continue
        if any(kw in text_l for kw in rule["keywords"]):
            items.append({"label": rule["label"], "points": rule["points"]})

    # ГТО — проверяем в порядке приоритета
    if "гто" in text_l:
        if any(kw in text_l for kw in ["золот", "золотой"]):
            items.append({"label": _ID_RULES["gto_gold"]["label"],
                          "points": _ID_RULES["gto_gold"]["points"]})
        elif any(kw in text_l for kw in ["серебр", "бронз"]):
            items.append({"label": _ID_RULES["gto_silver"]["label"],
                          "points": _ID_RULES["gto_silver"]["points"]})
        elif not any(kw in text_l for kw in ["серебр", "бронз", "золот"]):
            # ГТО без уточнения — запросим уточнение через LLM или дадим минимум
            items.append({"label": "Значок ГТО (цвет не указан — уточните)", "points": 4})

    if not items:
        # LLM как запасной вариант
        return _calc_id_llm(text)

    # Удаляем дубли
    seen = set()
    unique = []
    for it in items:
        if it["label"] not in seen:
            seen.add(it["label"])
            unique.append(it)

    total = min(sum(it["points"] for it in unique), 10)
    return {"items": unique, "total": total, "note": ""}


def _calc_id_llm(text: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"items": [], "total": 0, "note": "Не удалось распознать достижения — опиши подробнее."}
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_ID_CALC_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
        raw = resp.content[0].text.strip()
        return json.loads(raw)
    except Exception:
        return {"items": [], "total": 0, "note": "Не смог разобрать — попробуй описать точнее."}


def _format_id_result(result: dict) -> str:
    items = result.get("items", [])
    total = result.get("total", 0)
    note = result.get("note", "")

    if not items:
        return (
            "Не нашёл известных достижений. Попробуй описать подробнее.\n\n"
            "Например: <i>«У меня есть волонтёрская книжка 200 часов и золотой ГТО»</i>"
        )

    lines = ["🏆 <b>Баллы за индивидуальные достижения:</b>\n"]
    for it in items:
        lines.append(f"• {_esc(it['label'])} — <b>{it['points']} балл(ов)</b>")
    lines.append(f"\n<b>Итого: {total} балл(ов)</b> (максимум 10)")
    if total == 10:
        lines.append("✅ Ты уже набрал максимум!")
    if note:
        lines.append(f"\n⚠️ {_esc(note)}")
    lines.append("\n💡 Эти баллы прибавляются к сумме ЕГЭ и влияют на место в рейтинге.")
    return "\n".join(lines)


def _send_id_info() -> dict:
    return {
        "text": (
            "🏆 <b>Индивидуальные достижения (ИД)</b>\n\n"
            "МПГУ начисляет дополнительные баллы за личные достижения. "
            "<b>Максимум за все ИД — 10 баллов</b> (15 для целевого).\n\n"
            "<b>За что дают баллы:</b>\n"
            "🥇 Аттестат/диплом СПО с отличием — 10 баллов\n"
            "🥇 Значок ГТО золотой — 5 баллов\n"
            "🥈 Значок ГТО серебряный/бронзовый — 4 балла\n"
            "🏅 Победитель ВсОШ или приравненных олимпиад — 5 баллов\n"
            "🤝 Волонтёрская книжка — от 2 до 10 баллов\n"
            "   (зависит от часов и профиля волонтёрства)\n"
            "🏆 Чемпион/призёр страны или мира по спорту — 5-10 баллов\n\n"
            "💡 Нажми «Посчитать», чтобы я посчитал твои баллы по описанию."
        ),
        "keyboard": _ID_MENU_KB,
    }


# ---------------------------------------------------------------------------
# Калькулятор шансов поступления (ЕГЭ)
# ---------------------------------------------------------------------------

_SUBJECT_ALIASES: dict[str, str] = {
    "русский": "Русский язык", "рус": "Русский язык", "russian": "Русский язык",
    "математика": "Математика (профиль)", "матем": "Математика (профиль)",
    "профиль": "Математика (профиль)", "профильная": "Математика (профиль)",
    "база": "Математика (база)", "базовая": "Математика (база)",
    "обществознание": "Обществознание", "общество": "Обществознание", "общ": "Обществознание",
    "история": "История", "ист": "История",
    "биология": "Биология", "био": "Биология",
    "физика": "Физика", "фи": "Физика",
    "химия": "Химия", "хим": "Химия",
    "информатика": "Информатика", "инф": "Информатика", "ит": "Информатика",
    "иностранный": "Иностранный язык", "английский": "Иностранный язык",
    "немецкий": "Иностранный язык", "французский": "Иностранный язык",
    "литература": "Литература", "лит": "Литература",
    "география": "География", "гео": "География",
}


def _parse_scores(text: str) -> dict[str, int]:
    """Парсит 'Русский 85, Математика профиль 78, Общество 90' → {'Русский язык': 85, ...}"""
    results: dict[str, int] = {}
    # Делим по запятой/точке с запятой/переносу и ищем «предмет число» в каждом кусочке
    for chunk in re.split(r"[,;\n]+", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        # «Предмет 85» или «Предмет: 85»
        m = re.search(r"^(.*?)\s*[:-]?\s*(\d{2,3})\s*$", chunk)
        if not m:
            continue
        subject_raw = m.group(1).strip().lower()
        score = int(m.group(2))
        if score < 20 or score > 100:
            continue
        for alias, canonical in _SUBJECT_ALIASES.items():
            if alias in subject_raw:
                if canonical not in results:
                    results[canonical] = score
                break
    return results


def _match_programs_by_scores(scores: dict[str, int]) -> dict:
    """Сопоставляет баллы с программами из programs.json."""
    try:
        programs = _adm_json("programs.json")
        plist = programs if isinstance(programs, list) else programs.get("programs", [])
    except Exception:
        plist = []

    total = sum(scores.values())
    high, mid, low, no_match = [], [], [], []

    for p in plist:
        required = p.get("ege_subjects") or p.get("exams", [])
        if not required:
            continue
        # Нормализуем требуемые предметы
        req_norm = set()
        for subj in required:
            subj_l = subj.lower()
            for alias, canonical in _SUBJECT_ALIASES.items():
                if alias in subj_l:
                    req_norm.add(canonical)
                    break
            else:
                req_norm.add(subj)

        # Проверяем наличие требуемых предметов
        user_subjects = set(scores.keys())
        if not req_norm.intersection(user_subjects):
            continue  # нет нужных предметов вообще

        # Минимальные пороги
        min_scores = p.get("min_scores", {})
        below_min = []
        for subj, min_score in min_scores.items():
            user_score = scores.get(subj, 0)
            if user_score > 0 and user_score < min_score:
                below_min.append(f"{subj}: {user_score} < {min_score}")

        if below_min:
            no_match.append({**p, "_reason": f"Ниже минимума: {', '.join(below_min)}"})
            continue

        # Сравниваем с проходным прошлого года
        passing = p.get("passing_score_prev") or p.get("min_score")
        if passing:
            diff = total - passing
            entry = {**p, "_total": total, "_passing": passing, "_diff": diff}
            if diff >= 10:
                high.append(entry)
            elif diff >= -15:
                mid.append(entry)
            else:
                low.append(entry)
        else:
            mid.append({**p, "_total": total})

    return {"high": high, "mid": mid, "low": low, "no_match": no_match, "total": total}


def _format_calculator_result(scores: dict[str, int], match: dict) -> str:
    total = match["total"]
    lines = [
        f"🧮 <b>Результат калькулятора шансов</b>\n",
        "Твои предметы:",
    ]
    for subj, score in scores.items():
        lines.append(f"  • {_esc(subj)}: <b>{score}</b>")
    lines.append(f"\n<b>Сумма баллов: {total}</b>\n")

    if match["high"]:
        lines.append("🟢 <b>Высокий шанс</b> (проходной прошлого года ниже твоей суммы):")
        for p in match["high"][:5]:
            seats = p.get("budget_seats", "?")
            lines.append(f"  • {_esc(p.get('name',''))} — бюджет {seats} мест")

    if match["mid"]:
        lines.append("\n🟡 <b>Погранично</b> (±15 баллов от проходного):")
        for p in match["mid"][:5]:
            passing = p.get("_passing", "?")
            lines.append(f"  • {_esc(p.get('name',''))} — проходной ~{passing}")

    if match["low"]:
        lines.append("\n🔴 <b>На бюджет маловероятно</b>, но доступно платное:")
        for p in match["low"][:5]:
            passing = p.get("_passing", "?")
            lines.append(f"  • {_esc(p.get('name',''))} — проходной ~{passing}")

    if match["no_match"]:
        lines.append("\n⚠️ <b>Ниже минимального порога</b> (документы не примут):")
        for p in match["no_match"][:3]:
            lines.append(f"  • {_esc(p.get('name',''))}: {_esc(p.get('_reason',''))}")

    if not any([match["high"], match["mid"], match["low"]]):
        lines.append(
            "ℹ️ Не нашёл подходящих направлений по введённым предметам.\n"
            "Уточни набор: например, для педагогики нужны <b>Русский язык</b> + профильный предмет."
        )

    lines.append("\n💡 <b>Важно:</b> проходные баллы меняются каждый год. "
                 "Используй результат как ориентир, не как гарантию.")
    lines.append("📌 Актуальные данные: mpgu.su/abiturientam/")
    return "\n".join(lines)


def _calc_ege_no_data_text() -> str:
    return (
        "🧮 <b>Введи свои ЕГЭ-баллы</b>\n\n"
        "Напиши предметы и баллы в свободной форме. Например:\n\n"
        "<i>Русский 87, Математика профиль 72, Обществознание 80</i>\n"
        "<i>или: Русский язык 91, История 74, Биология 65</i>\n\n"
        "Я покажу, на какие направления МПГУ ты можешь пройти на бюджет 🎓"
    )


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
    # Главное меню
    if data == "adm_main":
        return {"text": "Главное меню абитуриента:", "keyboard": MAIN_MENU_KB}

    # Направления
    if data == "adm_programs":
        return _send_programs(None, chat_id)

    # Сроки
    if data == "adm_calendar":
        return _send_calendar(None, chat_id)

    # Документы
    if data == "adm_docs":
        return _send_documents(None, chat_id, category=None)
    if data == "adm_docs_budget":
        return _send_documents(None, chat_id, category="budget")
    if data == "adm_docs_contract":
        return _send_documents(None, chat_id, category="contract")
    if data == "adm_docs_target":
        return _send_documents(None, chat_id, category="target")

    # Индивидуальные достижения
    if data == "adm_id":
        return _send_id_info()
    if data == "id_info":
        return _send_id_info()
    if data == "id_calc":
        _STATE[chat_id] = {"mode": "id_waiting"}
        return {
            "text": (
                "🏆 <b>Посчитаем твои баллы за достижения</b>\n\n"
                "Опиши свои достижения в свободной форме. Например:\n\n"
                "<i>«У меня волонтёрская книжка 240 часов педагогического волонтёрства, "
                "золотой ГТО и аттестат без троек»</i>\n\n"
                "Я назначу баллы по правилам МПГУ 🎯"
            ),
            "keyboard": _BACK_KB,
        }

    # Платное обучение
    if data == "adm_paid":
        return _send_paid_main()
    if data == "paid_cost":
        return _send_paid_cost()
    if data == "paid_credit":
        return _send_paid_credit()
    if data == "paid_maternkap":
        return _send_paid_maternkap()

    # ВИ и ДВИ
    if data == "adm_vi":
        return _send_vi_main()
    if data == "vi_school":
        return _send_vi_school()
    if data == "vi_spo":
        return _send_vi_spo()
    if data == "vi_creative":
        return _send_vi_creative()

    # Калькулятор шансов
    if data == "adm_calculator":
        return {"text": "🧮 <b>Подбор программ</b>\n\nКак ты поступаешь?", "keyboard": _CALC_MENU_KB}
    if data == "calc_ege":
        _STATE[chat_id] = {"mode": "calc_ege_waiting"}
        return {"text": _calc_ege_no_data_text(), "keyboard": _BACK_KB}
    if data == "calc_vi_info":
        return {
            "text": (
                "📝 <b>Поступление по внутренним испытаниям (ВИ)</b>\n\n"
                "Если ты сдаёшь вступительные испытания в МПГУ (а не ЕГЭ), "
                "калькулятор по баллам ЕГЭ тебе не подойдёт.\n\n"
                "Что делать:\n"
                "1. Уточни список испытаний для своего направления → раздел «ВИ и ДВИ»\n"
                "2. Подготовься по программам с сайта МПГУ\n"
                "3. После экзаменов используй «Найти себя в списке» по СНИЛС\n\n"
                "📌 mpgu.su/postuplenie/entrance-test-programs/"
            ),
            "keyboard": _CALC_MENU_KB,
        }
    if data == "calc_bvi":
        return {
            "text": (
                "🏆 <b>Поступление без вступительных испытаний (БВИ)</b>\n\n"
                "Если ты победитель или призёр Всероссийской олимпиады школьников (ВсОШ) "
                "по профильному предмету — ты можешь поступить <b>без конкурса</b>.\n\n"
                "<b>Что нужно:</b>\n"
                "• Диплом победителя/призёра ВсОШ (не старше 4 лет)\n"
                "• Аттестат об окончании школы\n"
                "• Подать заявление в МПГУ с подтверждением права БВИ\n\n"
                "<b>Важно:</b> право БВИ действует только на одно направление. "
                "На остальные ты можешь подавать по ЕГЭ.\n\n"
                "📌 Уточни детали: priem@mpgu.su"
            ),
            "keyboard": _CALC_MENU_KB,
        }

    # СНИЛС
    if data == "adm_snils":
        _STATE[chat_id] = {"mode": "snils_wait"}
        return {
            "text": (
                "🔍 <b>Найти себя в конкурсном списке</b>\n\n"
                "Введите ваш СНИЛС — я найду вас во всех опубликованных рейтинговых списках.\n\n"
                "Формат: <code>123-456-789 01</code> или <code>12345678901</code>\n\n"
                "🔒 СНИЛС нигде не сохраняется и не передаётся третьим лицам."
            ),
            "keyboard": _BACK_KB,
        }

    # Q&A
    if data == "adm_qa":
        _STATE[chat_id] = {"mode": "qa_wait"}
        return {
            "text": (
                "💬 <b>Задайте вопрос о поступлении</b>\n\n"
                "Спросите что угодно: документы, сроки, направления, баллы, общежитие...\n\n"
                "Я отвечу на основе актуальной информации с сайта МПГУ 🎓"
            ),
            "keyboard": _BACK_KB,
        }

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

    # Диспетчер по состоянию
    state = _STATE.get(chat_id, {})
    mode = state.get("mode")

    if mode == "snils_wait":
        _STATE.pop(chat_id, None)
        return search_by_snils(text)

    if mode == "qa_wait":
        _STATE.pop(chat_id, None)
        return ask_llm(text)

    if mode == "id_waiting":
        _STATE.pop(chat_id, None)
        result = _calc_id_scores(text)
        return {"text": _format_id_result(result), "keyboard": _ID_MENU_KB}

    if mode == "calc_ege_waiting":
        _STATE.pop(chat_id, None)
        scores = _parse_scores(text)
        if not scores:
            # LLM попытается распарсить нестандартный ввод
            _STATE[chat_id] = {"mode": "calc_ege_waiting"}
            return {
                "text": (
                    "Не смог разобрать баллы 🤔\n\n"
                    "Попробуй написать так: <b>Русский 87, Математика 72, Обществознание 80</b>\n"
                    "Число рядом с предметом — твой балл ЕГЭ (от 20 до 100)."
                ),
                "keyboard": _BACK_KB,
            }
        match = _match_programs_by_scores(scores)
        return {"text": _format_calculator_result(scores, match), "keyboard": _CALC_MENU_KB}

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
