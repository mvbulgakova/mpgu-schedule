"""Офлайн-извлечение справочника программ 2026 из текстов официальных PDF.

Вход (тексты, извлечённые pymupdf):
  --programs  текст Приложения 1 (перечень программ и ВИ)
  --kcp       текст КЦП (бюджетные места)
Выход: scraper/abitur/programs_2026.json (коммитится в репозиторий).

Запуск (однократно при обновлении кампании):
  python -m scraper.abitur.extract_programs \
      --programs /tmp/pk26/programmy.txt --kcp /tmp/pk26/kcp_bvo.txt
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

_CODE_RE = re.compile(r"^(\d{2}\.\d{2}\.\d{2})\s*(.*)")
_FORM_RE = re.compile(r"^(очная|очно-заочная|заочная)\b", re.I)
_SLOT_RE = re.compile(r"^([123])\.\s*(.*)")
_HEADER_RE = re.compile(r"(факультет|^Институт |^Высшая школа|^Академия)", re.I)
_DUR_RE = re.compile(r"^\d+\s*(год|года|лет)|^\d+\s*месяцев|^месяцев", re.I)

OUT_PATH = Path(__file__).with_name("programs_2026.json")


def _clean_alt(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" .;")
    return s


def _split_slot(raw: str) -> List[str]:
    raw = re.sub(r"\s*/\s*", "/", re.sub(r"\s+", " ", raw)).strip()
    return [a for a in (_clean_alt(x) for x in raw.split("/")) if a]


def parse_programs(text: str) -> List[dict]:
    lines = [ln.strip() for ln in text.splitlines()]
    progs: List[dict] = []
    i = 0
    # начинаем после заголовка секции
    for j, ln in enumerate(lines):
        if "Базовые уровни" in ln:
            i = j + 1
            break
    cur: Optional[dict] = None
    mode = "idle"           # idle|name|slots|skip_spo
    slot_group = 0
    slot_raw: List[str] = []

    def flush_slot():
        nonlocal slot_raw
        if cur is not None and slot_raw and slot_group == 1:
            cur["exam_slots"].append(_split_slot(" ".join(slot_raw)))
        slot_raw = []

    def close_program():
        nonlocal cur
        if cur is not None:
            flush_slot()
            if cur["exam_slots"]:
                progs.append(cur)
        cur = None

    while i < len(lines):
        ln = lines[i]
        i += 1
        if not ln:
            continue
        m = _CODE_RE.match(ln)
        if m:
            close_program()
            name0 = m.group(2).strip()
            cur = {"code": m.group(1), "name_parts": [name0] if name0 else [],
                   "form": None, "exam_slots": [], "paid_only": False, "dvi": False}
            mode, slot_group = "name", 0
            continue
        if _HEADER_RE.search(ln) and mode in ("skip_spo", "idle"):
            close_program()
            mode = "idle"
            continue
        if cur is None:
            continue
        if mode == "name":
            fm = _FORM_RE.match(ln)
            if fm:
                cur["form"] = fm.group(1).lower()
                mode = "await_slots"
            else:
                cur["name_parts"].append(ln)
            continue
        if mode == "await_slots":
            if _DUR_RE.match(ln):
                continue
            sm = _SLOT_RE.match(ln)
            if sm:
                mode, slot_group = "slots", 1
                slot_raw = [sm.group(2)]
            continue
        if mode == "slots":
            sm = _SLOT_RE.match(ln)
            if sm:
                if sm.group(1) == "1" and slot_raw:
                    # вторая нумерованная группа = колонка СПО → пропускаем
                    flush_slot()
                    mode, slot_group = "skip_spo", 2
                    continue
                flush_slot()
                slot_raw = [sm.group(2)]
            else:
                slot_raw.append(ln)
            continue
        # skip_spo: ждём следующий код программы (обрабатывается выше)

    close_program()

    out = []
    for p in progs:
        name = re.sub(r"\s+", " ", " ".join(p["name_parts"])).strip(" ,")
        paid = "*" in name
        name = name.replace("*", "").strip()
        dvi = any("испытание" in a.lower() for slot in p["exam_slots"] for a in slot)
        out.append({"code": p["code"], "name": name, "form": p["form"] or "очная",
                    "exam_slots": p["exam_slots"], "paid_only": paid, "dvi": dvi,
                    "places": None})
    return out


def parse_kcp(text: str) -> List[dict]:
    lines = [ln.strip() for ln in text.splitlines()]
    entries: List[dict] = []
    cur: Optional[dict] = None
    mode = "idle"
    for ln in lines:
        if not ln:
            continue
        m = _CODE_RE.match(ln)
        if m:
            cur = {"code": m.group(1), "name_parts": [m.group(2).strip()],
                   "form": None, "places": None}
            mode = "name"
            continue
        if cur is None:
            continue
        if mode == "name":
            fm = _FORM_RE.match(ln)
            if fm:
                cur["form"] = fm.group(1).lower()
                mode = "places"
            else:
                cur["name_parts"].append(ln)
            continue
        if mode == "places":
            if _DUR_RE.match(ln):
                continue
            if re.fullmatch(r"\d{1,4}", ln):
                cur["places"] = int(ln)
                cur["name"] = re.sub(r"\s+", " ", " ".join(cur["name_parts"])).strip(" ,")
                entries.append(cur)
                cur, mode = None, "idle"
            continue
    return entries


_STOP = {"направленность", "образовательная", "программа", "профиль", "выбору"}


def _words(s: str) -> set:
    return {w for w in re.findall(r"[а-яёa-z]{4,}", s.lower()) if w not in _STOP}


def match_kcp(programs: List[dict], kcp: List[dict]) -> List[str]:
    """Проставляет places; возвращает список нематчей для ручной проверки."""
    unmatched = []
    for p in programs:
        cands = [k for k in kcp if k["code"] == p["code"] and k["form"] == p["form"]]
        if not cands:
            if not p["paid_only"]:
                unmatched.append(f"{p['code']} {p['form']} | {p['name'][:60]}")
            continue
        if len(cands) == 1:
            p["places"] = cands[0]["places"]
            continue
        pw = _words(p["name"])
        best = max(cands, key=lambda k: len(pw & _words(k["name"])))
        score = len(pw & _words(best["name"]))
        if score == 0:
            unmatched.append(f"{p['code']} {p['form']} | {p['name'][:60]} (score=0)")
        else:
            p["places"] = best["places"]
    return unmatched


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--programs", required=True)
    ap.add_argument("--kcp", required=True)
    args = ap.parse_args()

    programs = parse_programs(Path(args.programs).read_text(encoding="utf-8"))
    kcp = parse_kcp(Path(args.kcp).read_text(encoding="utf-8"))
    unmatched = match_kcp(programs, kcp)

    doc = {"campaign": "2026/27",
           "source": "Приложение 1 к Правилам приёма МПГУ + КЦП-2026",
           "generated": dt.date.today().isoformat(),
           "programs": programs}
    OUT_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"программ: {len(programs)}; КЦП-записей: {len(kcp)}; "
          f"с местами: {sum(1 for p in programs if p['places'])}")
    if unmatched:
        print("НЕ СМАТЧЕНЫ С КЦП (проверить вручную):", file=sys.stderr)
        for u in unmatched:
            print("  " + u, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
