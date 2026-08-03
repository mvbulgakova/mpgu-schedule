"""CLI: разовая рассылка подтверждённого роста КЦП подписчикам общих списков.

Требует BOT_TOKEN (секрет бота) и subs.json (кэш подписок) — оба существуют
только внутри GitHub Actions. Сравнивает baseline-снимок lists_meta.json с
текущим и рассылает подписчикам каждого общего списка, у которого kcp_epk
подтверждённо вырос (см. scraper.abitur.quota_vacancy.seats_increased).

Запуск: python -m scraper.notify_seats_increased \
    --baseline-path baseline_meta.json --meta-path lists_meta.json
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
    parser.add_argument("--meta-path",
                        default=os.environ.get("LISTS_META_PATH",
                                               "lists_meta.json"))
    parser.add_argument("--subs-path",
                        default=os.environ.get("SUBS_PATH", "subs.json"))
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
        with open(args.meta_path, encoding="utf-8") as f:
            current_lists = json.load(f)["lists"]
    except Exception as e:
        print(f"Не удалось прочитать {args.meta_path}: {e}")
        return 0

    grown = quota_vacancy.seats_increased(baseline_lists, current_lists)
    if not grown:
        print("Списков с увеличенным КЦП не найдено.")
        return 0

    subs = follow.load(args.subs_path)

    total_sent, total_no_position, total_failed = 0, 0, 0
    breakdown = []
    for code, info in grown.items():
        list_sent = 0
        for chat, sub in subs.items():
            try:
                pos = (sub.get("last") or {}).get(code)
                if pos is None:
                    total_no_position += 1
                    continue
                text = quota_vacancy.format_seats_increased(
                    old=info["old"], new=info["new"],
                    direction=info["direction"], form=info["form"],
                    code=sub.get("code", "?"))
                _send(token, int(chat), Reply(text, []))
                total_sent += 1
                list_sent += 1
            except Exception as e:
                print(f"notify error {chat} ({code}): {e}")
                total_failed += 1
            time.sleep(0.1)
        breakdown.append((code, info, list_sent))

    print(f"Отправлено всего: {total_sent}, без позиции: {total_no_position}, "
         f"с ошибкой: {total_failed} (всего подписчиков: {len(subs)}), "
         f"списков с ростом КЦП: {len(grown)}")
    for code, info, list_sent in breakdown:
        print(f"  {code}: {info['direction']} | {info['form']} | "
             f"{info['old']}→{info['new']} — отправлено: {list_sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
