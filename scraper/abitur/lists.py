"""Чтение шардированного индекса конкурсных списков (jsDelivr) и форматирование.

admissions/lists_meta.json    — метаданные списков (направление/форма/вид/totals)
admissions/by_code/<XX>.json  — позиции абитуриентов (шард по первым 2 цифрам кода)
"""
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


def _general_seats(m: dict, places: int):
    """(мест в общем конкурсе сейчас, квотных). Общий = КЦП − квоты (если известны).

    Если места взяты прямо со страницы epk25 (kcp_from_epk) — это уже общий
    конкурс (квоты там отдельными списками), вычитать ничего не нужно."""
    if m.get("kcp_from_epk"):
        return places, None
    quota = _quota_for(m)
    if quota is None:
        return places, None
    return max(places - quota, 0), quota


def _history_for(m: dict) -> Optional[dict]:
    """История проходных программы этого списка ({год: балл}) или None.

    Матчим направление списка на каталог (тот же надёжный матчинг, что и места),
    затем ищем запись истории по имени каталога (build_admissions пишет туда
    именно каталожные имена)."""
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


def _consent_caveat(entries: List[Dict], lists_meta_all: dict) -> str:
    """Честная оговорка: оценка основана на подавших согласие СЕЙЧАС, а их пока мало."""
    share = ""
    for e in entries:
        m = lists_meta_all.get(e["list"], {})
        if m.get("general") and m.get("consented") is not None and m.get("count"):
            pct = round(100 * m["consented"] / m["count"]) if m["count"] else 0
            share = (f" В этом списке согласие подали пока лишь {m['consented']} "
                     f"из {m['count']} (~{pct}%).")
            break
    return ("⚠️ <b>Это очень предварительно.</b>" + share + " Большинство подаёт "
            "согласие ближе к <b>5 августа</b> — конкурентов станет больше, и позиция, "
            "скорее всего, ухудшится. Не расслабляйтесь и не понижайте приоритеты, "
            "которые действительно хотите.")


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
        elif m.get("general") and places and sim_above is not None:
            sim_place = sim_above + 1
            seats, _q = _general_seats(m, places)
            ok = sim_place <= seats
            lines.append(f"{'✅' if ok else '⏳'} {pri} · ~{sim_place}-е из {seats} · {name}")
            if ok:
                passing.append((e.get("priority_pz") or 99, name, sim_place, seats))
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
    budget = [e for e in entries
              if lists_meta_all.get(e["list"], {}).get("kind") == "бюджет"]
    if budget and not consented:
        lines.append("⚠️ Согласие на зачисление не отмечено — на основном этапе "
                     "нужно до <b>5 августа 12:00</b>")
    upd = (meta or {}).get("updated_at", "")
    if upd:
        lines.append(f"<i>Обновлено: {upd[11:16]} {upd[8:10]}.{upd[5:7]}</i>")
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
            if general:
                places = m["places"] if "places" in m else _places_for(m)
                sim_above = e.get("sim_above")
                if places and sim_above is not None:
                    any_places = any_sim = True
                    sim_place = sim_above + 1
                    seats, quota = _general_seats(m, places)
                    ok = sim_place <= seats
                    seats_s = (f"{seats} (общий конкурс; +{quota} квотных к КЦП {places})"
                               if quota else f"{seats}")
                    parts.append(f"с согласием: ~{sim_place}-е из {seats_s} "
                                 f"{'✅' if ok else '⏳'}")
                    if ok:
                        passing.append((e.get("priority_pz") or 99,
                                        m.get("direction") or name, sim_place, seats,
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
                # «Вид мест» со страницы (если есть) точнее наших догадок
                parts.append(m.get("vid_mest") or "особый вид мест")
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
    elif any_places:
        lines.append("⏳ Пока вы ниже черты во всех бюджетных списках. Но согласий подано "
                     "мало — расклад ещё сильно поменяется; и после приоритетного этапа "
                     "в конкурс вернутся незанятые квотные места.")
    if any_sim:
        lines.append("ℹ️ Как считается: учитываются только подавшие согласие, и кто "
                     "проходит на свой более высокий приоритет — из конкурса убираются. "
                     "«Мест» — в общем конкурсе сейчас (КЦП минус квоты); незанятые "
                     "квотные вернутся после приоритетного этапа (приказы 3 августа). "
                     "На Госуслугах видно текущее число мест общего конкурса.")
    elif any_places:
        lines.append("ℹ️ «Мест» — в общем конкурсе (КЦП минус квоты). Незанятые квотные "
                     "места вернутся в общий конкурс после приоритетного этапа (3 августа).")
    # Напоминание про согласие: главная причина «пролететь» на зачислении.
    # Показываем, если есть бюджетные позиции и ни в одной согласие не отмечено.
    lists_meta = (meta or {}).get("lists") or {}
    budget = [e for e in entries
              if lists_meta.get(e["list"], {}).get("kind") == "бюджет"]
    if budget and not any(e.get("consent") for e in budget):
        lines.append("")
        lines.append("⚠️ <b>В бюджетных списках согласие на зачисление не отмечено.</b> "
                     "Без согласия зачислить не могут: на основном этапе его нужно подать "
                     "до <b>5 августа 12:00</b> (отметка на Госуслугах или заявление в ПК). "
                     "Если уже подали — обновление могло ещё не дойти до списков.")
    if updated:
        lines.append("")
        lines.append(f"Обновлено: {updated}")
    lines.append(f"Официальные списки: {_OFFICIAL}")
    lines.append("⚠️ Данные предварительные — ориентируйтесь на официальные списки и ЛК на Госуслугах.")
    return "\n".join(lines)
