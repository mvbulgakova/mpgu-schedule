"""CLI: отчёт по незанятым квотным местам (read-only, без секретов, без сети).

Читает admissions/lists_meta.json (по умолчанию текущий каталог) и печатает
направления, где по квотам есть незанятые места, которые по правилам должны
вернуться в общий конкурс. Только для ручного просмотра перед решением, по
какому списку слать /notify_quota_seats.py — ничего не отправляет и не меняет.

Запуск: python -m scraper.report_quota_vacancies /tmp/data-wt/admissions/lists_meta.json
"""
import argparse
import json

from scraper.abitur import quota_vacancy


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("meta_path", nargs="?",
                        default="admissions/lists_meta.json")
    args = parser.parse_args(argv)
    with open(args.meta_path, encoding="utf-8") as f:
        lists = json.load(f)["lists"]
    print(quota_vacancy.format_report(lists))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
