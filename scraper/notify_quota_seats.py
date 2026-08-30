"""CLI: разовая рассылка предварительной оценки позиции подписчикам списка.

Требует BOT_TOKEN (секрет бота) и subs.json (кэш подписок) — оба существуют
только внутри GitHub Actions (см. docs/superpowers/specs/
2026-08-03-quota-vacancy-notify-design.md). Запускается ТОЛЬКО вручную через
workflow_dispatch «Quota Notify» — не автоматически, не по расписанию.

Запуск: python -m scraper.notify_quota_seats --code 000000700
"""
import argparse
import json
import os
import time

from scraper.abitur import follow, quota_vacancy
from scraper.telegram_bot import Reply, _send


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True, help="код общего списка")
    parser.add_argument("--subs-path",
                        default=os.environ.get("SUBS_PATH", "subs.json"))
    parser.add_argument("--meta-path",
                        default=os.environ.get("LISTS_META_PATH",
                                               "lists_meta.json"))
    args = parser.parse_args(argv)

    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN не задан — выход.")
        return 1

    try:
        with open(args.meta_path, encoding="utf-8") as f:
            lists = json.load(f)["lists"]
    except Exception as e:
        print(f"Не удалось прочитать {args.meta_path}: {e}")
        return 0
    m = lists.get(args.code)
    if not m:
        print(f"Список {args.code} не найден в {args.meta_path}.")
        return 0
    if not m.get("main_kcp"):
        print(f"Список {args.code} — не общий список (main_kcp не установлен), "
             "рассылка не выполнена.")
        return 0

    info = quota_vacancy.vacancy_for_list(lists, args.code)
    if not info or info["vacant"] <= 0:
        print(f"Вакантных квотных мест для {args.code} не найдено/неизвестно "
             "— рассылка не выполнена.")
        return 0

    kcp = m.get("kcp_epk")
    if kcp is None:
        print(f"КЦП списка {args.code} неизвестен — рассылка не выполнена.")
        return 0

    subs = follow.load(args.subs_path)
    sent, no_position, failed = 0, 0, 0
    for chat, sub in subs.items():
        try:
            pos = (sub.get("last") or {}).get(args.code)
            if pos is None:
                no_position += 1
                continue
            text = quota_vacancy.format_notification(
                pos=pos, kcp=kcp, vacant=info["vacant"],
                direction=m.get("direction", "?"), form=m.get("form", "?"),
                code=sub.get("code", "?"))
            _send(token, int(chat), Reply(text, []))
            sent += 1
        except Exception as e:
            print(f"notify error {chat}: {e}")
            failed += 1
        time.sleep(0.1)
    print(f"Отправлено: {sent}, без позиции: {no_position}, с ошибкой: {failed} "
         f"(всего подписчиков: {len(subs)}), вакантно квот: {info['vacant']}, "
         f"КЦП: {kcp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
