"""
Scraper for mpgu.su admissions pages.
Writes/updates structured JSON in DATA_PATH (data branch worktree).

Usage:
    python scraper/admission_scraper.py            # write to .data-wt/
    python scraper/admission_scraper.py --dry-run  # print only, no writes
    DATA_PATH=/path/to/data python scraper/admission_scraper.py
"""
import json
import os
import re
import sys
import datetime
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: pip install requests beautifulsoup4")
    sys.exit(1)

DATA_PATH = Path(os.environ.get("DATA_PATH", ".data-wt"))
DRY_RUN = "--dry-run" in sys.argv
TODAY = datetime.date.today().isoformat()
HEADERS = {"User-Agent": "Mozilla/5.0 MPGU-Scraper/1.0"}

_MONTH = {
    "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
    "мая": "05", "июня": "06", "июля": "07", "августа": "08",
    "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12",
}
_DATE_RE = re.compile(
    r"(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа"
    r"|сентября|октября|ноября|декабря)\s+(\d{4})", re.I
)


def _get(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  WARN fetch {url}: {e}")
        return None


def _load(subpath: str):
    path = DATA_PATH / "admissions" / subpath
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save(subpath: str, data) -> None:
    path = DATA_PATH / "admissions" / subpath
    if DRY_RUN:
        print(f"  [dry-run] {path}:")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:600])
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  wrote {path}")


def _to_iso(day: str, month_ru: str, year: str) -> str:
    return f"{year}-{_MONTH[month_ru.lower()]}-{int(day):02d}"


def _get_text(soup: BeautifulSoup, max_chars: int = 8000) -> str:
    """Извлекает основной текстовый контент страницы."""
    for tag in soup.find_all(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.find(class_=re.compile(r"content|entry|post"))
    target = main or soup.find("body") or soup
    text = target.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()[:max_chars]


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def scrape_calendar() -> list[dict]:
    """Парсит сроки приёма."""
    print("calendar …")
    soup = _get("https://mpgu.su/postuplenie/")
    if not soup:
        return []

    events: list[dict] = []

    # Таблицы (дата | событие)
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            date_txt = cells[0].get_text(" ", strip=True)
            event_txt = cells[-1].get_text(" ", strip=True)
            m = _DATE_RE.search(date_txt)
            if m and event_txt and event_txt != date_txt:
                events.append({
                    "event": event_txt[:150],
                    "date": _to_iso(*m.groups()),
                    "description": "",
                })

    # Параграфы/li с датой внутри
    if not events:
        for tag in soup.find_all(["p", "li"]):
            text = tag.get_text(" ", strip=True)
            m = _DATE_RE.search(text)
            if not m or len(text) < 12:
                continue
            iso = _to_iso(*m.groups())
            desc = _DATE_RE.sub("", text).strip(" —–:,")
            if desc and len(desc) > 5:
                events.append({"event": desc[:150], "date": iso, "description": ""})

    seen: set[str] = set()
    unique = []
    for ev in events:
        key = ev["date"] + ev["event"][:40]
        if key not in seen:
            seen.add(key)
            unique.append(ev)

    print(f"  found {len(unique)} events")
    return sorted(unique, key=lambda e: e["date"])


def scrape_documents() -> dict:
    """Парсит перечень документов."""
    print("documents …")
    soup = _get("https://mpgu.su/postuplenie/bakalavriat/")
    if not soup:
        return {}

    result: dict[str, list[str]] = {}
    cat_re = re.compile(r"бюджет|платн|контракт|целев", re.I)

    for heading in soup.find_all(["h2", "h3", "h4", "strong", "b"]):
        text = heading.get_text(strip=True)
        if not cat_re.search(text):
            continue
        key = ("target" if re.search(r"целев", text, re.I)
               else "budget" if re.search(r"бюджет", text, re.I)
               else "contract")
        ul = heading.find_next(["ul", "ol"])
        if ul:
            items = [li.get_text(strip=True) for li in ul.find_all("li")
                     if li.get_text(strip=True)]
            if items:
                result[key] = items

    print(f"  found keys: {list(result.keys())}")
    return result


def scrape_page_text() -> dict[str, str]:
    """Скачивает текст ключевых страниц и сохраняет для LLM."""
    print("page texts …")
    pages = {
        "postuplenie_main":      "https://mpgu.su/postuplenie/",
        "bakalavriat":           "https://mpgu.su/postuplenie/bakalavriat/",
        "entrance_tests":        "https://mpgu.su/postuplenie/entrance-test-programs/",
        "platnoe":               "https://mpgu.su/postuplenie/platnoe-obuchenie/",
        "normativnoe":           "https://mpgu.su/postuplenie/normativno-pravovoe-obespechenie-priema/",
        "magistratura":          "https://mpgu.su/postuplenie/magistratura/",
        "ovz":                   "https://mpgu.su/postuplenie/informatsiya-o-postuplenii-dlya-lits-s-ogranichenyimi-vozmozhnostyami-zdorovya/",
    }
    texts = {}
    for key, url in pages.items():
        soup = _get(url)
        if soup:
            texts[key] = _get_text(soup, 6000)
            print(f"  {key}: {len(texts[key])} chars")
    return texts


def main() -> None:
    print(f"MPGU Admissions Scraper — {TODAY}"
          + (" [DRY RUN]" if DRY_RUN else ""))
    print(f"DATA_PATH = {DATA_PATH.resolve()}\n")

    # Calendar
    cal_new = scrape_calendar()
    cal_existing = _load("calendar.json") or []
    if cal_new and len(cal_new) >= 3:
        existing_by_date = {e["date"]: e for e in cal_existing if isinstance(e, dict)}
        for ev in cal_new:
            ev["description"] = (ev.get("description")
                                 or existing_by_date.get(ev["date"], {}).get("description", ""))
        _save("calendar.json", cal_new)
    else:
        print(f"  calendar: only {len(cal_new)} events found, keeping existing\n")

    # Documents
    docs_new = scrape_documents()
    docs_existing = _load("documents.json") or {}
    if docs_new and len(docs_new) >= 2:
        _save("documents.json", {**docs_existing, **docs_new})
    else:
        print("  documents: insufficient, keeping existing\n")

    # Page texts (для LLM-контекста)
    texts = scrape_page_text()
    if texts:
        _save("site_texts.json", {"updated_at": TODAY, "pages": texts})

    # Ranked lists timestamp
    idx = _load("ranked_lists/index.json") or {"lists": []}
    idx["checked_at"] = TODAY
    _save("ranked_lists/index.json", idx)

    print("\nDone.")


if __name__ == "__main__":
    main()
