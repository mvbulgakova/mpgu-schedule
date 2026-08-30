"""CLI: разовая точечная рассылка подписчикам одного списка.

Для случаев, когда предыдущее авто-уведомление про конкретный список
содержало ошибку и её нужно поправить адресно, не дожидаясь следующего
цикла обычных рассылок (см. notify_seats_increased.py,
notify_seats_increased_from_order.py, notify_quota_seats.py).

Текст рассылки берётся как есть (без форматирования) и уходит всем
подписчикам, у кого этот код есть среди отслеживаемых списков (то же
условие "last.get(code) is not None", что и в остальных notify-скриптах)
— то есть именно тем, кто мог получить исходное сообщение.

Запуск: python -m scraper.notify_correction --list-code 000000690 \
    --message "текст поправки"
"""
import argparse
import os
import time

from scraper.abitur import follow
from scraper.telegram_bot import Reply, _send


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-code", required=True, help="код списка")
    parser.add_argument("--message", default=os.environ.get("CORRECTION_MESSAGE"))
    parser.add_argument("--subs-path",
                        default=os.environ.get("SUBS_PATH", "subs.json"))
    args = parser.parse_args(argv)

    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN не задан — выход.")
        return 1

    if not args.message:
        print("--message (или CORRECTION_MESSAGE) не задан — выход.")
        return 1

    subs = follow.load(args.subs_path)
    n_subs = len(subs)

    sent, failed = 0, 0
    for chat, sub in subs.items():
        try:
            last = sub.get("last") or {}
            tracked = last.get(args.list_code) is not None
        except Exception as e:
            print(f"notify error {chat}: {e}")
            failed += 1
            continue
        if not tracked:
            continue
        try:
            _send(token, int(chat), Reply(args.message, []))
            sent += 1
            print(f"-> отправлено: chat={chat} (отправлено всего: {sent})")
        except Exception as e:
            print(f"notify error {chat}: {e}")
            failed += 1
        time.sleep(0.1)

    print(f"Отправлено всего: {sent}, с ошибкой: {failed} "
         f"(всего подписчиков: {n_subs}, список: {args.list_code})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
