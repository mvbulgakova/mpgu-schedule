"""
Fetch and parse exam/credit session schedules for all institutes.

For each institute, derives the exam URL from schedule_url by replacing
'raspisanie-uchebnyih-zanyatiy' with 'raspisanie-ekzamenatsionnyih-sessiy'
(and credit URL with 'raspisanie-zachjotnyh-sessij' / 'raspisanie-zachetnyh-sessij').

Writes: {DATA_PATH}/institutes/{id}/exams.json

Run:
    python -m scraper.fetch_exams
    python -m scraper.fetch_exams --institute history
"""
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

load_dotenv()

from scraper.fetchers.site_fetcher import fetch_schedule_links, HEADERS
from scraper.fetchers.file_fetcher import fetch_file
from scraper.parsers.exam_parser import parse_exam_bytes, entries_to_dicts
from scraper.parsers.nextcloud_parser import nextcloud_download_url
from scraper.storage.git_storage import GitStorage

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config" / "institutes.json"
DATA_PATH = os.environ.get("DATA_PATH", "./data")

# Institutes with non-standard exam URL structure.
# childhood uses sub-faculty URLs, so derive from each sub-faculty's schedule_url.
EXAM_URL_OVERRIDES: dict[str, list[str]] = {
    "childhood": [
        # defectology sub-faculty
        "https://mpgu.su/ob-mpgu/struktura/faculties/institut-detstva/defektologicheskiy-fakultet/uchebnyiy-protsess/raspisanie-ekzamenatsionnyih-sessiy/",
        "https://mpgu.su/ob-mpgu/struktura/faculties/institut-detstva/defektologicheskiy-fakultet/uchebnyiy-protsess/raspisanie-zachjotnyh-sessij/",
        # primary education sub-faculty
        "https://mpgu.su/ob-mpgu/struktura/faculties/institut-detstva/fakultet-nachalnogo-obrazovaniya/uchenyiy-otdel/raspisanie-ekzamenatsionnyih-sessiy/",
        "https://mpgu.su/ob-mpgu/struktura/faculties/institut-detstva/fakultet-nachalnogo-obrazovaniya/uchenyiy-otdel/raspisanie-zachjotnyh-sessij/",
        # music sub-faculty
        "https://mpgu.su/ob-mpgu/struktura/faculties/institut-detstva/uchebnyiy-protsess/raspisanie-ekzamenatsionnyih-sessiy/",
        "https://mpgu.su/ob-mpgu/struktura/faculties/institut-detstva/uchebnyiy-protsess/raspisanie-zachjotnyh-sessij/",
    ],
}

CREDIT_SLUGS = [
    "raspisanie-zachjotnyh-sessij",   # with ё-encoding (most institutes)
    "raspisanie-zachetnyh-sessij",    # without ё (physics, some others)
    "raspisanie-zachjotnoj-sessii",   # singular genitive variant
]
# Exam slug variants (different URL spelling across institutes)
EXAM_SLUGS = [
    "raspisanie-ekzamenatsionnyih-sessiy",  # main spelling
    "raspisanie-ekzamenatsionnoj-sessii",   # singular
    "raspisanie-ekzamenacionnoj-sessii",    # without ё
]
REGULAR_SLUGS = [
    "raspisanie-uchebnyih-zanyatiy",  # main spelling
    "raspisanie-uchebnyh-zanjatij",   # teaching_development / digital variant
    "raspisanie-zanyatiy-instituta",  # childhood (non-standard)
]

# Link types that carry downloadable files (gsheets are unlikely for exams)
_FILE_TYPES = {"pdf", "excel", "nextcloud", "docx", "doc"}

# Hint extensions from link type
_TYPE_EXT = {
    "pdf":       ".pdf",
    "excel":     ".xlsx",
    "docx":      ".docx",
    "doc":       ".doc",
    "nextcloud": "",     # format detected from bytes
}

# Skip links whose URL contains upload year older than this
_MIN_YEAR = 2024

_YEAR_IN_URL_RE = re.compile(r"/(\d{4})/\d{2}/")


def _is_stale_link(url: str) -> bool:
    """True if the link's upload year is older than _MIN_YEAR."""
    m = _YEAR_IN_URL_RE.search(url)
    return bool(m and int(m.group(1)) < _MIN_YEAR)


_URL_GROUP_RE = re.compile(
    r"[А-ЯЁA-Za-zа-яё]{2,4}\d{2}-[А-ЯЁA-Za-zа-яё]{2,4}\d{4}"
)


def _group_from_url(url: str) -> str | None:
    """
    Extract a group code from the URL filename.
    Works for URLs like …/BVO_1_kurs_VOK34-MDE2501.pdf → 'VOK34-MDE2501'
    or …/2-курс-БОК34-МДЭ2401.pdf → 'БОК34-МДЭ2401'.
    Returns None for hash-named files or URLs with no embedded group code.
    """
    stem = url.split("?")[0].rsplit("/", 1)[-1].rsplit(".", 1)[0]
    m = _URL_GROUP_RE.search(stem)
    return m.group(0).upper() if m else None


def derive_exam_urls(schedule_url: str) -> list[str]:
    """Derive exam and credit session URLs from the regular schedule URL."""
    matched_slug = next(
        (s for s in REGULAR_SLUGS if s in schedule_url), None
    )
    if not matched_slug:
        return []
    base = schedule_url[: schedule_url.index(matched_slug)]
    urls = [base + s + "/" for s in EXAM_SLUGS]
    urls += [base + s + "/" for s in CREDIT_SLUGS]
    return urls


async def process_institute(
    session: aiohttp.ClientSession,
    institute: dict,
    storage: GitStorage,
) -> dict:
    inst_id = institute["id"]
    schedule_url = institute.get("schedule_url", "")

    exam_urls = EXAM_URL_OVERRIDES.get(inst_id) or derive_exam_urls(schedule_url)
    if not exam_urls:
        log.warning("[%s] Cannot derive exam URL from %s", inst_id, schedule_url)
        return {"id": inst_id, "status": "skip", "entries": 0}

    all_entries = []

    for exam_url in exam_urls:
        try:
            links = await fetch_schedule_links(session, exam_url)
        except Exception as e:
            log.debug("[%s] %s → %s", inst_id, exam_url, e)
            continue

        log.info("[%s] %s → %d links", inst_id, exam_url, len(links))

        for link in links:
            url = link["url"]
            link_type = link["type"]
            if link_type not in _FILE_TYPES:
                log.debug("[%s] skip link type %s: %s", inst_id, link_type, url[:60])
                continue

            if _is_stale_link(url):
                log.debug("[%s] skip stale link (%s): %s", inst_id, link_type, url[:60])
                continue

            if "drive.google.com" in url:
                log.debug("[%s] skip google drive link: %s", inst_id, url[:60])
                continue

            # Nextcloud: resolve to direct download URL
            fetch_url = nextcloud_download_url(url) if link_type == "nextcloud" else url
            hint_ext = _TYPE_EXT.get(link_type, "")

            try:
                content, _ = await fetch_file(session, fetch_url)
            except Exception as e:
                log.warning("[%s] fetch %s: %s", inst_id, url[:60], e)
                continue

            try:
                entries = parse_exam_bytes(content, hint_ext=hint_ext)
                # For OCR entries that have no group (scanned per-group PDFs),
                # fall back to extracting the group code from the filename.
                if entries and any(not e.groups for e in entries):
                    grp = _group_from_url(url)
                    if grp:
                        for e in entries:
                            if not e.groups:
                                e.groups = [grp]
                log.info("  [%s] %s → %d entries", inst_id, url[-50:], len(entries))
                all_entries.extend(entries)
            except Exception as e:
                log.warning("  [%s] parse error %s: %s", inst_id, url[-50:], e)

    # Deduplicate by (date, time_start, subject, groups)
    seen = set()
    unique = []
    for e in all_entries:
        key = (e.date, e.time_start, e.subject, tuple(sorted(e.groups)))
        if key not in seen:
            seen.add(key)
            unique.append(e)

    doc = {
        "institute_id": inst_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries_to_dicts(unique),
    }

    out_dir = Path(DATA_PATH) / "institutes" / inst_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "exams.json"
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  {inst_id}: {len(unique)} exam entries → {out_path}")
    return {"id": inst_id, "status": "ok", "entries": len(unique)}


async def run(data_path: str, institute_filter: str | None = None) -> None:
    global DATA_PATH
    DATA_PATH = data_path

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    institutes = config["institutes"]
    if institute_filter:
        institutes = [i for i in institutes if i["id"] == institute_filter]

    storage = GitStorage(data_path)
    connector = aiohttp.TCPConnector(limit=5)

    async with aiohttp.ClientSession(
        connector=connector,
        headers=HEADERS,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as session:
        tasks = [process_institute(session, inst, storage) for inst in institutes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    ok = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "ok")
    total_entries = sum(
        r.get("entries", 0) for r in results if isinstance(r, dict)
    )
    print(f"\nDone: {ok}/{len(institutes)} institutes, {total_entries} total exam entries")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Fetch MPGU exam schedules")
    parser.add_argument("--data-path", default=DATA_PATH)
    parser.add_argument("--institute", help="Process only this institute ID")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run(args.data_path, args.institute))


if __name__ == "__main__":
    main()
