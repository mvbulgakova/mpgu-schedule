"""Калькулятор шансов: подбор программ по своим ЕГЭ + живые списки + история.

Детерминированный. LLM не участвует. Никаких обещаний — только факты и диапазоны.
"""
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_PROGRAMS_PATH = Path(__file__).with_name("programs_2026.json")

DATA_BASE = os.environ.get(
    "DATA_BASE", "https://cdn.jsdelivr.net/gh/mvbulgakova/mpgu-schedule@data")
_HISTORY_PATH = "admissions/history.json"
_HCACHE = {"ts": 0.0, "data": None}
_TTL = 3600

# Канонические предметы ЕГЭ → алиасы для разбора сообщения.
SUBJECT_ALIASES: Dict[str, List[str]] = {
    "русский язык": ["русский", "рус", "русск"],
    "математика (профильная)": ["математика", "матем", "мат", "профильная", "профиль"],
    "обществознание": ["обществознание", "общество", "общага", "общ", "обществознанию"],
    "история": ["история", "ист"],
    "иностранный язык": ["иностранный", "английский", "англ", "иняз", "немецкий",
                         "французский", "китайский"],
    "литература": ["литература", "литра", "лит"],
    "биология": ["биология", "био"],
    "химия": ["химия", "хим"],
    "физика": ["физика", "физ"],
    "информатика": ["информатика", "информ", "икт"],
    "география": ["география", "гео"],
}
_ALIAS_TO_CANON = {a: canon for canon, als in SUBJECT_ALIASES.items() for a in als}
for c in SUBJECT_ALIASES:
    _ALIAS_TO_CANON[c] = c


def parse_scores(text: str) -> Optional[Dict[str, int]]:
    """«русский 78, общество 84 история 90» → {канонический предмет: балл}."""
    if not text:
        return None
    tokens = re.findall(r"[а-яёa-z()]+|\d+", text.lower())
    scores: Dict[str, int] = {}
    pending: Optional[str] = None
    for tok in tokens:
        if tok.isdigit():
            val = int(tok)
            if pending is None or not (0 < val <= 100):
                return None
            scores[pending] = val
            pending = None
        else:
            canon = _ALIAS_TO_CANON.get(tok)
            if canon:
                pending = canon
    if len(scores) < 2 or "русский язык" not in scores:
        return None
    return scores


def _canon_subject(alt: str) -> Optional[str]:
    """Название альтернативы из слота → канонический предмет ЕГЭ (или None для ДВИ/ВИ)."""
    low = alt.lower()
    if "испытание" in low:
        return None
    for canon in SUBJECT_ALIASES:
        head = canon.split()[0][:6]
        if head in low:
            return canon
    return None


def load_programs() -> List[dict]:
    return json.loads(_PROGRAMS_PATH.read_text(encoding="utf-8"))["programs"]


def match_programs(scores: Dict[str, int], programs: List[dict]) -> List[dict]:
    """Программы, у которых каждый ЕГЭ-слот закрывается предметом абитуриента.

    Слот с ДВИ пропускается при подсчёте суммы, программа помечается need_dvi.
    """
    out = []
    for p in programs:
        total = 0
        used: List[Tuple[str, int]] = []
        need_dvi = False
        ok = True
        for slot in p["exam_slots"]:
            canon_alts = [(_canon_subject(a), a) for a in slot]
            dvi_only = all(c is None for c, _ in canon_alts)
            if dvi_only:
                need_dvi = True
                continue
            best = max((scores.get(c, -1) for c, _ in canon_alts if c), default=-1)
            if best < 0:
                ok = False
                break
            total += best
            used.append((next(c for c, _ in canon_alts if c and scores.get(c, -1) == best),
                         best))
        if not ok:
            continue
        out.append({"program": p, "total": total, "used": used,
                    "need_dvi": need_dvi or p.get("dvi", False)})
    out.sort(key=lambda m: (-(m["program"].get("places") or 0), -m["total"]))
    return out


def fetch_history(force: bool = False) -> Optional[dict]:
    now = time.time()
    if not force and _HCACHE["data"] is not None and now - _HCACHE["ts"] < _TTL:
        return _HCACHE["data"]
    try:
        req = urllib.request.Request(f"{DATA_BASE}/{_HISTORY_PATH}",
                                     headers={"User-Agent": "MPGU-Abitur-Bot"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        _HCACHE["data"], _HCACHE["ts"] = data, now
        return data
    except Exception:
        return _HCACHE["data"]


_STOP = {"направленность", "образование", "педагогическое"}


def _words(s: str) -> set:
    return {w for w in re.findall(r"[а-яё]{4,}", (s or "").lower()) if w not in _STOP}


def _find_history(p: dict, history: Optional[dict]) -> Optional[dict]:
    if not history:
        return None
    cands = [v for v in (history.get("programs") or {}).values()
             if v["code"] == p["code"] and v["form"] == p["form"]]
    pw = _words(p["name"])
    scored = sorted(((len(pw & _words(v["name"])), v) for v in cands), key=lambda t: -t[0])
    if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]) and scored[0][0] >= 1:
        return scored[0][1]
    return None


def _find_live(p: dict, lists_meta: Optional[dict], total: int) -> Optional[str]:
    """Строка о живом (бюджетном) списке epk25 для программы.

    Одна программа обычно имеет несколько списков (общий конкурс + квоты) с почти
    одинаковым названием направления. Матч считаем надёжным, только если ВСЕ значимые
    слова программы присутствуют в названии направления (подмножество) — это исключает
    подмену другой программой. Среди совпавших берём общий конкурс — самый многочисленный
    список (квоты всегда малочисленны). Оценка позиции — ориентир, не гарантия.
    """
    if not lists_meta:
        return None
    metas = lists_meta.get("lists") or {}
    pw = _words(p["name"])
    if len(pw) < 2:  # слишком короткое имя — не рискуем ложным матчем
        return None
    cands = []
    for _code_list, m in metas.items():
        d = m.get("direction") or ""
        if not d.startswith(p["code"]):
            continue
        if m.get("kind") == "платное":
            continue
        if m.get("form") and m["form"] != p.get("form"):
            continue
        if pw <= _words(d):  # все слова программы есть в направлении
            cands.append(m)
    if not cands:
        return None
    m = max(cands, key=lambda x: x.get("count") or 0)  # общий конкурс — самый большой
    totals = m.get("totals") or []
    if not totals:
        return None
    pos = 1 + sum(1 for t in totals if t > total)
    return (f"в списке (общий конкурс) {len(totals)} чел.; с суммой {total} ты был бы "
            f"примерно на {pos}-м месте (лучший результат сейчас: {totals[0]})")


def format_answer(matches: List[dict], history: Optional[dict],
                  lists_meta: Optional[dict], scores: Dict[str, int],
                  limit: int = 5) -> str:
    if not matches:
        return ("По присланным предметам подходящих программ не нашлось. Проверьте "
                "формат: «русский 78, обществознание 84, история 90». Перечень ВИ по "
                "программам: https://mpgu.su/postuplenie/")
    lines = ["🧮 <b>Подбор по твоим ЕГЭ</b> "
             f"({', '.join(f'{k} {v}' for k, v in scores.items())}):", ""]
    for m in matches[:limit]:
        p = m["program"]
        head = f"• <b>{p['code']} {p['name']}</b> ({p['form']}"
        head += f", мест: {p['places']}" if p.get("places") else ", только платно"
        head += ")"
        lines.append(head)
        lines.append(f"   Твоя сумма по ВИ программы: {m['total']}"
                     + (" + ДВИ (сдаётся дополнительно!)" if m["need_dvi"] else ""))
        live = _find_live(p, lists_meta, m["total"])
        if live:
            lines.append(f"   Живые списки: {live}")
        h = _find_history(p, history)
        if h and h.get("history"):
            yrs = sorted(h["history"])
            hist_s = ", ".join(f"{y}: {h['history'][y]}" for y in yrs)
            lines.append(f"   Проходной прошлых лет: {hist_s}")
        lines.append("")
    lines.append("⚠️ Это ориентир, а не гарантия: проходной-2026 станет известен только "
                 "после зачисления. Данные списков обновляются периодически. "
                 "Официальные списки: https://epk25.mpgu.su/competitive-list")
    return "\n".join(lines)


def answer(text: str, *, lists_meta: Optional[dict] = None,
           history: Optional[dict] = None) -> str:
    scores = parse_scores(text)
    if scores is None:
        return ("Пришлите предметы и баллы одним сообщением, например:\n"
                "<b>русский 78, обществознание 84, история 90</b>\n"
                "(обязательно укажите русский; баллы 1–100)")
    matches = match_programs(scores, load_programs())
    return format_answer(matches, history, lists_meta, scores)
