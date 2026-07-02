"""Сборка истории проходных баллов по программам → data-ветка admissions/history.json.

build_history — чистая (строки лет + справочник программ → индекс). Матчинг программ
между годами: код + форма + пересечение слов направленности. Нематчи не теряются —
складываются в "unmatched" для ручного разбора.
"""
import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Dict, List

_STOP = {"направленность", "образование", "образовательная", "программа", "профиль"}


def _words(s: str) -> set:
    return {w for w in re.findall(r"[а-яёa-z]{4,}", (s or "").lower()) if w not in _STOP}


def _program_key(p: dict) -> str:
    return f"{p['code']}|{p['form']}|{p['name'][:48]}"


def build_history(rows: List[dict], programs: List[dict]) -> dict:
    """rows: [{year, code, program, form, passing, competition}]; programs: справочник."""
    hist: Dict[str, dict] = {}
    unmatched: List[dict] = []
    by_code_form: Dict[tuple, List[dict]] = {}
    for p in programs:
        by_code_form.setdefault((p["code"], p["form"]), []).append(p)

    for r in rows:
        cands = by_code_form.get((r["code"], r["form"]), [])
        rw = _words(r["program"])
        scored = sorted(((len(rw & _words(p["name"])), p) for p in cands),
                        key=lambda t: -t[0])
        best = None
        if len(cands) == 1 and scored and scored[0][0] >= 1:
            best = scored[0][1]
        elif scored and scored[0][0] >= 2 and (
                len(scored) == 1 or scored[0][0] > scored[1][0]):
            # строгий однозначный лидер: точность важнее покрытия —
            # склеить историю чужой программы хуже, чем не показать её
            best = scored[0][1]
        if best is None:
            unmatched.append(r)
            continue
        key = _program_key(best)
        entry = hist.setdefault(key, {"code": best["code"], "name": best["name"],
                                      "form": best["form"], "history": {}})
        entry["history"][str(r["year"])] = r["passing"]

    for entry in hist.values():
        years = sorted(int(y) for y in entry["history"])
        last3 = years[-3:]
        vals3 = [entry["history"][str(y)] for y in last3]
        entry["range3"] = [min(vals3), max(vals3)] if vals3 else None
        entry["last"] = [years[-1], entry["history"][str(years[-1])]] if years else None

    return {"generated": dt.date.today().isoformat(),
            "programs": hist,
            "unmatched": unmatched}


def main() -> int:
    from scraper.fetchers.history_fetcher import collect_history_pages
    from scraper.parsers.passing_score_parser import parse_score_table
    from scraper.storage.git_storage import GitStorage

    programs = json.loads(
        (Path(__file__).parent / "abitur" / "programs_2026.json")
        .read_text(encoding="utf-8"))["programs"]

    pages = collect_history_pages()
    rows: List[dict] = []
    for year, html in pages.items():
        got = parse_score_table(html, year)
        print(f"{year}: {len(got)} строк")
        rows.extend(got)

    doc = build_history(rows, programs)
    matched = len(doc["programs"])
    print(f"итого: программ с историей {matched}, нематчей {len(doc['unmatched'])}")

    storage = GitStorage(os.environ.get("DATA_PATH", "data"))
    storage.write_admissions_history(doc)
    storage.commit_and_push(
        f"admissions: история проходных ({doc['generated']}, {matched} программ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
