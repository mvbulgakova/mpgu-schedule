"""Проходные баллы 2026 из ПРИКАЗОВ о зачислении → cutoffs_2026.json.

Раньше проходные считались по отметкам ВПП на epk25 («этот сейчас проходит»).
Это была оценка: снимок за девять часов до приказа. Теперь есть сами приказы,
где перечислены реально зачисленные с баллами, — это и есть проходной без
оговорок. Сверка методов: из 91 сопоставленной группы общего конкурса 79
совпали точь-в-точь, остальные разошлись на 2–16 баллов.

Виды конкурса считаются РАЗДЕЛЬНО: у общего конкурса, особой и отдельной
квоты свои места и свои проходные, и смешивать их — всё равно что смешивать
разные вузы. В квоты не берём зачисленных по БВИ: у них в приказе пустые
графы баллов (или заполнена одна ИД), они прошли вне конкурса и утянули бы
порог к нулю. 2026: в отдельной квоте таких 70 из 288.

Запуск: python -m scraper.build_cutoffs
"""
import io
import json
import re
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from scraper.abitur import orders_watch as OW
from scraper.parsers.enrollment_order_groups import is_bvi_row, parse_pdf_bytes

OUT = Path(__file__).parent / "abitur" / "cutoffs_2026.json"

# «Особенности приема» в приказе называют не вид квоты, а место внутри неё:
# приказ от 03.08 идёт «в пределах особой квоты», и внутри него «Общие места»
# — это особая квота, а «Отдельная квота» — отдельная. Проверено по epk25:
# из 40 человек с меткой «Общие места» все 32 найденных стоят в списках вида
# «особая квота», а все 40 с меткой «Отдельная квота» — в «отдельная квота».
_QUOTA_IN_PREAMBLE = (
    ("особой квоты", "особая квота"),
    ("отдельной квоты", "отдельная квота"),
    ("целевой квоты", "целевая квота"),
)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "MPGU-Abitur-Bot"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def preamble_quota(data: bytes) -> Optional[str]:
    """Какой квоте посвящён приказ — по вводной фразе «в пределах … квоты»."""
    import fitz
    with fitz.open(stream=io.BytesIO(data), filetype="pdf") as d:
        head = re.sub(r"\s+", " ", d[0].get_text())
    for needle, kind in _QUOTA_IN_PREAMBLE:
        if needle in head:
            return kind
    return None


def competition_of(group: dict, order_quota: Optional[str]) -> str:
    """Вид конкурса группы: общий, особая/отдельная/целевая квота."""
    label = (group.get("admission") or "").strip().lower()
    if not label:
        return "общий конкурс"
    if "отдельная" in label:
        return "отдельная квота"
    if "целевая" in label:
        return "целевая квота"
    if "особая" in label:
        return "особая квота"
    # «Общие места» внутри квотного приказа = та квота, которой приказ посвящён
    return order_quota or "общий конкурс"


def level_of(direction: str) -> str:
    """Ступень по среднему сегменту кода ФГОС: 03 — бакалавриат, 04 — маг."""
    m = re.match(r"\d\d\.(\d\d)\.", direction or "")
    seg = m.group(1) if m else ""
    return {"04": "specialized_higher_education", "05": "specialist",
            "02": "secondary_vocational_education"}.get(seg, "basic_higher_education")


def rows_from_order(data: bytes, source: str) -> List[dict]:
    quota = preamble_quota(data)
    out = []
    for g in parse_pdf_bytes(data):
        comp = [r for r in g["rows"]
                if not is_bvi_row(r) and r.get("total") is not None]
        direction = (g.get("direction") or "").strip()
        profile = (g.get("profile") or "").strip()
        out.append({
            "direction": f"{direction}. {profile}" if profile else direction,
            "form": (g.get("form") or "").lower().strip(),
            "unit": g.get("unit"),
            "kind": "бюджет",
            "competition": competition_of(g, quota),
            "level": level_of(direction),
            "enrolled": len(g["rows"]),
            "bvi": sum(1 for r in g["rows"] if is_bvi_row(r)),
            "counted": len(comp),
            "cutoff": min((r["total"] for r in comp), default=None),
            "top": max((r["total"] for r in comp), default=None),
            "exact": True,
            "source": source,
        })
    return out


def main() -> int:
    index = _get(OW.INDEX_PAGE).decode("utf-8", "replace")
    pdfs: Dict[str, str] = {}
    for page in OW.order_pages(index):
        html = _get(page).decode("utf-8", "replace")
        for u in re.findall(r'href="([^"]+\.pdf)"', html, re.I):
            pdfs[u] = OW.order_date(page) or ""
    rows: List[dict] = []
    for url, date in sorted(pdfs.items()):
        name = url.rsplit("/", 1)[-1].lower()
        if "grant" in name:
            continue            # право учиться за счёт средств МПГУ — не конкурс
        data = _get(url)
        got = rows_from_order(data, f"приказ {date}")
        print(f"{name}: групп {len(got)}, зачислено "
              f"{sum(r['enrolled'] for r in got)}, БВИ {sum(r['bvi'] for r in got)}")
        rows.extend(got)
    rows = [r for r in rows if r["counted"]]
    doc = {"source": "приказы о зачислении МПГУ 2026 (mpgu.su)", "lists": rows}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ГОТОВО: групп с проходным {len(rows)} → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
