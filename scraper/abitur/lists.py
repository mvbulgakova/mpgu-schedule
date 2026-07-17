"""Чтение шардированного индекса конкурсных списков (jsDelivr) и форматирование.

admissions/lists_meta.json    — метаданные списков (направление/форма/вид/totals)
admissions/by_code/<XX>.json  — позиции абитуриентов (шард по первым 2 цифрам кода)
"""
import json
import os
import time
import urllib.request
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


def _list_label(meta: Optional[dict], list_code: str) -> str:
    m = ((meta or {}).get("lists") or {}).get(list_code, {})
    name = m.get("direction") or list_code
    extras = [x for x in (m.get("form"), m.get("kind")) if x]
    return f"{name} ({', '.join(extras)})" if extras else name


_PLACES_CACHE: Dict[tuple, Optional[int]] = {}


def _places_for(m: dict) -> Optional[int]:
    """Бюджетные места (КЦП) программы для списка epk25; None, если матч ненадёжен.

    Тот же безопасный матчинг, что в /shansy: слова программы — подмножество слов
    направления, код и форма совпадают; при неоднозначности мест не показываем.
    """
    direction, form = m.get("direction") or "", m.get("form") or ""
    key = (direction, form)
    if key in _PLACES_CACHE:
        return _PLACES_CACHE[key]
    places = None
    try:
        from scraper.abitur import shansy
        code = direction.split()[0] if direction else ""
        dw = shansy._words(direction)
        cands = [p for p in shansy.load_programs()
                 if p["code"] == code and p.get("form") == form
                 and shansy._words(p["name"]) and shansy._words(p["name"]) <= dw]
        vals = {p.get("places") for p in cands}
        if len(vals) == 1:
            places = vals.pop()
    except Exception:
        places = None
    _PLACES_CACHE[key] = places
    return places


def _is_general_budget(lists_meta: dict, list_code: str) -> bool:
    """Список — общий конкурс (не квотный)? Общий = крупнейший бюджетный список
    своего направления+формы; квотные списки того же направления всегда меньше."""
    m = lists_meta.get(list_code, {})
    if m.get("kind") != "бюджет":
        return False
    same = [x for x in lists_meta.values()
            if x.get("kind") == "бюджет" and x.get("direction") == m.get("direction")
            and x.get("form") == m.get("form")]
    counts = [x.get("count") or 0 for x in same]
    return not counts or (m.get("count") or 0) >= max(counts)


def format_positions(meta: Optional[dict], shard: Optional[dict], code: str) -> str:
    entries = lookup(shard, code)
    updated = (meta or {}).get("updated_at", "") or (shard or {}).get("updated_at", "")
    if not entries:
        return (f"Уникальный код <b>{_norm(code)}</b> не найден в индексе.\n"
                f"Проверьте номер или посмотрите официальные списки: {_OFFICIAL}\n"
                f"Данные обновляются периодически — возможна задержка.")
    lists_meta_all = (meta or {}).get("lists") or {}
    lines = [f"🔎 <b>Ваши позиции по коду {_norm(code)}:</b>", ""]
    passing: List[tuple] = []      # (приоритет, направление) — где сейчас «в зелёной зоне»
    any_places = False
    for e in entries:
        m = lists_meta_all.get(e["list"], {})
        name = _list_label(meta, e["list"])
        count = m.get("count")
        parts = [f"место {e['position']}" + (f" из {count}" if count else "")]
        if m.get("kind") == "бюджет":
            if _is_general_budget(lists_meta_all, e["list"]):
                places = _places_for(m)
                if places:
                    any_places = True
                    ok = e["position"] <= places
                    parts.append(f"мест: {places} {'✅' if ok else '⏳'}")
                    if ok:
                        passing.append((e.get("priority_pz") or 99,
                                        m.get("direction") or name))
            else:
                parts.append("квотный список")
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
        passing.sort()
        pri, nm = passing[0]
        lines.append(f"🎯 <b>Сейчас проходите на: {nm}</b> (приоритет {pri}) — "
                     "если списки не изменятся.")
    elif any_places:
        lines.append("⏳ Пока вы ниже черты во всех бюджетных списках. Это не приговор: "
                     "не все выше вас подадут согласие, а после приоритетного этапа "
                     "в конкурс вернутся незанятые квотные места.")
    if any_places:
        lines.append("ℹ️ «Мест» — все бюджетные места программы (КЦП): часть сейчас "
                     "зарезервирована под квоты, их незаполненный остаток вернётся в "
                     "общий конкурс после приоритетного этапа (приказы 3 августа).")
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
