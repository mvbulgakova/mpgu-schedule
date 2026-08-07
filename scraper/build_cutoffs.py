"""Проходные баллы 2026 из отметок ВПП → JSON для бота.

Откуда берётся цифра. ВПП («высший проходной приоритет») — пометка epk25
«этот человек сейчас проходит»; минимальный балл среди отмеченных и есть
проходной. Считать его иначе нельзя: «балл N-го по силе» врёт, потому что
сильные уходят проходить туда, где у них приоритет выше, и место достаётся
тому, кто заметно ниже (2026: на «Истории и Воспитательной работе» при 24
местах и 2516 участниках проходной оказался 137).

Почему по ИСТОРИИ data-ветки. После зачисления МПГУ снимает отметки ВПП со
всех строк разом (2026-08-07 в 04:00 — по всем 99 общим бюджетным спискам
бакалавриата), и в свежем снимке считать уже нечего. Поэтому идём по
коммитам data назад и для каждого списка берём ПОСЛЕДНИЙ снимок, где отметки
ещё стояли: у большинства это 6 августа 19:12, у части — 7 августа.

Проверка, что снимок пойман верно: число отметок ВПП должно совпасть с «Мест
для зачисления» (seats_open), а НЕ с КЦП — там, где часть мест уже занята
приказом, epk25 отмечает ровно оставшиеся. В 2026 сошлось на 97 списках из 99.

Запуск: python -m scraper.build_cutoffs --data /tmp/data-wt [--commits 30]
"""
import argparse
import collections
import json
import subprocess
from pathlib import Path

OUT = Path(__file__).parent / "abitur" / "cutoffs_2026.json"


def _git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, check=True).stdout


def _snapshot(cwd, sha):
    """(строки по спискам, метаданные списков) на этом коммите."""
    files = _git(cwd, "ls-tree", "--name-only", f"{sha}:admissions/by_code").split()
    by = collections.defaultdict(list)
    for f in files:
        doc = json.loads(_git(cwd, "show", f"{sha}:admissions/by_code/{f}"))
        for code, entries in doc["codes"].items():
            for e in entries:
                by[e["list"]].append(dict(e, code=code))
    meta = json.loads(_git(cwd, "show", f"{sha}:admissions/lists_meta.json"))
    return by, meta


def collect(data_path: str, commits: int = 30):
    """[{list, cutoff, seats, ...}] — по последнему снимку с ВПП для каждого списка."""
    shas = _git(data_path, "log", "--format=%H", "origin/data", f"-{commits}").split()
    best, meta_all = {}, {}
    for sha in shas:
        by, meta = _snapshot(data_path, sha)
        stamp = meta["updated_at"]
        for lc, rows in by.items():
            if lc in best:
                continue
            vpp = [r for r in rows if r.get("vpp")]
            if vpp:
                best[lc] = (stamp, vpp)
                meta_all[lc] = meta["lists"].get(lc, {})
        print(f"  снимок {stamp[5:16]}: списков с ВПП накоплено {len(best)}", flush=True)
    out = []
    for lc, (stamp, vpp) in best.items():
        m = meta_all[lc]
        seats = m.get("seats_open")
        if seats is None:
            seats = m.get("kcp_epk")
        # БВИ-шники проходят вне конкурса баллов — по ним «проходной» не считают.
        scores = sorted((r["score_total"] for r in vpp
                         if not r.get("bvi") and r.get("score_total")))
        out.append({
            "list": lc, "direction": m.get("direction", ""), "form": m.get("form"),
            "kind": m.get("kind"), "level": m.get("level"), "unit": m.get("unit"),
            "vid_mest": m.get("vid_mest"), "kcp": m.get("kcp_epk"), "seats": seats,
            "vpp": len(vpp), "bvi": sum(1 for r in vpp if r.get("bvi")),
            "cutoff": scores[0] if scores else None,
            "top": scores[-1] if scores else None,
            # Снимок поймал список в момент пересчёта — цифра менее надёжна.
            "exact": len(vpp) == (seats or -1),
            "snapshot": stamp,
        })
    return sorted(out, key=lambda r: -(r["cutoff"] or 0))


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="/tmp/data-wt", help="рабочая копия ветки data")
    p.add_argument("--commits", type=int, default=30)
    args = p.parse_args(argv)
    rows = collect(args.data, args.commits)
    exact = sum(1 for r in rows if r["exact"])
    OUT.write_text(json.dumps({"source": "отметки ВПП epk25 (см. scraper/build_cutoffs.py)",
                               "lists": rows}, ensure_ascii=False), encoding="utf-8")
    print(f"ГОТОВО: списков {len(rows)}, из них с точным совпадением ВПП и мест "
          f"{exact} → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
