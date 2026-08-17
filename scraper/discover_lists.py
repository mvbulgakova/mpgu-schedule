"""Найти состав конкурсных списков (без снятия самих списков).

Отдельный шаг, чтобы при обходе на нескольких раннерах поиск шёл ОДИН раз:
уровни и направления — это ~48 последовательных страниц, и делать их в каждой
доле значит умножить эту работу на число раннеров.

Запуск: python -m scraper.discover_lists --out entries.json
"""
import argparse
import json
import sys

from scraper.fetchers import lists_fetcher as LF


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)

    entries, stats = LF.discover()
    if stats["levels_failed"]:
        # Пропущенный уровень = целый пласт списков молча исчезнет из индекса.
        print(f"ОШИБКА: не прочитаны уровни {stats['levels_failed']}", file=sys.stderr)
        return 1
    if not entries:
        print("ОШИБКА: не найдено ни одного списка", file=sys.stderr)
        return 1

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"entries": entries, "stats": stats}, f, ensure_ascii=False)
    print(f"Найдено списков: {len(entries)} "
          f"(направлений {stats['directions_total']}, "
          f"не прочитано {stats['directions_failed']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
