"""Чтение индекса конкурсных списков (с jsDelivr) и форматирование ответа."""
import json
import os
import time
import urllib.request
from typing import Dict, List, Optional

DATA_BASE = os.environ.get(
    "DATA_BASE", "https://cdn.jsdelivr.net/gh/mvbulgakova/mpgu-schedule@data")
_INDEX_PATH = "admissions/lists_index.json"
_CACHE = {"ts": 0.0, "data": None}
_TTL = 300  # секунд

_OFFICIAL = "https://epk25.mpgu.su/competitive-list"


def _norm(code: str) -> str:
    return "".join(ch for ch in (code or "") if ch.isdigit())


def fetch_index(force: bool = False) -> Optional[dict]:
    now = time.time()
    if not force and _CACHE["data"] is not None and now - _CACHE["ts"] < _TTL:
        return _CACHE["data"]
    try:
        req = urllib.request.Request(f"{DATA_BASE}/{_INDEX_PATH}",
                                     headers={"User-Agent": "MPGU-Abitur-Bot"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        _CACHE["data"], _CACHE["ts"] = data, now
        return data
    except Exception:
        return _CACHE["data"]


def lookup(index: dict, code: str) -> List[Dict]:
    return (index.get("codes") or {}).get(_norm(code), [])


def format_positions(index: dict, code: str) -> str:
    entries = lookup(index, code)
    updated = (index or {}).get("updated_at", "")
    lists = (index or {}).get("lists") or {}
    if not entries:
        return (f"Уникальный код <b>{_norm(code)}</b> не найден в индексе.\n"
                f"Проверьте номер или посмотрите официальные списки: {_OFFICIAL}\n"
                f"Данные обновляются периодически — возможна задержка.")
    lines = [f"🔎 <b>Ваши позиции по коду {_norm(code)}:</b>", ""]
    for e in entries:
        meta = lists.get(e["list"], {})
        name = meta.get("direction") or e["list"]
        flags = []
        if e.get("consent"):
            flags.append("согласие ✅")
        if e.get("bvi"):
            flags.append("БВИ")
        pri = f", приоритет {e['priority_pz']}" if e.get("priority_pz") is not None else ""
        tail = (" · " + ", ".join(flags)) if flags else ""
        lines.append(f"• <b>{name}</b>\n   место {e['position']}, "
                     f"баллы {e.get('score_total')}{pri} — {e.get('status') or '—'}{tail}")
    if updated:
        lines.append("")
        lines.append(f"Обновлено: {updated}")
    lines.append(f"Официальные списки: {_OFFICIAL}")
    lines.append("⚠️ Данные предварительные — ориентируйтесь на официальные списки и ЛК на Госуслугах.")
    return "\n".join(lines)
