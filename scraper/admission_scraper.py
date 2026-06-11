"""Скрейпер данных приёмной кампании МПГУ.

Сохраняет структурированные данные в data/admissions/:
  programs.json     — направления подготовки
  calendar.json     — ключевые даты
  documents.json    — необходимые документы
  ranked_lists/     — рейтинговые списки по СНИЛС

Запуск:
  python -m scraper.admission_scraper
  python -m scraper.admission_scraper --dry-run   # только парсит, не сохраняет
"""
import asyncio
import json
import logging
import os
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("admission_scraper")

_CFG_PATH = Path(__file__).parent / "config" / "admissions.json"
_DATA_PATH = Path(os.environ.get("DATA_PATH", "./data"))
_BASE = "https://mpgu.su"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MPGU-Bot/1.0)"}
_TIMEOUT = 20


def _cfg() -> dict:
    with open(_CFG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return r.read()


def _soup(url: str) -> "BeautifulSoup":
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 not installed")
    html = _fetch(url)
    return BeautifulSoup(html, "lxml")


def _save(rel_path: str, data: Any, dry_run: bool = False) -> None:
    dest = _DATA_PATH / rel_path
    if dry_run:
        log.info("[dry-run] would write %s (%d items)", rel_path,
                 len(data) if isinstance(data, (list, dict)) else 1)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("saved %s", dest)


# ---------------------------------------------------------------------------
# Programs (направления подготовки)
# ---------------------------------------------------------------------------

def _normalize_code(raw: str) -> str:
    """'44.03.01' → '44.03.01', strip garbage"""
    m = re.search(r"\d{2}\.\d{2}\.\d{2}", raw or "")
    return m.group() if m else raw.strip()


def _parse_programs_table(soup: "BeautifulSoup") -> list[dict]:
    programs = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        if not any(k in " ".join(headers) for k in ("направлен", "шифр", "код")):
            continue
        for row in rows[1:]:
            cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            if not cells:
                continue
            prog = _row_to_program(headers, cells)
            if prog:
                programs.append(prog)
    return programs


def _row_to_program(headers: list[str], cells: list[str]) -> dict | None:
    p: dict[str, Any] = {"updated_at": str(date.today())}
    for i, h in enumerate(headers):
        if i >= len(cells):
            break
        v = cells[i].strip()
        if not v:
            continue
        if any(k in h for k in ("код", "шифр", "направлен")):
            code = _normalize_code(v)
            if code:
                p["code"] = code
            if not re.search(r"\d{2}\.\d{2}\.\d{2}", v):
                p["name"] = v  # row without code → name column
        if any(k in h for k in ("наименован", "название", "профиль")):
            p["name"] = v
        if any(k in h for k in ("бюдж", "контр", "места бюдж")):
            n = re.search(r"\d+", v)
            if n:
                p["budget_seats"] = int(n.group())
        if any(k in h for k in ("стоимост", "цена", "платн", "руб")):
            n = re.search(r"[\d\s]+", v.replace("\xa0", ""))
            if n:
                try:
                    p["tuition_cost"] = int(n.group().replace(" ", ""))
                except ValueError:
                    pass
        if any(k in h for k in ("егэ", "предмет", "вступ")):
            p["ege_subjects"] = [s.strip() for s in re.split(r"[,;/\n]", v) if s.strip()]
        if any(k in h for k in ("форма", "обучен")):
            lower = v.lower()
            if "очно-заоч" in lower:
                p["form"] = "evening"
            elif "заочн" in lower:
                p["form"] = "distance"
            else:
                p["form"] = "full_time"
        if any(k in h for k in ("уровень", "степень", "бакалавр", "магистр")):
            lower = v.lower()
            if "магистр" in lower:
                p["degree"] = "master"
            elif "аспирант" in lower or "адъюнкт" in lower:
                p["degree"] = "postgraduate"
            else:
                p["degree"] = "bachelor"
    if "code" not in p and "name" not in p:
        return None
    p.setdefault("degree", "bachelor")
    p.setdefault("form", "full_time")
    return p


def scrape_programs() -> list[dict]:
    cfg = _cfg()
    url = _BASE + cfg["pages"]["programs"]
    log.info("programs → %s", url)
    try:
        soup = _soup(url)
    except Exception as e:
        log.warning("programs page error: %s — trying main page", e)
        try:
            soup = _soup(_BASE + cfg["pages"]["main"])
        except Exception as e2:
            log.error("programs fallback error: %s", e2)
            return []
    programs = _parse_programs_table(soup)
    if not programs:
        log.warning("no program table found, scraping links")
        programs = _scrape_programs_from_links(soup)
    log.info("programs: found %d", len(programs))
    return programs


def _scrape_programs_from_links(soup: "BeautifulSoup") -> list[dict]:
    """Fallback: find program links and collect name/code from <a> text."""
    programs = []
    seen = set()
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        code = _normalize_code(text)
        if not code or code in seen:
            continue
        seen.add(code)
        programs.append({"code": code, "name": text, "degree": "bachelor",
                         "form": "full_time", "updated_at": str(date.today())})
    return programs


# ---------------------------------------------------------------------------
# Calendar (ключевые даты)
# ---------------------------------------------------------------------------

_MONTHS = {
    "январ": "01", "феврал": "02", "март": "03", "апрел": "04",
    "май": "05", "мая": "05", "июн": "06", "июл": "07",
    "август": "08", "сентябр": "09", "октябр": "10", "ноябр": "11", "декабр": "12",
}


def _parse_date_ru(text: str) -> str | None:
    """'20 июня 2026' → '2026-06-20'"""
    text = text.lower()
    for m_ru, m_num in _MONTHS.items():
        if m_ru in text:
            day_m = re.search(r"(\d{1,2})\s+" + m_ru[:4], text)
            year_m = re.search(r"20\d{2}", text)
            if day_m:
                day = day_m.group(1).zfill(2)
                year = year_m.group() if year_m else str(date.today().year)
                return f"{year}-{m_num}-{day}"
    return None


def scrape_calendar() -> list[dict]:
    cfg = _cfg()
    url = _BASE + cfg["pages"]["calendar"]
    log.info("calendar → %s", url)
    events = []
    try:
        soup = _soup(url)
    except Exception as e:
        log.warning("calendar page error: %s", e)
        return _fallback_calendar()

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows[1:]:
            cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            date_str = _parse_date_ru(cells[0])
            desc = cells[1] if len(cells) > 1 else cells[0]
            events.append({
                "event": desc[:120],
                "date": date_str or cells[0],
                "description": " ".join(cells[2:])[:200] if len(cells) > 2 else "",
            })

    if not events:
        for li in soup.find_all(["li", "p"]):
            text = li.get_text(" ", strip=True)
            d = _parse_date_ru(text)
            if d and len(text) > 10:
                events.append({"event": text[:120], "date": d, "description": ""})

    if not events:
        events = _fallback_calendar()
    log.info("calendar: found %d events", len(events))
    return events


def _fallback_calendar() -> list[dict]:
    year = date.today().year
    return [
        {"event": "Начало приёма документов",
         "date": f"{year}-06-20",
         "description": "Подача заявлений через Госуслуги или лично"},
        {"event": "Завершение приёма документов (бюджет)",
         "date": f"{year}-07-25",
         "description": "Для поступающих по ЕГЭ"},
        {"event": "Публикация рейтинговых списков",
         "date": f"{year}-07-27",
         "description": "На сайте mpgu.su/abiturientam/rating/"},
        {"event": "Приоритетное зачисление",
         "date": f"{year}-08-05",
         "description": "Без вступительных испытаний: льготы, целевики"},
        {"event": "Основное зачисление",
         "date": f"{year}-08-09",
         "description": "Основная волна зачисления"},
    ]


# ---------------------------------------------------------------------------
# Documents (необходимые документы)
# ---------------------------------------------------------------------------

def scrape_documents() -> dict:
    cfg = _cfg()
    url = _BASE + cfg["pages"]["documents"]
    log.info("documents → %s", url)
    try:
        soup = _soup(url)
    except Exception as e:
        log.warning("documents page error: %s", e)
        return _fallback_documents()

    docs: dict[str, list[str]] = {"budget": [], "contract": [], "target": []}
    current_section = "budget"

    for el in soup.find_all(["h2", "h3", "h4", "li", "p"]):
        text = el.get_text(strip=True)
        if not text:
            continue
        lower = text.lower()
        if any(k in lower for k in ("бюджет", "бесплатн")):
            current_section = "budget"
        elif any(k in lower for k in ("платн", "договор", "контракт")):
            current_section = "contract"
        elif "целев" in lower:
            current_section = "target"
        elif el.name == "li" and len(text) > 3:
            docs[current_section].append(text[:150])

    for key in docs:
        if not docs[key]:
            docs[key] = _fallback_documents()[key]

    log.info("documents: budget=%d contract=%d target=%d",
             len(docs["budget"]), len(docs["contract"]), len(docs["target"]))
    return docs


def _fallback_documents() -> dict:
    common = ["Паспорт (оригинал + копия)", "Аттестат или диплом (оригинал или копия)",
              "СНИЛС", "Фотографии 3×4 (6 шт.)", "Медицинская справка 086/у",
              "Согласие на обработку персональных данных"]
    return {
        "budget": common + ["Оригинал аттестата для зачисления на бюджет"],
        "contract": common + ["Договор об оказании платных образовательных услуг"],
        "target": common + ["Целевой договор с направляющей организацией",
                             "Направление от работодателя"],
    }


# ---------------------------------------------------------------------------
# Ranked lists (рейтинговые списки)
# ---------------------------------------------------------------------------

def _snils_normalize(raw: str) -> str:
    return re.sub(r"[\s\-–—]", "", raw or "")


def _parse_ranked_xlsx(content: bytes) -> list[dict]:
    if openpyxl is None:
        log.warning("openpyxl not installed, skipping xlsx ranked list")
        return []
    import io
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    results = []
    for ws in wb.worksheets:
        headers: list[str] = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c or "").strip() for c in row]
            if not any(cells):
                continue
            if not headers:
                headers = [c.lower() for c in cells]
                continue
            entry = _xlsx_row_to_entry(headers, cells)
            if entry:
                results.append(entry)
        if results:
            break
    return results


def _xlsx_row_to_entry(headers: list[str], cells: list[str]) -> dict | None:
    entry: dict = {}
    for i, h in enumerate(headers):
        if i >= len(cells):
            break
        v = cells[i].strip()
        if any(k in h for k in ("снилс",)):
            norm = _snils_normalize(v)
            if re.match(r"\d{11}", norm):
                entry["snils"] = norm
        if any(k in h for k in ("балл", "сумма", "итог")):
            try:
                entry["score"] = float(v.replace(",", "."))
            except ValueError:
                pass
        if any(k in h for k in ("приоритет", "prior")):
            try:
                entry["priority"] = int(v)
            except ValueError:
                pass
        if any(k in h for k in ("статус", "зачислен", "рекоменд")):
            entry["status"] = v[:50]
    return entry if "snils" in entry else None


def scrape_ranked_lists() -> dict[str, list[dict]]:
    cfg = _cfg()
    url = _BASE + cfg["pages"]["ranked_lists"]
    log.info("ranked_lists → %s", url)
    result: dict[str, list[dict]] = {}
    try:
        soup = _soup(url)
    except Exception as e:
        log.warning("ranked lists page unavailable: %s", e)
        return result

    exts = cfg.get("ranked_lists_extensions", ["xlsx", "xls"])
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not any(href.lower().endswith("." + ext) for ext in exts):
            continue
        if not href.startswith("http"):
            href = _BASE + href
        name = a.get_text(strip=True) or Path(href).stem
        code = _normalize_code(name) or re.sub(r"[^\w]", "_", name)[:20]
        log.info("  downloading ranked list %s → %s", name, href)
        try:
            content = _fetch(href)
            if href.lower().endswith((".xlsx", ".xls")):
                entries = _parse_ranked_xlsx(content)
            else:
                entries = []  # PDF parsing via existing pdf_parser if needed
            if entries:
                result[code] = entries
                log.info("  %s: %d entries", code, len(entries))
        except Exception as e:
            log.warning("  failed to download %s: %s", href, e)

    return result


# ---------------------------------------------------------------------------
# Index for ranked lists
# ---------------------------------------------------------------------------

def _build_ranked_index(lists: dict[str, list]) -> dict:
    return {
        "updated_at": str(date.today()),
        "lists": [{"code": code, "count": len(entries)} for code, entries in lists.items()],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_all(dry_run: bool = False) -> None:
    log.info("=== Admission scraper start (dry_run=%s) ===", dry_run)
    programs = scrape_programs()
    _save("admissions/programs.json", programs, dry_run)

    calendar = scrape_calendar()
    _save("admissions/calendar.json", calendar, dry_run)

    documents = scrape_documents()
    _save("admissions/documents.json", documents, dry_run)

    ranked = scrape_ranked_lists()
    if ranked:
        for code, entries in ranked.items():
            _save(f"admissions/ranked_lists/{code}.json", entries, dry_run)
        _save("admissions/ranked_lists/index.json", _build_ranked_index(ranked), dry_run)
    else:
        log.info("ranked lists not yet published or none found")
        if not dry_run:
            idx_path = _DATA_PATH / "admissions" / "ranked_lists" / "index.json"
            if not idx_path.exists():
                _save("admissions/ranked_lists/index.json",
                      {"updated_at": str(date.today()), "lists": []}, dry_run)

    # Исторические проходные баллы + прогноз на текущий год
    log.info("Scraping historical passing scores...")
    try:
        from scraper.score_predictor import (
            scrape_all_historical, build_predictions,
            save_historical, save_predictions,
        )
        historical = scrape_all_historical()
        if historical:
            save_historical(historical, dry_run)
            predictions = build_predictions(historical)
            if predictions:
                save_predictions(predictions, dry_run)
                log.info("predictions: %d программ", len(predictions))
        else:
            log.info("historical scores not found (site may be unavailable)")
    except Exception as e:
        log.warning("historical scores scraper error: %s", e)

    log.info("=== Admission scraper done ===")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    asyncio.run(run_all(dry_run))
