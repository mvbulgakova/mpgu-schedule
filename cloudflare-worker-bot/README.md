# Telegram-бот расписания МПГУ

Cloudflare Worker, принимающий вебхуки Telegram. Пользователь шлёт код группы
(или его часть) — бот ищет в `meta/groups.json` (data-ветка, через прокси-воркер)
и отвечает парами на сегодня с учётом чётности недели.

## Развёртывание

1. Создайте бота у [@BotFather](https://t.me/BotFather), получите `BOT_TOKEN`.
2. (Опц.) если прокси данных живёт не на `https://mpgu-schedule.workers.dev`,
   поправьте `DATA_BASE` в `worker.js`.
3. Деплой и секреты:
   ```sh
   cd cloudflare-worker-bot
   wrangler deploy
   wrangler secret put BOT_TOKEN
   wrangler secret put WEBHOOK_SECRET   # любая строка
   ```
4. Зарегистрируйте вебхук (один раз):
   ```sh
   curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://mpgu-schedule-bot.<subdomain>.workers.dev&secret_token=<WEBHOOK_SECRET>"
   ```

## Команды

- `/start`, `/help` — справка.
- любой текст — поиск группы по коду (гомоглифы/регистр/пробелы игнорируются).
  Один результат → пары на сегодня; несколько → список для уточнения.

## Зависимость от данных

Бот читает `meta/groups.json` — плоский индекс групп, который генерирует
`scraper/build_group_index.py` и коммитит workflow `scrape.yml` в data-ветку.
