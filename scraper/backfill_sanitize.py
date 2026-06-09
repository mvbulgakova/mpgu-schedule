#!/usr/bin/env python3
"""Применяет финальную очистку (sanitize_groups) к уже сохранённым данным
в ветке `data`, без повторного парсинга источников.

Очищает per-group файлы institutes/*/groups/*.json:
  - удаляет точные дубли пар внутри дня;
  - сортирует пары по времени;
  - вытаскивает подгруппу из текста (subject/teacher/room/notes);
  - чистит аудиторию ("ауд. 403" -> "403", "332 / ауд. 333" -> "332 / 333");
  - достраивает slot из времени начала.

Использование:
    python scraper/backfill_sanitize.py /path/to/data-branch [--dry-run]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.normalizer.schedule_normalizer import sanitize_groups


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data_root", help="корень рабочей копии ветки data")
    ap.add_argument("--dry-run", action="store_true", help="только показать статистику, не писать")
    args = ap.parse_args()

    root = Path(args.data_root)
    files = sorted(root.glob("institutes/*/groups/*.json"))
    if not files:
        print(f"Не найдено файлов групп в {root}/institutes/*/groups/", file=sys.stderr)
        return 1

    changed = 0
    for fp in files:
        try:
            group = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ✗ {fp}: {e}", file=sys.stderr)
            continue
        before = json.dumps(group, ensure_ascii=False, sort_keys=True)
        sanitize_groups([group])
        after = json.dumps(group, ensure_ascii=False, sort_keys=True)
        if before != after:
            changed += 1
            if not args.dry_run:
                fp.write_text(json.dumps(group, ensure_ascii=False, indent=2), encoding="utf-8")

    verb = "изменилось бы" if args.dry_run else "обновлено"
    print(f"Файлов всего: {len(files)}; {verb}: {changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
