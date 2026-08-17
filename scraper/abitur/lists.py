"""Чтение шардированного индекса конкурсных списков (jsDelivr) и форматирование.

admissions/lists_meta.json    — метаданные списков (направление/форма/вид/totals)
admissions/by_code/<XX>.json  — позиции абитуриентов (шард по первым 2 цифрам кода)
"""
import datetime as dt
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

# Первичный источник — raw.githubusercontent (кэш ~5 мин: важно для уведомлений
# об изменении позиций); jsDelivr — фолбэк (кэширует ветку до 12 часов).
DATA_BASE = os.environ.get(
    "DATA_BASE", "https://raw.githubusercontent.com/mvbulgakova/mpgu-schedule/data")
_FALLBACK_BASE = "https://cdn.jsdelivr.net/gh/mvbulgakova/mpgu-schedule@data"
_TTL = 300  # секунд

_META_CACHE = {"ts": 0.0, "data": None}
_SHARD_CACHE: Dict[str, dict] = {}

_OFFICIAL = "https://epk25.mpgu.su/competitive-list"


def _norm(code: str) -> str:
    return "".join(ch for ch in (code or "") if ch.isdigit())


def _get_json(path: str) -> Optional[dict]:
    bases = [DATA_BASE]
    if _FALLBACK_BASE != DATA_BASE:
        bases.append(_FALLBACK_BASE)
    for base in bases:
        try:
            req = urllib.request.Request(f"{base}/{path}",
                                         headers={"User-Agent": "MPGU-Abitur-Bot"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            continue
    return None


def fetch_meta(force: bool = False) -> Optional[dict]:
    now = time.time()
    if not force and _META_CACHE["data"] is not None and now - _META_CACHE["ts"] < _TTL:
        return _META_CACHE["data"]
    data = _get_json("admissions/lists_meta.json")
    if data is not None:
        _META_CACHE["data"], _META_CACHE["ts"] = data, now
        return data
    return _META_CACHE["data"]


_HIST_CACHE = {"ts": 0.0, "data": None}
_HIST_TTL = 3600


def fetch_history(force: bool = False) -> Optional[dict]:
    now = time.time()
    if not force and _HIST_CACHE["data"] is not None and now - _HIST_CACHE["ts"] < _HIST_TTL:
        return _HIST_CACHE["data"]
    data = _get_json("admissions/history.json")
    if data is not None:
        _HIST_CACHE["data"], _HIST_CACHE["ts"] = data, now
        return data
    return _HIST_CACHE["data"]


# обратная совместимость по имени (использовалась ботом)
def fetch_index(force: bool = False) -> Optional[dict]:
    return fetch_meta(force)


def fetch_shard(unique_code: str) -> Optional[dict]:
    c = _norm(unique_code)
    key = c[:2] if len(c) >= 2 else c.zfill(2)
    now = time.time()
    cached = _SHARD_CACHE.get(key)
    if cached and now - cached["ts"] < _TTL:
        return cached["data"]
    data = _get_json(f"admissions/by_code/{key}.json")
    if data is not None:
        _SHARD_CACHE[key] = {"ts": now, "data": data}
        return data
    return cached["data"] if cached else None


def lookup(shard: Optional[dict], code: str) -> List[Dict]:
    if not shard:
        return []
    return (shard.get("codes") or {}).get(_norm(code), [])


def _branch(m: dict) -> Optional[str]:
    """Филиал (если список не головного кампуса) — у филиала свой КЦП и конкурс,
    а название направления совпадает с московским, поэтому это важно показать."""
    unit = m.get("unit") or ""
    return unit if "филиал" in unit.lower() else None


def _list_label(meta: Optional[dict], list_code: str) -> str:
    m = ((meta or {}).get("lists") or {}).get(list_code, {})
    name = m.get("direction") or list_code
    br = _branch(m)
    if br:
        name = f"{name} — {br}"
    extras = [x for x in (m.get("form"), m.get("kind")) if x]
    return f"{name} ({', '.join(extras)})" if extras else name


_PLACES_CACHE: Dict[tuple, Optional[int]] = {}

_ALIAS_PATH = Path(__file__).with_name("list_aliases_2026.json")
_MAG_PATH = Path(__file__).with_name("programs_mag_2026.json")
_ALIASES: Optional[dict] = None
_MAG: Optional[List[dict]] = None


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _aliases() -> dict:
    """{"dir": направление→программа, "code": код списка→программа} (нормализовано)."""
    global _ALIASES
    if _ALIASES is None:
        by_dir, by_code = {}, {}
        try:
            doc = json.loads(_ALIAS_PATH.read_text(encoding="utf-8"))
            for a in doc.get("aliases", []):
                if a.get("list_code"):
                    by_code[a["list_code"]] = _norm_text(a["program"])
                else:
                    by_dir[_norm_text(a["direction"])] = _norm_text(a["program"])
        except Exception:
            pass
        _ALIASES = {"dir": by_dir, "code": by_code}
    return _ALIASES


def alias_list_codes() -> set:
    """Коды списков с ручной привязкой по коду (нужны build_lists_index)."""
    return set(_aliases()["code"])


def _mag_programs() -> List[dict]:
    """Магистратура (бюджет): отдельный каталог только для матчинга мест."""
    global _MAG
    if _MAG is None:
        try:
            doc = json.loads(_MAG_PATH.read_text(encoding="utf-8"))
            _MAG = doc.get("programs", [])
        except Exception:
            _MAG = []
    return _MAG


def _list_code_of(m: dict) -> str:
    mm = re.search(r"code=(\d+)", m.get("url") or "")
    return mm.group(1) if mm else ""


def _match_programs(direction: str, form: str, paid: bool,
                    list_code: str = "") -> List[dict]:
    """Программы каталога, надёжно соответствующие списку epk25.

    1. Ручная привязка (list_aliases_2026.json) по коду списка — когда у двух
       списков одинаковое направление+форма (Москва и филиал) — или по
       направлению: сокращённые/обрезанные названия на epk25, где матчинг
       по словам бессилен.
    2. Иначе — слова программы ⊆ слов направления; кандидаты, чьи слова —
       СТРОГОЕ подмножество слов другого кандидата, отбрасываются: короткое
       имя («История») совпало «заодно» с объединённой конкурсной группой
       («История и Воспитательная работа/…»), а не наоборот.
    """
    from scraper.abitur import shansy
    code = direction.split()[0] if direction else ""
    progs = [p for p in shansy.load_programs() + _mag_programs()
             if p["code"] == code and p.get("form") == form
             and bool(p.get("paid_only")) == paid]
    al = _aliases()
    alias = al["code"].get(list_code) or al["dir"].get(_norm_text(direction))
    if alias:
        hit = [p for p in progs if _norm_text(p["name"]) == alias]
        if hit:
            return hit
    dw = shansy._words(direction)
    ws = [(p, shansy._words(p["name"])) for p in progs
          if shansy._words(p["name"]) and shansy._words(p["name"]) <= dw]
    return [p for p, w in ws if not any(w < w2 for _, w2 in ws)]


def _places_for(m: dict) -> Optional[int]:
    """Места программы для списка epk25; None, если матч ненадёжен.

    Для бюджетных списков — КЦП (places), для платных — договорные места РФ
    (paid_places). При неоднозначности мест не показываем (см. _match_programs).
    """
    direction, form = m.get("direction") or "", m.get("form") or ""
    paid = (m.get("kind") == "платное")
    lc = _list_code_of(m)
    key = (direction, form, paid, lc)
    if key in _PLACES_CACHE:
        return _PLACES_CACHE[key]
    places = None
    try:
        field = "paid_places" if paid else "places"
        vals = {p.get(field)
                for p in _match_programs(direction, form, paid, list_code=lc)}
        if len(vals) == 1:
            places = vals.pop()
    except Exception:
        places = None
    _PLACES_CACHE[key] = places
    return places


_QUOTA_CACHE: Dict[tuple, Optional[int]] = {}


def _quota_for(m: dict) -> Optional[int]:
    """Мест под квотами (особая+отдельная) у программы бюджетного списка; None если неизвестно."""
    direction, form = m.get("direction") or "", m.get("form") or ""
    lc = _list_code_of(m)
    key = (direction, form, lc)
    if key in _QUOTA_CACHE:
        return _QUOTA_CACHE[key]
    q = None
    try:
        vals = {p.get("quota_places")
                for p in _match_programs(direction, form, paid=False,
                                         list_code=lc)}
        if len(vals) == 1:
            q = vals.pop()
    except Exception:
        q = None
    _QUOTA_CACHE[key] = q
    return q


def source_updated_at(meta: Optional[dict]) -> Optional[str]:
    """Когда САМ вуз последний раз пересчитывал списки (максимум page_updated_at).

    Не путать с meta["updated_at"] — это момент нашего обхода. Списки на epk25
    пересчитываются вразнобой (2026-08-05: 325 списков стояли на 08:00, часть
    уже на 09:50), поэтому «когда обновились списки» — самый свежий из них.
    """
    stamps = [m.get("page_updated_at") for m in ((meta or {}).get("lists") or {}).values()
              if m.get("page_updated_at")]
    return max(stamps) if stamps else None


def source_updated_for(meta: Optional[dict], list_codes) -> Optional[str]:
    """Когда вуз пересчитывал ИМЕННО эти списки (максимум их page_updated_at).

    Глобальный максимум конкретному человеку врёт. epk25 переписывает списки
    волнами по десяткам минут: 2026-08-05 в 22:17 у 325 списков стояло 20:00,
    у 135 — 21:10, а самый свежий был 21:50. Человеку с кодом 1914288 при этом
    показали «обновлены 21:50», хотя все 13 ЕГО списков стояли на 20:00 —
    время чужого списка, к его местам отношения не имеющее.
    """
    lst = ((meta or {}).get("lists") or {})
    stamps = [(lst.get(c) or {}).get("page_updated_at") for c in (list_codes or [])]
    stamps = [s for s in stamps if s]
    return max(stamps) if stamps else None


def _hhmm_dd_mm(ts: str) -> str:
    """'2026-08-05T09:50:00+03:00' → '09:50 05.08'."""
    return f"{ts[11:16]} {ts[8:10]}.{ts[5:7]}"


def _general_seats(m: dict, places: int):
    """(мест в общем конкурсе сейчас, квотных). Общий = КЦП − квоты (если известны).

    «Мест для зачисления» (seats_open) со страницы epk25 — это уже КЦП минус
    зачисленных приказом, т.е. буквально сколько мест разыгрывается сейчас;
    оно авторитетнее любого расчёта из КЦП (проверено 2026-08-05: на
    бакалавриате число официальных отметок ВПП совпадает с seats_open на 97
    списках из 99, а с полным КЦП — только на 70).

    Если места взяты прямо со страницы epk25 (kcp_from_epk) — это уже общий
    конкурс (квоты там отдельными списками), вычитать ничего не нужно."""
    seats_open = m.get("seats_open")
    if seats_open is not None:
        return seats_open, None
    if m.get("kcp_from_epk"):
        return places, None
    quota = _quota_for(m)
    if quota is None:
        return places, None
    return max(places - quota, 0), quota


def enrollment_done(m: dict) -> bool:
    """Зачисление по этому списку уже проведено — конкурса больше нет.

    Признак со страницы epk25: «Зачислено» сравнялось с КЦП. 2026-08-07 в
    04:00 так стало на ВСЕХ 99 общих бюджетных списках бакалавриата разом
    (2155 из 2155), поле «Мест для зачисления» опустело, а отметки ВПП сняли
    у всех до единого.

    Без этой проверки бот продолжал считать конкурс живым и говорил человеку
    «прошли бы на Физика и Информатика (~40-е из 67)» по списку, где уже
    зачислены все 67 и у него самого никакого ВПП нет. Симуляция по КЦП
    формально считается — но отвечает на вопрос, которого больше не существует.
    """
    kcp = m.get("kcp_epk")
    enrolled = m.get("enrolled")
    return bool(kcp) and enrolled is not None and enrolled >= kcp


def _level_of(entries: List[Dict], lists_meta: dict) -> Optional[str]:
    """Ступень по спискам человека — от неё зависят сроки платного этапа."""
    for e in entries:
        lvl = (lists_meta.get(e["list"]) or {}).get("level")
        if lvl:
            return lvl
    return None


def _enrollment_done_note(entries: List[Dict], done_lists: List[dict]) -> str:
    """Что писать, когда конкурс по спискам человека уже закрыт.

    Категоричного вердикта не выносим: приказ на mpgu.su — единственный
    официальный документ, а epk25 показал результат раньше него. Наше дело —
    честно назвать состояние страниц и не выдавать симуляцию за прогноз.
    """
    n = len(done_lists)
    level = (done_lists[0] or {}).get("level") if done_lists else None
    return (
        f"🎓 <b>Бюджетное зачисление завершено</b> — по "
        f"{'вашему списку' if n == 1 else 'вашим спискам'} места заняты.\n"
        f"<b>Проверьте себя в приказе</b> от 7 августа на mpgu.su: это "
        f"единственный официальный ответ. Тем, кто в него попал, ночью пришло "
        f"уведомление на Госуслугах.\n"
        f"По конкурсным спискам сказать, кто зачислен, нельзя: отметки ВПП "
        f"epk25 снял у всех, когда конкурс закрылся, а зачисленных в самих "
        f"строках он не помечает.\n\n"
        + paid_stage_note(level=level))


def _history_for(m: dict) -> Optional[dict]:
    """История проходных программы этого списка ({год: балл}) или None.

    Матчим направление списка на каталог (тот же надёжный матчинг, что и места),
    затем ищем запись истории по имени каталога (build_admissions пишет туда
    именно каталожные имена).

    Для филиалов истории не даём: название направления совпадает с московским,
    но конкурс совсем другой (свой КЦП, обычно ниже проходной) — подставить
    московские проходные значило бы дать неверный ориентир."""
    if _branch(m):
        return None
    try:
        progs = _match_programs(m.get("direction") or "", m.get("form") or "",
                                paid=False, list_code=_list_code_of(m))
        if len(progs) != 1:
            return None
        target = _norm_text(progs[0]["name"])
        doc = fetch_history()
        for v in (doc or {}).get("programs", {}).values():
            if _norm_text(v.get("name", "")) == target:
                return v.get("history")
    except Exception:
        return None
    return None


def _prediction_line(m: dict) -> Optional[str]:
    """Однострочный (многострочный) блок прогноза проходного для списка."""
    from scraper.abitur import prediction
    return prediction.format_prediction(
        _history_for(m), m.get("sim_cutoff"), m.get("cap"), m.get("general_seats"))


_MSK = dt.timezone(dt.timedelta(hours=3))
# Правила приёма МПГУ 2026, разд. 6.2 (бюджет БВО/бакалавриат/специалитет).
_MAIN_CONSENT_DEADLINE = dt.datetime(2026, 8, 5, 12, 0, tzinfo=_MSK)
_EXTRA_CONSENT_DEADLINE = dt.datetime(2026, 8, 9, 12, 0, tzinfo=_MSK)
# Приказы основного этапа опубликованы 7 августа. После этого «приказы будут
# 7 августа» в будущем времени — уже не подсказка, а дезинформация.
_MAIN_ORDERS_PUBLISHED = dt.datetime(2026, 8, 7, 14, 0, tzinfo=_MSK)
# У магистратуры бюджетный этап ЦЕЛИКОМ другой и на три недели позже (Сроки
# приёма, п. 6.5): списки 23 августа, согласие до 24 августа 12:00, приказы
# 25-го, дополнительный этап 26–27 августа. 2026-08-17 магистрантке с живым
# конкурсом и отметкой ВПП бот написал «приказы на бюджет опубликованы
# (7 августа), официальный ответ только в нём» — то есть отправил сдаваться
# за неделю до её собственного дедлайна согласия.
_MAG_CONSENT_DEADLINE = dt.datetime(2026, 8, 24, 12, 0, tzinfo=_MSK)
_MAG_EXTRA_CONSENT_DEADLINE = dt.datetime(2026, 8, 26, 12, 0, tzinfo=_MSK)
_MAG_ORDERS_PUBLISHED = dt.datetime(2026, 8, 25, 14, 0, tzinfo=_MSK)
# Платный приём идёт своим чередом и заканчивается позже бюджетного: договор
# и оплата первого семестра до 27 августа 18:00, приказ по платникам ОДИН на
# всех — 29 августа (Правила приёма, раздел 6).
_PAID_CONTRACT_DEADLINE = dt.datetime(2026, 8, 27, 18, 0, tzinfo=_MSK)
_PAID_ORDER_DATE = dt.datetime(2026, 8, 29, 0, 0, tzinfo=_MSK)
# У магистратуры и специализированного высшего СВОИ сроки, на день-два позже
# (Сроки приёма, п. 6.7): договор до 28 августа 18:00, приказ 31 августа.
# Показать магистранту бакалаврские 27/29 — значит назвать не ту дату в
# единственном месте, где дата решает всё.
_MAG_LEVELS = {"specialized_higher_education", "magistracy"}


def budget_stage(level=None) -> dict:
    """Сроки бюджетного этапа для ступени. Тексты рядом с датами намеренно:
    разъехавшаяся дата и подпись к ней — самая дорогая ошибка в этом боте."""
    if level in _MAG_LEVELS:
        return {"consent": _MAG_CONSENT_DEADLINE, "consent_txt": "24 августа 12:00",
                "extra": _MAG_EXTRA_CONSENT_DEADLINE, "extra_txt": "26 августа 12:00",
                "orders": _MAG_ORDERS_PUBLISHED, "orders_txt": "25 августа"}
    return {"consent": _MAIN_CONSENT_DEADLINE, "consent_txt": "5 августа 12:00",
            "extra": _EXTRA_CONSENT_DEADLINE, "extra_txt": "9 августа 12:00",
            "orders": _MAIN_ORDERS_PUBLISHED, "orders_txt": "7 августа"}
_PAID_CONTRACT_DEADLINE_MAG = dt.datetime(2026, 8, 28, 18, 0, tzinfo=_MSK)
_PAID_ORDER_DATE_MAG = dt.datetime(2026, 8, 31, 0, 0, tzinfo=_MSK)


def paid_stage_note(short: bool = False, level: Optional[str] = None) -> str:
    """Что сейчас происходит с платными местами.

    Бюджетное зачисление на бакалавриате закончилось, и для тех, кто не
    прошёл, единственный живой путь — платное. Сроки там другие и позже, а из
    бюджетных текстов этого не видно: человек читает «приказы 7 августа» и
    решает, что всё.
    """
    mag = level in _MAG_LEVELS
    deadline = _PAID_CONTRACT_DEADLINE_MAG if mag else _PAID_CONTRACT_DEADLINE
    order = _PAID_ORDER_DATE_MAG if mag else _PAID_ORDER_DATE
    d_txt = "28 августа 18:00" if mag else "27 августа 18:00"
    o_txt = "31 августа" if mag else "29 августа"
    now = _now_msk()
    if now >= order:
        return (f"💳 Приказ о зачислении на платные места ({o_txt}) "
                f"опубликован — смотрите его на mpgu.su.")
    if now >= deadline:
        return (f"💳 Приём договоров на платные места закрыт ({d_txt}). "
                f"Приказ — <b>{o_txt}</b>.")
    if short:
        return (f"💳 <b>Идёт зачисление на платные места:</b> договор и оплата "
                f"до <b>{d_txt}</b>, приказ <b>{o_txt}</b>.")
    return (f"💳 <b>Сейчас идёт зачисление на платные места.</b>\n"
            f"Договор и оплата первого семестра — до <b>{d_txt} мск</b>. "
            f"Приказ по платным местам один на всех и выходит <b>{o_txt}</b>, "
            f"поэтому «ещё не зачислен» до этой даты — это норма, а не отказ.\n"
            f"Обращаться в приёмную комиссию своего института.")


def _now_msk() -> dt.datetime:
    """Отдельной функцией — чтобы тесты могли встать в нужный момент кампании."""
    return dt.datetime.now(_MSK)


def _no_consent_warning(short: bool, level: Optional[str] = None) -> str:
    """Напоминание про согласие. После закрытия этапа зовёт на следующий.

    Звать «подайте до 5 августа 12:00» после 5 августа 12:00 — вредный совет:
    человек решит, что всё пропало, хотя остаётся дополнительный этап. И даты
    берём по ступени: у магистратуры этап на три недели позже.
    """
    st = budget_stage(level)
    now = _now_msk()
    if now >= st["extra"]:
        return ("⚠️ Согласие на зачисление не отмечено, приём согласий "
                "завершён — зачисление возможно только при дополнительном приёме.")
    if now >= st["consent"]:
        if short:
            return (f"⚠️ Согласие не отмечено. Основной этап закрыт, остался "
                    f"дополнительный — до <b>{st['extra_txt']}</b>")
        return (f"⚠️ <b>В бюджетных списках согласие на зачисление не отмечено.</b> "
                f"Приём согласий на основном этапе закрыт ({st['consent_txt']}). "
                f"Остаётся дополнительный этап: согласие до <b>{st['extra_txt']}</b>, "
                f"если после приказов {st['orders_txt']} останутся места. Если вы "
                f"уже подавали — обновление могло ещё не дойти до списков.")
    if short:
        return (f"⚠️ Согласие на зачисление не отмечено — на основном этапе "
                f"нужно до <b>{st['consent_txt']}</b>")
    return (f"⚠️ <b>В бюджетных списках согласие на зачисление не отмечено.</b> "
            f"Без согласия зачислить не могут: на основном этапе его нужно подать "
            f"до <b>{st['consent_txt']}</b> (отметка на Госуслугах или заявление "
            f"в ПК). Если уже подали — обновление могло ещё не дойти до списков.")


def _consent_caveat(entries: List[Dict], lists_meta_all: dict) -> str:
    """Честная оговорка про предварительность оценки.

    До закрытия приёма согласий главный риск — что конкурентов станет больше.
    После дедлайна это уже неправда: новых согласий на основном этапе не
    будет, и обещание «их станет больше» в самый нервный день кампании просто
    дезинформирует. Поэтому текст зависит от момента И от ступени: у
    магистратуры дедлайн 24 августа, а не 5-го.
    """
    share = ""
    for e in entries:
        m = lists_meta_all.get(e["list"], {})
        if m.get("general") and m.get("consented") is not None and m.get("count"):
            pct = round(100 * m["consented"] / m["count"]) if m["count"] else 0
            share = (f" Согласие в этом списке подали {m['consented']} "
                     f"из {m['count']} (~{pct}%).")
            break
    st = budget_stage(_level_of(entries, lists_meta_all))
    now = _now_msk()
    if now >= st["orders"]:
        return (f"⚠️ <b>Приказы о зачислении на бюджет опубликованы</b> "
                f"({st['orders_txt']})." + share + f" Оценка ниже — "
                f"предварительная и к приказу отношения не имеет: официальный "
                f"ответ только в нём.")
    if now >= st["consent"]:
        return (f"⚠️ <b>Приём согласий на основном этапе закрыт</b> "
                f"({st['consent_txt']})." + share + f" Списки ещё "
                f"пересчитываются, пока вуз обрабатывает поданные согласия, так "
                f"что позиция может сдвинуться. Приказы о зачислении — "
                f"<b>{st['orders_txt']}</b>.")
    return (f"⚠️ <b>Это очень предварительно.</b>" + share + f" Большинство подаёт "
            f"согласие ближе к дедлайну (<b>{st['consent_txt']}</b>) — конкурентов "
            f"станет больше, и позиция, скорее всего, ухудшится. Не расслабляйтесь "
            f"и не понижайте приоритеты, которые действительно хотите.")


def _is_general_budget(lists_meta: dict, list_code: str) -> bool:
    """Список — общий конкурс? Приоритет — факту со страницы epk25 («Вид мест:
    основные места в рамках КЦП»); он же различает филиалы (у каждого свой КЦП).
    Если факта нет — прежняя эвристика «крупнейший список направления+формы»."""
    m = lists_meta.get(list_code, {})
    if m.get("kind") != "бюджет":
        return False
    if "main_kcp" in m:
        return bool(m["main_kcp"])
    if m.get("vid_mest"):
        return "основные места" in m["vid_mest"].lower()
    same = [x for x in lists_meta.values()
            if x.get("kind") == "бюджет" and x.get("direction") == m.get("direction")
            and x.get("form") == m.get("form")]
    counts = [x.get("count") or 0 for x in same]
    return not counts or (m.get("count") or 0) >= max(counts)


_BOILERPLATE = ("Педагогическое образование (с двумя профилями подготовки).",
                "Педагогическое образование.",
                "Психолого-педагогическое образование.",
                "Специальное (дефектологическое) образование.")


def _short_name(direction: str, maxlen: int = 42) -> str:
    """Компактное имя направления: без кода и типового префикса, с обрезкой."""
    import re as _re
    s = _re.sub(r"^\d{2}\.\d{2}\.\d{2}\s*", "", direction or "").strip()
    for b in _BOILERPLATE:
        if s.startswith(b):
            s = s[len(b):].strip()
            break
    return (s[:maxlen - 1] + "…") if len(s) > maxlen else s


_FORM_SHORT = {"очная": "", "заочная": " (заоч)", "очно-заочная": " (оч-заоч)"}


def format_positions_short(meta: Optional[dict], shard: Optional[dict],
                           code: str) -> str:
    """Компактная сводка: строка на список + вердикт. Детали — по кнопке."""
    entries = lookup(shard, code)
    if not entries:
        return format_positions(meta, shard, code)   # «не найден» и так короткий
    lists_meta_all = (meta or {}).get("lists") or {}
    consented = any(e.get("consent") for e in entries
                    if lists_meta_all.get(e["list"], {}).get("kind") == "бюджет")
    n = len(entries)
    word = ("список" if n % 10 == 1 and n % 100 != 11 else
            "списка" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else
            "списков")
    lines = [f"🔎 <b>Код {_norm(code)}</b> — {n} {word}:", ""]
    passing: List[tuple] = []
    done_lists: List[dict] = []
    entries_sorted = sorted(entries, key=lambda e: (e.get("priority_pz") or 99,))
    for e in entries_sorted:
        m = lists_meta_all.get(e["list"], {})
        br = _branch(m)
        name = _short_name(m.get("direction") or e["list"],
                           maxlen=30 if br else 42) + \
            _FORM_SHORT.get(m.get("form") or "", "") + \
            (f" · {br.replace(' филиал', ' ф-л')}" if br else "")
        pri = f"П{e['priority_pz']}" if e.get("priority_pz") is not None else "—"
        places = m.get("places")
        sim_above = e.get("sim_above")
        if m.get("kind") == "платное":
            pp = _places_for(m)
            pp_s = f" · мест {pp}" if pp else ""
            lines.append(f"💳 {pri} · {e['position']}/{m.get('count', '?')}{pp_s} · {name}")
        elif m.get("general") and enrollment_done(m):
            # Конкурс закончился: показываем факт, а не симуляцию.
            done_lists.append(m)
            mark = "🎓" if e.get("vpp") else "▫️"
            lines.append(f"{mark} {pri} · зачислено {m.get('enrolled')}/"
                         f"{m.get('kcp_epk')} — места заняты · {name}")
        elif m.get("general") and places and sim_above is not None:
            sim_place = sim_above + 1
            seats, _q = _general_seats(m, places)
            # ВПП — официальная отметка epk25 (кто реально проходит сейчас,
            # с учётом чужих приоритетов), точнее нашей внутренней симуляции
            # (см. 2026-08-04: sim_place может быть заметно пессимистичнее
            # даже на свежих данных). Если она стоит у самого человека —
            # его настоящее место среди подтверждённых — vpp_above+1, а не
            # sim_place; иначе используем sim_place как раньше.
            vpp = e.get("vpp")
            vpp_above = e.get("vpp_above")
            shown_place = vpp_above + 1 if vpp and vpp_above is not None else sim_place
            ok = bool(vpp) or sim_place <= seats
            vpp_tag = " ✓ВПП" if vpp else ""
            # Показываем ОБА числа: место в списке и оценку с согласием.
            # Иначе человек видит на epk25 «60», у нас «~33-е» и не понимает,
            # которое из них правда (реальный вопрос от абитуриентки). Разница
            # ровно в тех, кто выше без согласия: она их пересчитала руками —
            # 27 — и сошлось с нашим cons_above.
            lines.append(f"{'✅' if ok else '⏳'} {pri} · {e['position']}-е в списке "
                         f"→ ~{shown_place}-е из {seats} с согласием{vpp_tag} · {name}")
            if ok:
                passing.append((e.get("priority_pz") or 99, name, shown_place, seats))
        elif not m.get("general") and m.get("kind") == "бюджет" and "general" in m:
            lines.append(f"▫️ {pri} · квота · {e['position']}/{m.get('count', '?')} · {name}")
        else:
            lines.append(f"▫️ {pri} · {e['position']}/{m.get('count', '?')} · {name}")
    lines.append("")
    if passing:
        passing.sort(key=lambda t: t[0])
        _, nm, sim_place, seats = passing[0]
        lines.append(f"📊 <b>Будь приём сейчас — прошли бы на: {nm}</b> "
                     f"(~{sim_place}-е из {seats})")
        lines.append(_consent_caveat(entries, lists_meta_all))
        lines.append("Подробнее — «📋 Подробнее».")
    elif done_lists:
        lines.append(_enrollment_done_note(entries, done_lists))
    elif any(lists_meta_all.get(e["list"], {}).get("kind") == "платное"
             for e in entries) and _now_msk() >= _MAIN_ORDERS_PUBLISHED:
        # У кого бюджетных списков нет вовсе, done-заметка не покажется, а
        # сроки по платному он не знает ниоткуда: они позже бюджетных.
        lines.append(paid_stage_note(short=True, level=_level_of(entries, lists_meta_all)))
    budget = [e for e in entries
              if lists_meta_all.get(e["list"], {}).get("kind") == "бюджет"]
    if budget and not consented:
        lines.append(_no_consent_warning(
            short=True, level=_level_of(entries, lists_meta_all)))
    upd = (meta or {}).get("updated_at", "")
    # По спискам ЭТОГО человека, а не по всем 667: epk25 переписывает их
    # волнами, и глобальный максимум — время чужого списка.
    src = source_updated_for(meta, [e["list"] for e in entries])
    if src:
        # Две разные даты, и путать их нельзя: вуз мог не пересчитывать списки
        # полсуток, и тогда свежий обход всё равно показывает старую картину.
        lines.append(f"<i>Ваши списки на epk25 обновлены: {_hhmm_dd_mm(src)}</i>")
    if upd:
        lines.append(f"<i>Мы сверялись: {_hhmm_dd_mm(upd)}</i>")
    return "\n".join(lines)


def format_positions(meta: Optional[dict], shard: Optional[dict], code: str) -> str:
    entries = lookup(shard, code)
    updated = (meta or {}).get("updated_at", "") or (shard or {}).get("updated_at", "")
    if not entries:
        return (f"Уникальный код <b>{_norm(code)}</b> не найден в индексе.\n"
                f"Проверьте номер или посмотрите официальные списки: {_OFFICIAL}\n"
                f"Данные обновляются периодически — возможна задержка.")
    lists_meta_all = (meta or {}).get("lists") or {}
    lines = [f"🔎 <b>Ваши позиции по коду {_norm(code)}:</b>", ""]
    passing: List[tuple] = []      # (приоритет, направление, sim_place|None)
    any_places = False
    any_sim = False
    done_lists: List[dict] = []
    consented = any(e.get("consent") for e in entries
                    if lists_meta_all.get(e["list"], {}).get("kind") == "бюджет")
    for e in entries:
        m = lists_meta_all.get(e["list"], {})
        name = _list_label(meta, e["list"])
        count = m.get("count")
        parts = [f"место {e['position']}" + (f" из {count}" if count else "")]
        if m.get("kind") == "бюджет":
            general = m["general"] if "general" in m else \
                _is_general_budget(lists_meta_all, e["list"])
            if general and enrollment_done(m):
                # Конкурс закрыт — симуляция отвечает на несуществующий вопрос.
                done_lists.append(m)
                parts.append(f"зачислено {m.get('enrolled')}/{m.get('kcp_epk')} "
                             f"— места заняты" + (" · у вас ✓ВПП" if e.get("vpp") else ""))
            elif general:
                places = m["places"] if "places" in m else _places_for(m)
                sim_above = e.get("sim_above")
                if places and sim_above is not None:
                    any_places = any_sim = True
                    sim_place = sim_above + 1
                    seats, quota = _general_seats(m, places)
                    vpp = e.get("vpp")
                    vpp_above = e.get("vpp_above")
                    shown_place = vpp_above + 1 if vpp and vpp_above is not None else sim_place
                    ok = bool(vpp) or sim_place <= seats
                    seats_s = (f"{seats} (общий конкурс; +{quota} квотных к КЦП {places})"
                               if quota else f"{seats}")
                    vpp_s = " ✓ВПП" if vpp else ""
                    parts.append(f"с согласием: ~{shown_place}-е из {seats_s}{vpp_s} "
                                 f"{'✅' if ok else '⏳'}")
                    if ok:
                        passing.append((e.get("priority_pz") or 99,
                                        m.get("direction") or name, shown_place, seats,
                                        e["list"]))
                elif places:
                    any_places = True
                    seats, quota = _general_seats(m, places)
                    ok = e["position"] <= seats
                    parts.append(f"мест: {seats} {'✅' if ok else '⏳'}")
                    if ok:
                        passing.append((e.get("priority_pz") or 99,
                                        m.get("direction") or name, None, seats,
                                        e["list"]))
            else:
                # Квотный список — тоже бюджет и тоже конкурс, просто свой:
                # у него собственные места, и человеку важно видеть позицию.
                label = m.get("vid_mest") or "особый вид мест"
                qp = m.get("kcp_epk")
                if qp:
                    ok = e["position"] <= qp
                    parts.append(f"{label}: место {e['position']} из {qp} "
                                 f"{'✅' if ok else '⏳'}")
                else:
                    parts.append(label)
        elif m.get("kind") == "платное":
            pp = _places_for(m)
            if pp:
                parts.append(f"мест (РФ): {pp}")
        parts.append(f"баллы {e.get('score_total')}")
        if e.get("priority_pz") is not None:
            parts.append(f"приоритет {e['priority_pz']}")
        flags = []
        if e.get("consent"):
            flags.append("согласие ✅")
        if e.get("bvi"):
            flags.append("БВИ")
        status = e.get("status") or ""
        if status and "участвует" not in status.lower():
            flags.append(status)
        tail = (" · " + ", ".join(flags)) if flags else ""
        lines.append(f"• <b>{name}</b>\n   {' · '.join(parts)}{tail}")
    lines.append("")
    if passing:
        passing.sort(key=lambda t: t[0])
        pri, nm, sim_place, seats, plist = passing[0]
        detail = f", ~{sim_place}-е из {seats}" if sim_place else ""
        lines.append(f"📊 <b>Если бы приём закончился ПРЯМО СЕЙЧАС, вы бы прошли на: "
                     f"{nm}</b> (приоритет {pri}{detail}).")
        lines.append(_consent_caveat(entries, lists_meta_all))
        pred = _prediction_line(lists_meta_all.get(plist, {}))
        if pred:
            lines.append(pred)
    elif done_lists:
        lines.append(_enrollment_done_note(entries, done_lists))
    elif any(lists_meta_all.get(e["list"], {}).get("kind") == "платное"
             for e in entries) and _now_msk() >= _MAIN_ORDERS_PUBLISHED:
        lines.append(paid_stage_note(level=_level_of(entries, lists_meta_all)))
    elif any_places:
        lines.append("⏳ Пока вы ниже черты во всех бюджетных списках. Но согласий подано "
                     "мало — расклад ещё сильно поменяется; и после приоритетного этапа "
                     "в конкурс вернутся незанятые квотные места.")
    if any_sim and not done_lists:
        lines.append("ℹ️ Как считается: учитываются только подавшие согласие, и кто "
                     "проходит на свой более высокий приоритет — из конкурса убираются. "
                     "«Мест» — в общем конкурсе сейчас (КЦП минус квоты); незанятые "
                     "квотные вернутся после приоритетного этапа (приказы 3 августа). "
                     "На Госуслугах видно текущее число мест общего конкурса.")
    elif any_places and not done_lists:
        lines.append("ℹ️ «Мест» — в общем конкурсе (КЦП минус квоты). Незанятые квотные "
                     "места вернутся в общий конкурс после приоритетного этапа (3 августа).")
    # Напоминание про согласие: главная причина «пролететь» на зачислении.
    # Показываем, если есть бюджетные позиции и ни в одной согласие не отмечено.
    lists_meta = (meta or {}).get("lists") or {}
    budget = [e for e in entries
              if lists_meta.get(e["list"], {}).get("kind") == "бюджет"]
    if budget and not any(e.get("consent") for e in budget):
        lines.append("")
        lines.append(_no_consent_warning(
            short=False, level=_level_of(entries, lists_meta_all)))
    src_full = source_updated_for(meta, [e["list"] for e in entries])
    if src_full:
        lines.append("")
        lines.append(f"Ваши списки на epk25 обновлены: {_hhmm_dd_mm(src_full)}")
    if updated:
        if not src_full:
            lines.append("")
        lines.append(f"Мы сверялись: {updated}")
    lines.append(f"Официальные списки: {_OFFICIAL}")
    lines.append("⚠️ Данные предварительные — ориентируйтесь на официальные списки и ЛК на Госуслугах.")
    return "\n".join(lines)
