"""Офлайн-извлечение справочника магистратуры 2026 из текста приказа КЦП.

Вход: текст pk26_kcpspvomag.pdf (специализированные уровни ВО), извлечённый
pymupdf. Выход: scraper/abitur/programs_mag_2026.json — только бюджет
(КЦП); используется матчингом мест в scraper.abitur.lists, в каталог LLM
(shansy.load_programs) не попадает.

Запуск (однократно при обновлении кампании):
  python -m scraper.abitur.extract_programs_mag --kcp /tmp/pk26/kcp_spvomag.txt
"""
import argparse
import datetime as dt
import json
from pathlib import Path

from scraper.abitur.extract_programs import parse_kcp

OUT_PATH = Path(__file__).with_name("programs_mag_2026.json")

# Секции филиалов идут в конце приказа; их программы совпадают по названию с
# московскими — помечаем кампус прямо в названии, чтобы матчинг по словам их
# не путал (слова «покровский филиал» не встречаются в направлениях epk25).
_BRANCH_MARKERS = ["Покровский филиал"]


def extract(text: str) -> list:
    parts = [(None, text)]
    for marker in _BRANCH_MARKERS:
        head, sep, tail = parts[-1][1].partition(marker)
        if sep:
            parts[-1] = (parts[-1][0], head)
            parts.append((marker, tail))
    out = []
    for campus, chunk in parts:
        for e in parse_kcp(chunk):
            name = e["name"] + (f" ({campus})" if campus else "")
            out.append({"code": e["code"], "name": name, "form": e["form"],
                        "paid_only": False, "places": e["places"]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kcp", required=True)
    args = ap.parse_args()
    programs = extract(Path(args.kcp).read_text(encoding="utf-8"))
    doc = {"campaign": "2026/27",
           "source": "Приказ о КЦП МПГУ 2026 (специализированные уровни ВО)",
           "generated": dt.date.today().isoformat(),
           "programs": programs}
    OUT_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    total = sum(p["places"] for p in programs)
    print(f"программ: {len(programs)}; мест всего: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
