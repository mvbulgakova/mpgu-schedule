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

from scraper.abitur import (campaign, dialog, faq, feedback, follow, llm, lists,
                            shansy, study_plans)

RUN_SECONDS = int(os.environ.get("RUN_SECONDS", "3300"))
MAX_MSG_LEN = 1000
# Файл подписок «следи за кодом» (переживает рестарты через actions/cache).
SUBS_PATH = os.environ.get("SUBS_PATH", "")
SUBS_CHECK_SECONDS = 600
# Обратная связь: файл-хранилище и chat_id администратора (для /export, /fb_stats).
FEEDBACK_PATH = os.environ.get("FEEDBACK_PATH", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0") or "0")

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
# Обратная связь: накопленные записи и режим «жду отзыв».
FEEDBACK: List[dict] = []
AWAITING_FEEDBACK: Dict[int, bool] = {}
# Ожидание названия направления после /plan (учебные планы).
AWAITING_PLAN: Dict[int, bool] = {}


@dataclass
class Reply:
    text: str
    keyboard: List[List[Tuple[str, str]]] = field(default_factory=list)
    is_menu: bool = False   # сам экран меню — к нему кнопку «Меню» не добавляем
    document: Optional[Tuple[bytes, str]] = None   # (содержимое, имя файла) для sendDocument


_MENU_ROW = [("🏠 Меню", "open:menu")]


def _finalize(r: Reply) -> Reply:
    """Дописывает кнопку возврата в меню ко всем ответам, кроме самого меню.

    Пустой ответ (тихий игнор админ-команд от посторонних) не трогаем.
    """
    if r.is_menu or (not r.text and not r.document):
        return r
    return Reply(r.text, list(r.keyboard) + [_MENU_ROW], r.is_menu, r.document)


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
    rows.append([("📄 Учебный план", "open:plan")])
    rows.append([("🔔 Обновление списков", "u:1")])
    return rows


_GREETING = ("👋 Привет! Я помощник абитуриента МПГУ.\n\n"
             "Задайте вопрос своими словами — или выберите тему кнопкой ниже.\n\n"
             "<b>Самое нужное:</b>\n"
             "🔎 /spisok — прохожу ли я и на что (🔔 можно следить)\n"
             "🧮 /shansy — подбор программ по баллам ЕГЭ\n"
             "🧭 /vybor — помочь выбрать направление\n"
             "➕ /bally — калькулятор доп. баллов\n"
             "📅 /sroki — сроки и дедлайны\n\n"
             "<i>Вопросы о работе бота: @soldat_olovyanniy</i>")


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


_PLAN_PROMPT = ("Напишите <b>направление или профиль</b> (можно с кодом), например:\n"
                "<b>начальное образование</b> · <b>44.03.05 история и обществознание</b> · "
                "<b>лингвистика перевод</b>\n"
                "Пришлю официальный перечень дисциплин по программе (файлом).")


def _plan_label(p: dict) -> str:
    prof = (p.get("profile") or p.get("napr") or "")[:48]
    return f"📄 {p['code']} {prof} ({p.get('form', '')})"


def _plan_search(query: str) -> Reply:
    cands = study_plans.find_by_text(query)
    if not cands:
        return Reply("Не нашёл такого направления. Попробуйте иначе — по коду "
                     "(<b>44.03.01</b>) или короче (<b>биология</b>, "
                     "<b>лингвистика</b>). Полный список: "
                     "https://mpgu.su/sveden/education/", [])
    if len(cands) == 1:
        return _plan_menu(study_plans.share_id(cands[0]))
    kb = [[(_plan_label(p), f"plan:{study_plans.share_id(p)}")] for p in cands]
    return Reply("Нашлось несколько — выберите программу:", kb)


def _plan_menu(sid: str) -> Reply:
    """Выбор программы → что показать: файл плана или разбивку по семестрам."""
    p = study_plans.by_share_id(sid)
    if not p:
        return Reply("Не удалось найти этот план. Откройте меню и попробуйте снова.", [])
    kb = [[("📄 Скачать план (PDF)", f"dl:{sid}")]]
    if study_plans.semesters_for(sid):
        kb.append([("📅 Что по семестрам", f"sem:{sid}")])
    return Reply(f"📄 <b>{p['code']} {p.get('profile', '')}</b> ({p.get('form', '')}, "
                 f"год приёма {p.get('year', '')}). Что показать?", kb)


def _plan_semesters(sid: str) -> Reply:
    txt = study_plans.format_semesters(sid)
    if not txt:
        return Reply("По этой программе разбивка по семестрам пока недоступна — "
                     "но сам файл плана можно скачать (📄).",
                     [[("📄 Скачать план (PDF)", f"dl:{sid}")]])
    return Reply(txt, [[("📄 Скачать план (PDF)", f"dl:{sid}")]])


def _plan_send(sid: str) -> Reply:
    p = study_plans.by_share_id(sid)
    if not p:
        return Reply("Не удалось найти этот план. Откройте меню и попробуйте снова.", [])
    got = study_plans.fetch_plan_pdf(p)
    link = study_plans.share_url(p)
    if not got:
        return Reply(f"📄 <b>{p['code']} {p.get('profile', '')}</b> ({p.get('form', '')})\n"
                     f"Файл сейчас не скачался. Открыть на сайте МПГУ: {link}", [])
    data, filename = got
    caption = (f"📄 <b>{p['code']} {p.get('profile', '')}</b> ({p.get('form', '')})\n"
               f"Официальный учебный план (год приёма {p.get('year', '')}). "
               f"Источник: {link}")
    return Reply(caption, [], document=(data, filename))


def _lookup_code(code: str, detailed: bool = False) -> Reply:
    meta = lists.fetch_meta()
    if meta is None:  # реально недоступен индекс, а не просто редкий код
        return Reply("Индекс списков сейчас недоступен. Официальные списки: "
                     "https://epk25.mpgu.su/competitive-list", [])
    # shard может быть None, если кодов с таким префиксом нет — это «не найден»
    shard = lists.fetch_shard(code)
    fmt = lists.format_positions if detailed else lists.format_positions_short
    text = fmt(meta, shard, code)
    kb: List[List[Tuple[str, str]]] = []
    if lists.lookup(shard, code):
        norm = lists._norm(code)
        row = [("🔔 Следить", f"f:{norm}")]
        if not detailed:
            row.insert(0, ("📋 Подробнее", f"x:{norm}"))
        kb = [row, [("🔔 Обновление списков", "u:1")]]
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


def _follow_updates(chat_id: int, on: bool) -> Reply:
    """Подписка на сам факт обновления списков на epk25 — без кода заявления.

    Отдельная от «следить за кодом»: обновление списков касается всех, и знать
    о нём хотят и те, кто свой код не вводил. Живёт в той же записи подписчика,
    поэтому включение/выключение не должно задевать слежку за кодом.
    """
    sub = SUBS.setdefault(str(chat_id), {})
    if not on:
        sub.pop("lists_updates", None)
        sub.pop("src", None)
        if not sub.get("code"):
            SUBS.pop(str(chat_id), None)
        _save_subs()
        return Reply("🔕 Больше не сообщаю об обновлении списков.", [])
    meta = lists.fetch_meta()
    sub["lists_updates"] = True
    # Запоминаем текущую отметку, иначе первое же уведомление придёт про
    # обновление, которое случилось ДО подписки.
    sub["src"] = lists.source_updated_at(meta)
    _save_subs()
    src = sub["src"]
    when = f" (последнее — {lists._hhmm_dd_mm(src)})" if src else ""
    return Reply("🔔 Сообщу, когда МПГУ обновит конкурсные списки на epk25"
                 f"{when}.\nОтключить: кнопка «Не сообщать об обновлении списков».",
                 [[("🔕 Не сообщать об обновлении списков", "u:0")]])


_OTZYV_THANKS = ("Спасибо! 🙏 Записал анонимно — это поможет отвечать абитуриентам "
                 "честнее. Есть ещё впечатления — просто отправьте /otzyv снова.")


def _save_feedback(chat_id: int, kind: str, text: str):
    global FEEDBACK
    FEEDBACK = feedback.add(FEEDBACK_PATH or None, FEEDBACK, chat_id, kind, text)


def _otzyv(chat_id: int, payload: str) -> Reply:
    if payload:
        _save_feedback(chat_id, "otzyv", payload)
        return Reply(_OTZYV_THANKS, [])
    AWAITING_FEEDBACK[chat_id] = True
    return Reply("✍️ Поделитесь впечатлениями одним сообщением: общежития, учёба, "
                 "преподаватели, быт — что угодно. Сохраню анонимно (кто вы — "
                 "не записывается).", [])


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

    # 4) ожидаем отзыв после /otzyv
    if AWAITING_FEEDBACK.get(chat_id) and text and not text.startswith("/"):
        AWAITING_FEEDBACK.pop(chat_id, None)
        _save_feedback(chat_id, "otzyv", text)
        return Reply(_OTZYV_THANKS, [])

    # 5) ожидаем название направления после /plan
    if AWAITING_PLAN.get(chat_id) and text and not text.startswith("/"):
        AWAITING_PLAN.pop(chat_id, None)
        return _plan_search(text)

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
    if intent == "plan":
        if payload:
            return _plan_search(payload)
        AWAITING_PLAN[chat_id] = True
        return Reply(_PLAN_PROMPT, [])
    if intent == "otzyv":
        return _otzyv(chat_id, payload)
    if intent == "myid":
        return Reply(f"Ваш chat id: <b>{chat_id}</b>", [])
    if intent == "export":
        if chat_id != ADMIN_CHAT_ID:
            return Reply("", [])   # молча
        items = FEEDBACK
        if not items:
            return Reply("База обратной связи пуста.", [])
        name = f"feedback_{len(items)}.csv"
        return Reply(f"Выгрузка: {len(items)} записей.", [],
                     document=(feedback.to_csv(items), name))
    if intent == "fb_stats":
        if chat_id != ADMIN_CHAT_ID:
            return Reply("", [])   # молча
        return Reply(feedback.stats_text(FEEDBACK), [])
    if intent == "broadcast":
        if chat_id != ADMIN_CHAT_ID:
            return Reply("", [])   # молча
        return _broadcast(payload)
    # Голый уникальный код без команды — самый частый ввод (треть сообщений).
    # Раньше он уходил в ИИ, тот отвечал «воспользуйтесь /spisok», и человек
    # слал код снова и снова. Ищем позицию сразу.
    digits = re.sub(r"[\s\-]", "", text)
    if digits.isdigit() and not text.startswith("/"):
        if 5 <= len(digits) <= 8:
            return _lookup_code(digits)
        if len(digits) >= 9:
            return Reply("Это похоже на ID Telegram или телефон, а нужен "
                         "<b>уникальный код</b> заявления (6–7 цифр). Он есть в "
                         "личном кабинете на Госуслугах и в конкурсных списках "
                         f"{lists._OFFICIAL}", [])

    # свободный вопрос — сохраняем для аналитики (хеш вместо личности) и в логи
    _save_feedback(chat_id, "question", payload)
    print(f"Q: {re.sub(r'[0-9]{5,}', '<код>', payload)[:120]}", flush=True)
    return Reply(_answer_free(chat_id, payload), [])


def handle_callback(chat_id: int, data: str) -> Reply:
    return _finalize(_handle_callback(chat_id, data))


def _handle_callback(chat_id: int, data: str) -> Reply:
    if data == "open:menu":
        # выход из любых режимов ожидания — «спасательная» кнопка
        AWAITING_CODE.pop(chat_id, None)
        AWAITING_SCORES.pop(chat_id, None)
        AWAITING_PLAN.pop(chat_id, None)
        return Reply("Выберите тему:", _menu_keyboard(), is_menu=True)
    if data == "open:plan":
        AWAITING_PLAN[chat_id] = True
        return Reply(_PLAN_PROMPT, [])
    if data.startswith("plan:"):
        return _plan_menu(data[5:])
    if data.startswith("dl:"):
        return _plan_send(data[3:])
    if data.startswith("sem:"):
        return _plan_semesters(data[4:])
    if data.startswith("d:"):
        text_d, kb = faq.dates_step(data[2:])
        return Reply(text_d, kb)
    if data.startswith("u:"):
        return _follow_updates(chat_id, data[2:] == "1")
    if data.startswith("f:"):
        arg = data[2:]
        if arg == "off":
            return _unfollow(chat_id)
        return _follow_code(chat_id, arg)
    if data.startswith("x:"):   # развернуть подробности по коду
        return _lookup_code(data[2:], detailed=True)
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


def _broadcast(text: str) -> Reply:
    """Рассылка админа всем подписчикам /follow (одноразово, вручную).

    Появилась после инцидента 29.07: epk25 под нагрузкой отдал урезанные
    страницы, и подписчики получили ложное «вас больше нет в списке» (см.
    build_lists_index._guard_incomplete). У нас нет лога, КОМУ конкретно ушло
    ложное уведомление (sub["last"] перезаписывается на каждой сверке), поэтому
    рассылка идёт всем текущим подписчикам — это надёжный надмножество
    затронутых, а не точный список.
    """
    if not text:
        return Reply(f"Использование: <b>/broadcast текст</b>\n"
                     f"Уйдёт всем подписчикам /follow (сейчас: {len(SUBS)}).", [])
    token = os.environ.get("BOT_TOKEN")
    if not token:
        return Reply("BOT_TOKEN не задан — не могу отправить.", [])
    ok, fail = 0, 0
    for chat in list(SUBS):
        try:
            _send(token, int(chat), Reply(text, []))
            ok += 1
        except Exception as e:
            fail += 1
            print(f"broadcast error {chat}: {e}")
        time.sleep(0.1)   # вежливый интервал — не упереться в лимиты Telegram
    return Reply(f"Разослано: {ok} успешно, {fail} с ошибкой (из {len(SUBS)}).", [])


def _check_subs(token: str):
    """Сверяет позиции подписчиков со свежими данными; шлёт диффы."""
    if not SUBS:
        # Пустой список подписок и «всё тихо, уведомлять некого» выглядят
        # снаружи одинаково. Отличить их без этой строки нельзя: логи
        # работающего прогона GitHub не отдаёт, а идёт он часами.
        print("check_subs: подписок нет — уведомлять некого", flush=True)
        return
    meta = lists.fetch_meta(force=True)
    if not meta:
        print("check_subs: индекс недоступен — пропускаю проход", flush=True)
        return
    upd = meta.get("updated_at", "")
    src = lists.source_updated_at(meta)
    seen_srcs = {s.get("src") for s in SUBS.values()}
    print(f"check_subs: подписок {len(SUBS)}, обход {upd[11:16]}, "
          f"вуз {src[11:16] if src else '—'}, у подписчиков запомнено "
          f"{sorted(x[11:16] if x else '—' for x in seen_srcs)}", flush=True)
    sent_count = [0]
    changed = False
    for chat, sub in list(SUBS.items()):
        # Ориентир — отметка САМОГО epk25, а не время нашего обхода: обход идёт
        # каждые несколько минут и сдвигает updated_at постоянно, а списки вуз
        # пересчитывает куда реже. Людям важно именно это событие.
        seen = sub.get("src")
        source_moved = bool(src) and seen != src
        if source_moved and seen is None:
            # Подписка оформлена до появления этого поля: запоминаем текущую
            # отметку молча. Иначе первый же прогон после выкатки разошлёт
            # уведомление про обновление, которое случилось ДО подписки.
            sub["src"] = src
            changed = True
            source_moved = False
        # Отметку «видел» двигаем ТОЛЬКО после доставки. Иначе любой сбой
        # между отметкой и отправкой (моргнул CDN за шардом, Telegram отдал
        # 500) съедает обновление навсегда: на следующем проходе движения
        # источника уже «нет», и человек не узнает о пересчёте вовсе.
        if source_moved and sub.get("lists_updates") and not sub.get("code"):
            try:
                _send(token, int(chat), Reply(
                    f"🔔 МПГУ обновил конкурсные списки на epk25 "
                    f"({lists._hhmm_dd_mm(src)}).\n"
                    f"Посмотреть свои позиции: /spisok", []))
                sent_count[0] += 1
                sub["src"] = src
                changed = True
            except Exception as e:
                print(f"notify error {chat}: {e}")
                if "403" in str(e):
                    SUBS.pop(str(chat), None)
                    changed = True
                    print(f"подписка {chat} снята (бот заблокирован)")
            continue
        if not sub.get("code"):
            continue  # подписан только на обновление списков — кода нет
        if not source_moved and sub.get("updated_at") == upd:
            continue  # данные не менялись с прошлой сверки этого подписчика
        shard = lists.fetch_shard(sub["code"])
        if shard is None:
            continue  # сеть/CDN моргнули — src не трогаем, повторим в следующий проход
        entries = lists.lookup(shard, sub["code"])
        txt = follow.diff_text(sub["code"], sub.get("last") or {}, entries, meta)
        if txt is None and source_moved:
            # Списки пересчитали, а у человека ничего не сдвинулось. Это тоже
            # новость: молчание он читает как «данные не обновлялись». Дифф,
            # если он есть, сам начинается со слов «Списки обновились» —
            # поэтому второе сообщение сверху не шлём.
            txt = (f"🔔 МПГУ обновил списки ({lists._hhmm_dd_mm(src)}) — "
                   f"у вас по коду <b>{sub['code']}</b> без изменений.\n"
                   f"Подробнее: /spisok {sub['code']}")
        if not txt:
            # Сообщать нечего — отметку можно двигать сразу.
            sub["last"] = follow.positions_of(entries)
            sub["updated_at"] = upd
            if source_moved:
                sub["src"] = src
            changed = True
        if txt:
            try:
                _send(token, int(chat), Reply(txt, []))
                sent_count[0] += 1
                sub["last"] = follow.positions_of(entries)
                sub["updated_at"] = upd
                if source_moved:
                    sub["src"] = src
                changed = True
            except Exception as e:
                print(f"notify error {chat}: {e}")
                # 403 = человек заблокировал бота или удалил чат. Подписка иначе
                # висит вечно и на каждой проверке тратит запрос — снимаем её.
                if "403" in str(e):
                    SUBS.pop(str(chat), None)
                    changed = True
                    print(f"подписка {chat} снята (бот заблокирован)")
    print(f"check_subs: отправлено уведомлений {sent_count[0]}", flush=True)
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
    {"command": "plan", "description": "учебный план (дисциплины) по направлению"},
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
    "И отвечаю на свободные вопросы по Правилам приёма.\n"
    "Вопросы о работе бота: @soldat_olovyanniy")
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


def _content_type(filename: str) -> str:
    fn = filename.lower()
    if fn.endswith(".pdf"):
        return "application/pdf"
    if fn.endswith((".xlsx", ".xls")):
        return "application/vnd.ms-excel"
    return "text/csv"


def _send_document(token: str, chat_id: int, data: bytes, filename: str,
                   caption: str = ""):
    """sendDocument через multipart/form-data (стандартной библиотекой)."""
    boundary = "----mpguBotBoundary7351"
    parts = []
    for k, v in (("chat_id", str(chat_id)),
                 ("caption", caption), ("parse_mode", "HTML")):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                     f"name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    parts.append((f"--{boundary}\r\nContent-Disposition: form-data; "
                  f"name=\"document\"; filename=\"{filename}\"\r\n"
                  f"Content-Type: {_content_type(filename)}\r\n\r\n").encode())
    parts.append(data)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendDocument", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


_TG_LIMIT = 4000  # лимит Telegram 4096; берём с запасом на entity/эмодзи


def _split_text(text: str, limit: int = _TG_LIMIT) -> List[str]:
    """Режем длинный текст на части ≤limit по границам строк (наши <b>…</b>
    инлайновые и не пересекают перенос строки, поэтому разметка не рвётся)."""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:                 # одна строка длиннее лимита — рубим жёстко
            if cur:
                chunks.append(cur); cur = ""
            chunks.append(line[:limit]); line = line[limit:]
        if cur and len(cur) + 1 + len(line) > limit:
            chunks.append(cur); cur = ""
        cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def _send(token: str, chat_id: int, reply: Reply):
    if reply.document is not None:
        data, filename = reply.document
        _send_document(token, chat_id, data, filename, caption=reply.text)
        return
    if not reply.text:
        return  # тихий игнор (админ-команды от посторонних)
    chunks = _split_text(reply.text)
    mk = _markup(reply.keyboard)
    for i, chunk in enumerate(chunks):
        params = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML",
                  "disable_web_page_preview": "true"}
        if mk and i == len(chunks) - 1:          # клавиатуру — только к последней части
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
    warn = campaign.staleness_warning()
    if warn:
        print(warn, flush=True)
    else:
        print(f"Кампания: {campaign.CAMPAIGN}", flush=True)
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
    if FEEDBACK_PATH:
        FEEDBACK.extend(feedback.load(FEEDBACK_PATH))
        print(f"Записей обратной связи: {len(FEEDBACK)}")
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
