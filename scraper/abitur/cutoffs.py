"""Проходные баллы 2026: поиск по направлению и вывод для бота.

Данные готовит scraper/build_cutoffs.py по официальным отметкам ВПП epk25 —
там же описано, почему считать «балл N-го по силе» нельзя и откуда берётся
последний снимок с отметками.

Читаем готовый JSON: бот живёт в GitHub Actions без доступа к истории
data-ветки, а цифры после зачисления больше не меняются.
"""
import json
import re
from pathlib import Path
from typing import List, Optional

_PATH = Path(__file__).with_name("cutoffs_2026.json")
_DATA: Optional[List[dict]] = None

_STOP = {"направленность", "образование", "профиль", "программа", "институт"}


def _words(s: str) -> set:
    return {w for w in re.findall(r"[а-яёa-z]{4,}", (s or "").lower())
            if w not in _STOP}


def load() -> List[dict]:
    global _DATA
    if _DATA is None:
        try:
            _DATA = json.loads(_PATH.read_text(encoding="utf-8")).get("lists", [])
        except Exception:
            _DATA = []
    return _DATA


_BACHELOR = "basic_higher_education"
_LEVEL_TAG = {"specialized_higher_education": " · магистратура",
              "magistracy": " · магистратура",
              "specialist": " · специалитет",
              "secondary_vocational_education": " · колледж"}


def budget(level: Optional[str] = None) -> List[dict]:
    """Только бюджет: «проходной» люди спрашивают именно про него.

    level ограничивает ступень. Смешивать бакалавриат с магистратурой в одном
    рейтинге нельзя: там своя шкала (вступительный экзамен вуза, не ЕГЭ), и
    в «самых доступных» вылезали магистерские 41–45 рядом с бакалаврскими 137.
    """
    return [r for r in load()
            if r.get("kind") == "бюджет" and r.get("cutoff")
            and (level is None or r.get("level") == level)]


def find(query: str, limit: int = 8) -> List[dict]:
    """Списки, подходящие под запрос: по коду направления или словам названия."""
    qw = _words(query)
    m = re.search(r"\d\d\.\d\d\.\d\d", query or "")
    code = m.group(0) if m else None
    scored = []
    for r in budget():
        if code and not (r.get("direction") or "").startswith(code):
            continue
        hay = _words(f"{r.get('direction')} {r.get('unit')}")
        overlap = len(qw & hay)
        if not overlap and not code:
            continue
        # Больше совпавших слов — выше; при равенстве очная форма выше заочной.
        form_rank = {"очная": 2, "очно-заочная": 1}.get(r.get("form"), 0)
        scored.append((overlap, form_rank, r.get("cutoff") or 0, r))
    scored.sort(key=lambda t: t[:3], reverse=True)
    # Отбираем по релевантности, а показываем по баллу: подборку читают, чтобы
    # СРАВНИТЬ направления, и вперемешку она нечитаема.
    return sorted((r for *_, r in scored[:limit]),
                  key=lambda r: -(r["cutoff"] or 0))


def _short(direction: str, maxlen: int = 58) -> str:
    d = re.sub(r"^\d\d\.\d\d\.\d\d\s*", "", direction or "")
    return d if len(d) <= maxlen else d[:maxlen - 1].rstrip(" ,./") + "…"


_FORM = {"очная": "", "очно-заочная": " · очно-заочная", "заочная": " · заочная"}


def format_entry(r: dict) -> str:
    line = (f"<b>{r['cutoff']}</b> — {_short(r.get('direction'))}"
            f"{_FORM.get(r.get('form'), '')}"
            f"{_LEVEL_TAG.get(r.get('level'), '')}")
    seats = r.get("seats")
    if seats:
        line += f"\n    мест {seats}"
        if r.get("bvi"):
            line += f", из них по БВИ {r['bvi']}"
    if not r.get("exact"):
        line += " · цифра приблизительная"
    return line


_HEAD = "📊 <b>Проходные баллы 2026</b> (предварительно)"

_METHOD = ("<i>Считано по отметкам ВПП на epk25 — это пометка вуза «сейчас "
           "проходит». Проходной = самый низкий балл среди отмеченных. "
           "Официальный ответ даёт приказ.</i>")


def format_results(rows: List[dict], query: str = "") -> str:
    if not rows:
        return (f"{_HEAD}\n\nНичего не нашёл по запросу «{query}». Попробуйте "
                f"короче: <b>биология</b>, <b>лингвистика</b>, <b>44.03.01</b>.")
    lines = [_HEAD, ""]
    lines += [f"• {format_entry(r)}" for r in rows]
    lines += ["", _METHOD]
    return "\n".join(lines)


def format_extremes(n: int = 7) -> str:
    """Обзорная карточка: самые высокие и самые низкие проходные."""
    rows = sorted(budget(_BACHELOR), key=lambda r: -r["cutoff"])
    if not rows:
        return f"{_HEAD}\n\nДанных пока нет."
    lines = [_HEAD, "",
             f"Бюджет, бакалавриат — {len(rows)} списков "
             f"(магистратура и колледж считаются по своей шкале, ищите по названию).",
             "", "<b>Самые высокие:</b>"]
    lines += [f"• {format_entry(r)}" for r in rows[:n]]
    lines += ["", "<b>Самые доступные:</b>"]
    lines += [f"• {format_entry(r)}" for r in rows[-n:][::-1]]
    lines += ["", "Напишите направление — покажу по нему.", "", _METHOD]
    return "\n".join(lines)
