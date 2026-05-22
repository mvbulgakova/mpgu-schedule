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
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

load_dotenv()

from scraper.fetchers.site_fetcher import fetch_schedule_links, HEADERS
from scraper.fetchers.file_fetcher import fetch_file
from scraper.parsers.exam_parser import parse_exam_file, entries_to_dicts
from scraper.storage.git_storage import GitStorage

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config" / "institutes.json"
DATA_PATH = os.environ.get("DATA_PATH", "./data")

# Institutes with non-standard exam URL structure
EXAM_URL_OVERRIDES: dict[str, list[str]] = {
    # "institute_id": ["exam_url1", ...]
    # Fill in if auto-derived URL returns 404
}

CREDIT_SLUGS = [
    "raspisanie-zachjotnyh-sessij",  # with ё-encoding (most institutes)
    "raspisanie-zachetnyh-sessij",   # without ё (physics, some others)
]
EXAM_SLUG = "raspisanie-ekzamenatsionnyih-sessiy"
REGULAR_SLUG = "raspisanie-uchebnyih-zanyatiy"


def derive_exam_urls(schedule_url: str) -> list[str]:
    """Derive exam and credit session URLs from the regular schedule URL."""
    if REGULAR_SLUG not in schedule_url:
        return []
    base = schedule_url.replace(REGULAR_SLUG, "")
    urls = [base + EXAM_SLUG + "/"]
    for slug in CREDIT_SLUGS:
        urls.append(base + slug + "/")
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
            if link_type not in {"pdf", "excel", "nextcloud", "docx"}:
                continue

            try:
                content, _ = await fetch_file(session, url)
            except Exception as e:
                log.warning("[%s] fetch %s: %s", inst_id, url[:60], e)
                continue

            ext = {
                "pdf": ".pdf",
                "excel": ".xlsx",
                "docx": ".docx",
            }.get(link_type, ".bin")

            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            try:
                entries = parse_exam_file(tmp_path)
                log.info("  [%s] %s → %d entries", inst_id, url[-50:], len(entries))
                all_entries.extend(entries)
            except Exception as e:
                log.warning("  [%s] parse error %s: %s", inst_id, url[-50:], e)
            finally:
                os.unlink(tmp_path)

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
