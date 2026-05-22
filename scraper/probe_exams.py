"""
Probe exam schedule pages for all institutes — discover which ones have files.

Does NOT download or parse files, only checks link availability.

Run:
    python -m scraper.probe_exams
    python -m scraper.probe_exams --institute history
    python -m scraper.probe_exams --json > probe_results.json
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

load_dotenv()

from scraper.fetchers.site_fetcher import fetch_schedule_links, HEADERS
from scraper.fetch_exams import derive_exam_urls, EXAM_URL_OVERRIDES

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config" / "institutes.json"


async def probe_institute(
    session: aiohttp.ClientSession,
    institute: dict,
) -> dict:
    inst_id = institute["id"]
    inst_name = institute.get("short_name") or institute.get("name", inst_id)
    schedule_url = institute.get("schedule_url", "")

    exam_urls = EXAM_URL_OVERRIDES.get(inst_id) or derive_exam_urls(schedule_url)
    if not exam_urls:
        return {
            "id": inst_id,
            "name": inst_name,
            "status": "no_url",
            "pages": [],
        }

    pages = []
    for exam_url in exam_urls:
        try:
            links = await fetch_schedule_links(session, exam_url)
            file_links = [
                {"url": lnk["url"], "type": lnk["type"], "text": lnk["text"]}
                for lnk in links
                if lnk["type"] in {"pdf", "excel", "docx", "doc", "nextcloud"}
            ]
            pages.append({
                "url": exam_url,
                "status": "ok",
                "total_links": len(links),
                "file_links": file_links,
            })
        except Exception as e:
            pages.append({
                "url": exam_url,
                "status": "error",
                "error": str(e)[:120],
                "file_links": [],
            })

    has_files = any(p["file_links"] for p in pages)
    return {
        "id": inst_id,
        "name": inst_name,
        "status": "found" if has_files else "empty",
        "pages": pages,
    }


async def run(
    institute_filter: str | None = None,
    output_json: bool = False,
) -> list[dict]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    institutes = config["institutes"]
    if institute_filter:
        institutes = [i for i in institutes if i["id"] == institute_filter]

    connector = aiohttp.TCPConnector(limit=8)
    async with aiohttp.ClientSession(
        connector=connector,
        headers=HEADERS,
        timeout=aiohttp.ClientTimeout(total=30),
    ) as session:
        tasks = [probe_institute(session, inst) for inst in institutes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Unwrap exceptions
    clean: list[dict] = []
    for r in results:
        if isinstance(r, Exception):
            clean.append({"id": "?", "name": "?", "status": "exception", "error": str(r), "pages": []})
        else:
            clean.append(r)

    return clean


def _print_results(results: list[dict]) -> None:
    found = [r for r in results if r["status"] == "found"]
    empty = [r for r in results if r["status"] == "empty"]
    no_url = [r for r in results if r["status"] == "no_url"]
    errors = [r for r in results if r["status"] in ("error", "exception")]

    print(f"\n{'='*60}")
    print(f"Exam schedule probe — {len(results)} institutes")
    print(f"  ✓ found files : {len(found)}")
    print(f"  ○ page exists, no files : {len(empty)}")
    print(f"  - no derived URL : {len(no_url)}")
    print(f"  ✗ errors : {len(errors)}")
    print(f"{'='*60}\n")

    if found:
        print("── FOUND FILES ──────────────────────────────────────────")
        for r in found:
            total = sum(len(p["file_links"]) for p in r["pages"])
            print(f"  [{r['id']}] {r['name']} — {total} file(s)")
            for p in r["pages"]:
                if not p["file_links"]:
                    continue
                print(f"    {p['url']}")
                for lnk in p["file_links"]:
                    txt = f" ({lnk['text'][:40]})" if lnk["text"] else ""
                    print(f"      [{lnk['type']:8}] {lnk['url'][:80]}{txt}")

    if empty:
        print("\n── PAGE EXISTS, NO FILES ────────────────────────────────")
        for r in empty:
            for p in r["pages"]:
                if p["status"] == "ok" and p["total_links"] == 0:
                    print(f"  [{r['id']}] {p['url']}")
                elif p["status"] == "ok":
                    print(f"  [{r['id']}] {p['url']} ({p['total_links']} non-file links)")

    if no_url:
        print("\n── NO DERIVED EXAM URL ──────────────────────────────────")
        for r in no_url:
            print(f"  [{r['id']}] {r['name']}")

    if errors:
        print("\n── ERRORS ───────────────────────────────────────────────")
        for r in errors:
            print(f"  [{r['id']}] {r.get('error', '')} | pages: {r['pages'][:1]}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Probe MPGU exam schedule pages")
    parser.add_argument("--institute", help="Filter to one institute ID")
    parser.add_argument("--json", action="store_true", dest="output_json",
                        help="Output raw JSON to stdout")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    results = asyncio.run(run(args.institute, args.output_json))

    if args.output_json:
        json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        _print_results(results)


if __name__ == "__main__":
    main()
