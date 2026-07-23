"""Офлайн-предпарсинг семестровой разбивки учебных планов → JSON для бота.

Бот не имеет pymupdf/fitz, поэтому семестры разбираем заранее: скачиваем PDF
каждого плана из карты study_plans_2026.json, извлекаем «дисциплина → семестры»
(scraper.parsers.study_plan_semesters) и кладём в study_plan_semesters_2026.json
под ключом share_id плана. Бот читает готовый JSON.

Запуск (однократно/при обновлении планов):
  python -m scraper.build_study_plan_semesters [--levels бакалавр,базовое,спец]
"""
import argparse
import datetime as dt
import io
import json
import re
import time
import urllib.request
import zipfile
from pathlib import Path

from scraper.abitur import study_plans as SP
from scraper.parsers.study_plan_semesters import parse_pdf_bytes

OUT = Path(__file__).parent / "abitur" / "study_plan_semesters_2026.json"
_DEFAULT_LEVELS = ("базовое высшее", "бакалавриат", "специалитет")


def _download_pdf(url: str, retries: int = 4) -> bytes:
    # oc.mpgu.su сбрасывает соединение при частых запросах — вежливо ретраим.
    req = urllib.request.Request(url.rstrip("/") + "/download",
                                 headers={"User-Agent": "MPGU-Abitur-Bot"})
    content = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                content = r.read()
            break
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    z = zipfile.ZipFile(io.BytesIO(content))
    pdfs = [n for n in z.namelist() if n.lower().endswith(".pdf")]
    if not pdfs:
        raise ValueError("нет PDF в архиве")
    best = max(pdfs, key=lambda n: (re.search(r"(20\d\d)", n) or ["0"])[0]
               if re.search(r"(20\d\d)", n) else "0")
    return z.read(best)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default=",".join(_DEFAULT_LEVELS),
                    help="подстроки уровней образования через запятую")
    args = ap.parse_args()
    levels = [x.strip().lower() for x in args.levels.split(",") if x.strip()]

    plans = [p for p in SP.load_plans()
             if any(lv in (p.get("level") or "").lower() for lv in levels)]
    print(f"планов к разбору: {len(plans)}", flush=True)

    result, ok, fail = {}, 0, 0
    for i, p in enumerate(plans, 1):
        sid = SP.share_id(p)
        try:
            rows = parse_pdf_bytes(_download_pdf(SP.share_url(p)))
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  ! {p['code']} {p['profile'][:30]}: {e}", flush=True)
            continue
        if rows:
            result[sid] = rows
            ok += 1
        else:
            fail += 1
        time.sleep(0.4)                       # вежливая пауза между скачиваниями
        if i % 25 == 0:
            print(f"  ...{i}/{len(plans)} (ок {ok}, пусто/ошибка {fail})", flush=True)

    doc = {"generated": dt.date.today().isoformat(),
           "source": "учебные планы МПГУ (.plx→PDF), семестры по столбцам контроля",
           "plans": result}
    OUT.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(f"ГОТОВО: планов с семестрами {ok}, без {fail} → {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
