"""Долгоживущий обход: один запуск крутит цикл обновлений несколько часов.

Зачем. Расписание GitHub Actions — «по возможности»: 2026-08-05 при
cron */10 фактически случился ОДИН запуск за 2,3 часа, и данные двигались
только когда прогон запускали руками. Зато один запуск живёт часами
надёжно — на этом же держится бот. Поэтому вместо частого расписания
поднимаем одну задачу и обновляем данные изнутри неё.

Обход всех списков одним раннером упирается в лимит epk25 на адрес, поэтому
идём пачками с паузой (CRAWL_BATCH / CRAWL_BATCH_PAUSE): медленнее
шардированного обхода, но не требует ни расписания, ни шести раннеров.

Цикл переживает ошибку отдельного прохода: упасть целиком значит остановить
обновления до следующего запуска по расписанию, то есть, как выяснилось,
надолго.

Запуск: python -m scraper.crawl_loop --seconds 19800 --interval 900
"""
import argparse
import os
import time
import traceback


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--seconds", type=int,
                   default=int(os.environ.get("RUN_SECONDS", "19800")),
                   help="сколько всего работать")
    p.add_argument("--interval", type=int,
                   default=int(os.environ.get("CYCLE_SECONDS", "900")),
                   help="минимум секунд между НАЧАЛАМИ проходов")
    args = p.parse_args(argv)

    from scraper.build_lists_index import main as build_once

    deadline = time.time() + args.seconds
    cycle = 0
    print(f"Цикл обновлений запущен на {args.seconds}s, "
          f"проход не чаще чем раз в {args.interval}s", flush=True)
    while time.time() < deadline:
        cycle += 1
        started = time.time()
        print(f"\n=== проход {cycle} ===", flush=True)
        try:
            build_once()
        except Exception:  # noqa: BLE001
            # Один неудачный проход не повод останавливать обновления на часы.
            print("Проход упал, продолжаю цикл:", flush=True)
            traceback.print_exc()
        spent = time.time() - started
        left = deadline - time.time()
        if left <= 0:
            break
        nap = max(0.0, min(args.interval - spent, left))
        if nap:
            print(f"Проход занял {spent:.0f}s, сплю {nap:.0f}s "
                  f"(до конца {left / 60:.0f} мин)", flush=True)
            time.sleep(nap)
    print(f"Цикл завершён, проходов: {cycle}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
