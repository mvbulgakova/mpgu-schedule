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
    n_subs = len(subs)

    # Iterate SUBSCRIBERS once, not the (grown list × subscriber) cross
    # product — with ~50 grown lists in production and hundreds of
    # subscribers, looping lists-outer/subscribers-inner means every
    # subscriber is visited once per grown list regardless of whether they
    # track it, which does not scale. Here each subscriber is visited once,
    # and only the grown lists THEY actually track are processed (and
    # sleep-paced) for them.
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
        # Progress checkpoint so a killed/timed-out job still leaves a log
        # trail of what was done so far, instead of nothing until the end.
        if processed % 50 == 0 or processed == n_subs:
            print(f"... обработано подписчиков: {processed}/{n_subs}, "
                 f"отправлено: {total_sent}, с ошибкой: {total_failed}")

    # total_no_position across all lists is a meaningless cross-product count
    # at multi-list scale (N grown lists × M subscribers who don't track that
    # particular list) — omitted from the aggregate summary on purpose. The
    # per-list "не следят" figure below is the interpretable version.
    print(f"Отправлено всего: {total_sent}, с ошибкой: {total_failed} "
         f"(всего подписчиков: {n_subs}), списков с ростом КЦП: {len(grown)}")
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
