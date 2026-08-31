"""Разослать всем подписчикам конкретный PDF приказа, который вахта пропустила.

Одноразовая утилита, а не штатный путь. Вахта раньше метила страницу
разосланной, как только скачивала её; если один pdf не докачался (или был
добавлен позже), он оставался невиданным навсегда. 2026-08-31 так случилось
с part-2 приказа на dogovor. Штатный `_check_orders` теперь ходит по
страницам и добирает недостающее пофайлово, но людям, которые уже пропустили
part-2, ретро-добор нужен вручную — этим скриптом.

Запуск:
    BOT_TOKEN=xxx SUBS_PATH=./subs.json python -m scraper.notify_missing_pdf \\
        https://mpgu.su/wp-content/uploads/2026/08/pk26_...31-08-26_part-2.pdf

Можно перечислить несколько URL — все уйдут одним сообщением. Скрипт также
добавит их в SEEN_PDFS, чтобы штатный вахтер не разослал ещё раз.
"""
import os
import sys
import time

from scraper.abitur import follow, orders_watch
from scraper import telegram_bot as bot


def main() -> int:
    urls = [u for u in sys.argv[1:] if u.startswith("http")]
    if not urls:
        print("Использование: python -m scraper.notify_missing_pdf <pdf_url> [...]",
              file=sys.stderr)
        return 2
    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN не задан.", file=sys.stderr)
        return 1
    if bot.SUBS_PATH:
        bot.SUBS.update(follow.load(bot.SUBS_PATH))
        bot._load_seen_orders()
    subs = [k for k in bot.SUBS if k != bot._ORDERS_KEY]
    print(f"Подписчиков: {len(subs)}, файлов к отправке: {len(urls)}")

    files = []                             # [(bytes, filename, url)]
    for u in urls:
        try:
            data = bot._fetch(u)
            files.append((data, orders_watch.pdf_filename(u), u))
            print(f"  скачан: {u} ({len(data)} байт)")
        except Exception as e:  # noqa: BLE001
            print(f"  НЕ скачался {u}: {e}", file=sys.stderr)
    if not files:
        print("Ни один файл не скачан — выход.", file=sys.stderr)
        return 1

    # Дата и страница берутся из первого URL — приказ у него один и тот же
    # (иначе не одна досылка, а две разные — запусти скрипт дважды).
    date = orders_watch.order_date(files[0][2]) or ""
    page_hint = files[0][2].rsplit("/", 1)[0] + "/"
    n = len(files)
    if n == 1:
        header = (f"📎 <b>Приказ о зачислении{f' от {date}' if date else ''}: "
                  f"добавлен файл на mpgu.su.</b>")
        tail = ("Файл был выложен позже основной рассылки — ищите в нём "
                "свой уникальный код.")
    else:
        header = (f"📎 <b>Приказ о зачислении{f' от {date}' if date else ''}: "
                  f"добавлены файлы ({n}) на mpgu.su.</b>")
        tail = ("Файлы были выложены позже основной рассылки — ищите в них "
                "свой уникальный код.")
    text = f"{header}\n\n{tail}"

    sent = 0
    for chat in subs:
        try:
            bot._send(token, int(chat), bot.Reply(text, []))
            for data, name, _ in files:
                bot._send_document(token, int(chat), data, name)
            sent += 1
            time.sleep(0.15)               # вежливый интервал Telegram
        except Exception as e:  # noqa: BLE001
            print(f"chat {chat}: {e}", file=sys.stderr)
            if "403" in str(e):
                bot.SUBS.pop(str(chat), None)
    for _, _, u in files:
        bot.SEEN_PDFS.add(u)
    if bot.SUBS_PATH:
        bot._save_seen_orders()
    print(f"Разослано подписчикам: {sent}/{len(subs)}, файлов: {len(files)}")
    print(f"SEEN_PDFS пополнён — штатная вахта не отправит эти файлы повторно.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
