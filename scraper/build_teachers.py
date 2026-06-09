"""
Crawl mpgu.su department pages to build the teacher database.

Writes: {DATA_PATH}/meta/teachers.json

Run:
    python -m scraper.build_teachers
    python -m scraper.build_teachers --data-path ./data
"""
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

load_dotenv()

from scraper.teachers.crawler import (
    TeacherCrawler,
    STRUCTURE_SLUG_OVERRIDES,
    institute_slug_from_url,
)
from scraper.teachers.normalizer import parse_name, match_key

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config" / "institutes.json"
DATA_PATH = os.environ.get("DATA_PATH", "./data")


async def run(data_path: str) -> None:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)

    all_records: list[dict] = []

    connector = aiohttp.TCPConnector(limit=3)
    async with aiohttp.ClientSession(connector=connector,
                                     timeout=aiohttp.ClientTimeout(total=30)) as session:
        crawler = TeacherCrawler(session)
        for inst in config["institutes"]:
            inst_id = inst["id"]
            slug = (
                STRUCTURE_SLUG_OVERRIDES.get(inst_id)
                or institute_slug_from_url(inst.get("schedule_url", ""))
            )
            if not slug:
                print(f"[SKIP] {inst_id}: cannot determine structure slug")
                continue
            print(f"[CRAWL] {inst_id} → /{slug}/struktura/")
            records = await crawler.crawl_institute(inst_id, slug)
            print(f"  → {len(records)} teachers")
            all_records.extend(records)

    # Deduplicate by staff_slug (crawler deduplicates within a session,
    # but be safe in case of multiple institute runs)
    seen: set[str] = set()
    unique: list[dict] = []
    for r in all_records:
        slug = r["staff_slug"]
        if slug not in seen:
            seen.add(slug)
            unique.append(r)

    # Enrich with parsed name components and match key
    for i, t in enumerate(unique, start=1):
        parsed = parse_name(t["full_name"])
        t.update(parsed)
        t["id"] = i
        t["_key"] = match_key(t["abbreviated"])

    out_dir = Path(data_path) / "meta"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "teachers.json"
    out_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "count": len(unique),
                "teachers": unique,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nDone: {len(unique)} teachers → {out_path}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build MPGU teacher database")
    parser.add_argument("--data-path", default=DATA_PATH)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run(args.data_path))


if __name__ == "__main__":
    main()
