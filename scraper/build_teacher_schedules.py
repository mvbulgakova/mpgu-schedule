"""
Cross-reference the teacher database with group schedules to build
per-teacher schedule files.

Reads:
    {DATA_PATH}/meta/teachers.json
    {DATA_PATH}/institutes/*/groups/*.json

Writes:
    {DATA_PATH}/teachers/{staff_slug}.json   — one file per teacher with schedule
    {DATA_PATH}/meta/teachers.json           — updated with `has_schedule` flag

Run standalone:
    python -m scraper.build_teacher_schedules
"""
import json
import logging
import os
import re
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from scraper.teachers.normalizer import match_teacher, match_key, parse_name

# Strip trailing room numbers and date lists that bleed into teacher names in PDFs,
# e.g. "доц. И.С.Гусейнова ауд.802" or "проф. Гусев Д.А. 19.02, 05.03"
_ROOM_RE = re.compile(r"\s*\(?ауд\.?\s*[\w\d/\\-]+\)?", re.IGNORECASE)
_DATE_SUFFIX_RE = re.compile(r"\s*,?\s*\d{1,2}\.\d{2}(?:\.\d{2,4})?(?:\s*,\s*\d{1,2}\.\d{2}(?:\.\d{2,4})?)*\s*$")


def _clean_teacher_abbr(raw: str) -> str:
    s = _ROOM_RE.sub("", raw)
    s = _DATE_SUFFIX_RE.sub("", s)
    return s.strip().rstrip(",").strip()

log = logging.getLogger(__name__)

DATA_PATH = os.environ.get("DATA_PATH", "./data")

DAY_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]


def _empty_week() -> dict:
    return {d: [] for d in DAY_KEYS}


def build(data_path: str) -> None:
    teachers_path = Path(data_path) / "meta" / "teachers.json"
    if not teachers_path.exists():
        print(f"[SKIP] teacher DB not found at {teachers_path}")
        print("  Run:  python -m scraper.build_teachers  first.")
        return

    db_doc = json.loads(teachers_path.read_text(encoding="utf-8"))
    db: list[dict] = db_doc["teachers"]
    print(f"Loaded {len(db)} teachers from DB")

    # Build lesson buckets: staff_slug → {odd/even → day → [lesson]}
    buckets: dict[str, dict] = {}

    groups_root = Path(data_path) / "institutes"
    group_files = sorted(groups_root.glob("*/groups/*.json"))
    print(f"Scanning {len(group_files)} group files …")

    unknown_names: dict[str, dict] = {}  # abbreviated → minimal record

    for gf in group_files:
        # institutes/{inst_id}/groups/{file}.json
        parts = gf.parts
        try:
            inst_idx = list(parts).index("institutes") + 1
            institute_id = parts[inst_idx]
        except (ValueError, IndexError):
            continue

        try:
            group_doc = json.loads(gf.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Cannot read %s: %s", gf, e)
            continue

        group_name = group_doc.get("name", gf.stem)

        for week_key in ("odd_week", "even_week"):
            week = group_doc.get("schedule", {}).get(week_key, {})
            for day, lessons in week.items():
                for lesson in lessons:
                    teacher_abbr: str | None = lesson.get("teacher")
                    if not teacher_abbr:
                        continue

                    match = match_teacher(teacher_abbr, db)
                    if match is None:
                        # Teacher not in DB (no кафедра page, or name mismatch)
                        key_abbr = teacher_abbr.strip()
                        if key_abbr not in unknown_names:
                            clean_abbr = _clean_teacher_abbr(key_abbr)
                            parsed = parse_name(clean_abbr)
                            unknown_names[key_abbr] = {
                                "staff_slug": "_unknown_" + match_key(clean_abbr),
                                "full_name": clean_abbr,
                                "abbreviated": parsed["abbreviated"] or clean_abbr,
                                "last": parsed["last"],
                                "first": parsed["first"],
                                "patronymic": parsed["patronymic"],
                                "position": "",
                                "institute_id": "",
                                "kafedra_name": "",
                                "_key": match_key(key_abbr),
                                "_unknown": True,
                            }
                        match = unknown_names[key_abbr]

                    slug = match["staff_slug"]
                    if slug not in buckets:
                        buckets[slug] = {"odd_week": _empty_week(), "even_week": _empty_week()}

                    entry = {k: v for k, v in lesson.items() if k != "teacher"}
                    entry["institute_id"] = institute_id
                    entry["group_name"] = group_name
                    buckets[slug][week_key][day].append(entry)

    # Write per-teacher files
    teachers_out_dir = Path(data_path) / "teachers"
    teachers_out_dir.mkdir(parents=True, exist_ok=True)

    all_teachers = db + list(unknown_names.values())
    written = 0
    for teacher in all_teachers:
        slug = teacher["staff_slug"]
        if slug not in buckets:
            continue
        doc = {
            "id": teacher.get("id"),
            "staff_slug": slug,
            "full_name": teacher.get("full_name", ""),
            "last": teacher.get("last", ""),
            "first": teacher.get("first", ""),
            "patronymic": teacher.get("patronymic", ""),
            "abbreviated": teacher.get("abbreviated", ""),
            "position": teacher.get("position", ""),
            "institute_id": teacher.get("institute_id", ""),
            "kafedra_name": teacher.get("kafedra_name", ""),
            "schedule": buckets[slug],
        }
        out = teachers_out_dir / f"{slug}.json"
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1

    # Also remove stale teacher files not in current set
    existing = set(f.stem for f in teachers_out_dir.glob("*.json"))
    current = {t["staff_slug"] for t in all_teachers if t["staff_slug"] in buckets}
    for stale in existing - current:
        (teachers_out_dir / f"{stale}.json").unlink(missing_ok=True)

    # Add unknown teachers to DB index with high IDs
    max_id = max((t.get("id") or 0 for t in db), default=0)
    for i, unk in enumerate(unknown_names.values(), start=max_id + 1):
        unk["id"] = i

    combined = db + list(unknown_names.values())

    # Update teachers.json with has_schedule flag
    for t in combined:
        t["has_schedule"] = t["staff_slug"] in buckets

    db_doc["teachers"] = combined
    db_doc["count"] = len(combined)
    teachers_path.write_text(
        json.dumps(db_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Written {written} teacher schedule files")
    print(f"Unknown teachers (schedule only): {len(unknown_names)}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-path", default=DATA_PATH)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    build(args.data_path)


if __name__ == "__main__":
    main()
