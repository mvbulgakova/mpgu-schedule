"""CLI: разовая рассылка уведомлений о росте бюджетных мест, вычисленном
из официального приказа о зачислении, а не из живых данных epk25.

Источник роста — scraper.abitur.quota_vacancy.seats_increased_from_order:
берёт baseline-снимок lists_meta.json (kcp_epk общих и квотных списков)
и записи, извлечённые парсером приказа
(scraper.parsers.enrollment_order.parse_order_pdf_text) — доступно для
любого направления, упомянутого в приказе, даже если epk25 сам ещё не
пересчитал kcp_epk (в отличие от notify_seats_increased.py).

--exclude-path — опциональный JSON-список кодов, уже уведомлённых через
mode=seats_increased (по живым данным epk25), чтобы не слать подписчику
два уведомления про один и тот же список.

Запуск: python -m scraper.notify_seats_increased_from_order \
    --baseline-path baseline_meta.json --order-records-path order_records.json
"""
import argparse
import json
import os
import time

from scraper.abitur import follow, quota_vacancy
from scraper.telegram_bot import Reply, _send


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-path",
                        default=os.environ.get("BASELINE_META_PATH",
                                               "baseline_meta.json"))
    parser.add_argument("--order-records-path",
                        default=os.environ.get("ORDER_RECORDS_PATH",
                                               "order_records.json"))
    parser.add_argument("--subs-path",
                        default=os.environ.get("SUBS_PATH", "subs.json"))
    parser.add_argument("--exclude-path",
                        default=os.environ.get("EXCLUDE_CODES_PATH"))
    args = parser.parse_args(argv)

    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN не задан — выход.")
        return 1

    try:
        with open(args.baseline_path, encoding="utf-8") as f:
            baseline_lists = json.load(f)["lists"]
    except Exception as e:
        print(f"Не удалось прочитать {args.baseline_path}: {e}")
        return 0

    try:
        with open(args.order_records_path, encoding="utf-8") as f:
            order_records = json.load(f)
    except Exception as e:
        print(f"Не удалось прочитать {args.order_records_path}: {e}")
        return 0

    grown = quota_vacancy.seats_increased_from_order(baseline_lists, order_records)

    if args.exclude_path:
        try:
            with open(args.exclude_path, encoding="utf-8") as f:
                exclude = set(json.load(f))
            grown = {code: info for code, info in grown.items()
                     if code not in exclude}
        except Exception as e:
            print(f"Не удалось прочитать {args.exclude_path}: {e}")

    if not grown:
        print("Списков с увеличенным КЦП (по приказу) не найдено.")
        return 0

    subs = follow.load(args.subs_path)
    n_subs = len(subs)

    # Та же схема, что notify_seats_increased.py: подписчики — внешний
    # цикл, разросшиеся списки — внутренний, чтобы не получить cross
    # product (списки × подписчики), а посылать только реальные совпадения.
    total_sent, total_failed = 0, 0
    per_list_sent = {code: 0 for code in grown}
    per_list_no_position = {code: 0 for code in grown}
    processed = 0
    for chat, sub in subs.items():
        processed += 1
        try:
            last = sub.get("last") or {}
            tracked = [code for code in grown if last.get(code) is not None]
        except Exception as e:
            print(f"notify error {chat}: {e}")
            total_failed += 1
            tracked = []
        for code in grown:
            if code not in tracked:
                per_list_no_position[code] += 1
        for code in tracked:
            try:
                info = grown[code]
                text = quota_vacancy.format_seats_increased(
                    old=info["old"], new=info["new"],
                    direction=info["direction"], form=info["form"],
                    code=sub.get("code", "?"), enrolled=info.get("enrolled"))
                _send(token, int(chat), Reply(text, []))
                total_sent += 1
                per_list_sent[code] += 1
                print(f"-> отправлено: chat={chat}, список={code} "
                     f"(отправлено всего: {total_sent})")
            except Exception as e:
                print(f"notify error {chat} ({code}): {e}")
                total_failed += 1
            time.sleep(0.1)
        if processed % 50 == 0 or processed == n_subs:
            print(f"... обработано подписчиков: {processed}/{n_subs}, "
                 f"отправлено: {total_sent}, с ошибкой: {total_failed}")

    print(f"Отправлено всего: {total_sent}, с ошибкой: {total_failed} "
         f"(всего подписчиков: {n_subs}), списков с ростом КЦП (приказ): "
         f"{len(grown)}")
    breakdown = [(code, info, per_list_sent[code], per_list_no_position[code])
                for code, info in grown.items()]
    for code, info, list_sent, list_no_position in sorted(
            breakdown, key=lambda b: b[2], reverse=True):
        print(f"  {code}: {info['direction']} | {info['form']} | "
             f"{info['old']}→{info['new']} — отправлено: {list_sent}, "
             f"не следят: {list_no_position}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
