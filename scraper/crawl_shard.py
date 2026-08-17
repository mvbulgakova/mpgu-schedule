"""Обход ОДНОЙ доли конкурсных списков — для запуска на нескольких раннерах.

epk25 ограничивает число одновременных соединений с одного IP: 2026-08-05 с
раннера GitHub пул на 50 соединений уронил все 667 страниц, а на 8 потоках
обход шёл 49 минут и не уложился в таймаут. При этом с другого адреса те же
страницы отдаются за 1–2 секунды и держат 48 потоков без единой ошибки. Значит
упираемся не в скорость сайта, а в лимит на адрес — и лечится это не числом
потоков, а разными адресами: несколько раннеров, каждый берёт свою долю.

Каждая доля отдаёт УЖЕ РАЗОБРАННЫЕ строки (parse_pages), а не HTML: страницы
весят на порядок больше, и таскать их между шагами незачем. Индекс собирается
одним шагом над объединением долей — симуляция глобальная, по частям её
посчитать нельзя.

Запуск: python -m scraper.crawl_shard --index 0 --of 6 --out shard0.json
"""
import argparse
import json
import sys

from scraper.build_lists_index import parse_pages
from scraper.fetchers import lists_fetcher as LF


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--index", type=int, required=True, help="номер доли, с нуля")
    p.add_argument("--of", type=int, required=True, help="всего долей")
    p.add_argument("--out", required=True, help="куда писать JSON доли")
    p.add_argument("--entries", help="JSON от scraper.discover_lists; без него "
                                     "доля ищет списки сама")
    p.add_argument("--workers", type=int, default=LF.DEFAULT_VIEW_WORKERS)
    args = p.parse_args(argv)

    if args.entries:
        entries = json.load(open(args.entries, encoding="utf-8"))["entries"]
    else:
        entries, stats = LF.discover()
        if stats["levels_failed"]:
            # Пропущенный уровень = целый пласт списков молча исчезнет из
            # индекса. Лучше уронить долю, чем отдать сборке неполный набор.
            print(f"ОШИБКА: не прочитаны уровни {stats['levels_failed']}",
                  file=sys.stderr)
            return 1
    mine = LF.shard_of(entries, args.index, args.of)
    print(f"Всего списков: {len(entries)}, моя доля {args.index}/{args.of}: {len(mine)}",
          flush=True)

    pages, meta, fetch_stats = LF.fetch_views(
        {c: entries[c] for c in mine}, workers=args.workers)
    parsed = parse_pages(pages, meta)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"parsed": parsed, "stats": fetch_stats,
                   "discovered": len(entries), "assigned": len(mine)}, f,
                  ensure_ascii=False)
    print(f"Готово: {len(parsed)} списков, не снято {fetch_stats['views_failed']}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
