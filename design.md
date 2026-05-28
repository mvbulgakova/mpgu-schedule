# Design: МПГУ Расписание

## Общая архитектура

Система состоит из трёх независимых частей, связанных через Git-ветку `data`:

```
┌─────────────┐    ветка main     ┌──────────────────────┐
│   Scraper   │ ─── push to ───▶  │  GitHub Actions       │
│  (Python)   │     data branch   │  (расписание 2×/день) │
└─────────────┘                   └──────────────────────┘
                                           │
                                    data branch
                                    (JSON-файлы)
                                           │
                                           ▼
                                  ┌──────────────┐
                                  │     PWA      │
                                  │ (React + TS) │
                                  │  GitHub Pages│
                                  └──────────────┘
```

Код живёт в ветке `main`, данные — в ветке `data`. PWA читает данные напрямую из raw.githubusercontent.com. Нет бэкенда, нет базы данных.

---

## Scraper

### Структура (`scraper/`)

```
main.py                  — оркестратор, запускает все институты параллельно
config/institutes.json   — 16 институтов: URL, тип парсера, fallback
fetchers/
  site_fetcher.py        — краулер страниц МПГУ, возвращает список ссылок
  file_fetcher.py        — скачивает файлы, считает MD5
parsers/
  base.py                — BaseParser + ParseResult(groups, confidence, warnings)
  pdf_parser.py          — pdfplumber → camelot → Tesseract OCR → Gemini → Claude vision
  docx_parser.py         — python-docx, три формата таблиц
  excel_parser.py        — openpyxl
  gsheets_parser.py      — CSV-экспорт Google Sheets
  nextcloud_parser.py    — определяет формат файла, диспатчит в нужный парсер
  exam_parser.py         — расписание экзаменов/сессии
normalizer/
  schedule_normalizer.py — normalize_day/time/lesson_type + sanitize_groups (финальная очистка)
storage/
  git_storage.py         — запись JSON, git add/commit/push в ветку data
utils/
  hash_tracker.py        — MD5 кеш, CHANGED_ONLY режим
  gemini_client.py       — Gemini vision fallback для image-based PDF
  claude_client.py       — Claude vision fallback для image-based PDF
teachers/
  crawler.py, normalizer.py — БД преподавателей и их расписаний
```

### Поток данных

```
institutes.json
      │
      ▼
site_fetcher  →  список URL (pdf/docx/xlsx/gsheets/nextcloud)
      │
      ▼
file_fetcher  →  bytes + MD5
      │
      ├── hash_tracker: пропустить если не изменилось (CHANGED_ONLY=true)
      │
      ▼
parser.parse()  →  ParseResult
  └── groups: [{name, year, form, degree, schedule}, ...]
      schedule: {odd_week: {monday: [Lesson, ...], ...}, even_week: {...}}
      │
      ├── _filter_invalid_groups + _merge_duplicate_groups (дедуп групп)
      ├── sanitize_groups (финальная очистка пар, см. ниже)
      │
      ▼
GitStorage.write_schedule()  →  data/institutes/{id}/schedule.json   (манифест)
                                 data/institutes/{id}/groups/{name}.json
GitStorage.write_index()     →  data/meta/index.json
```

### PDF-парсер: пять уровней

| Уровень | Инструмент | Когда |
|---------|-----------|-------|
| 1 | pdfplumber | всегда первый; confidence ≥ 0.65 → готово |
| 2 | camelot | если pdfplumber не справился и PDF не image-based |
| 3 | Tesseract OCR | распознавание текста на image-based PDF |
| 4 | Gemini vision | image-based PDF (нужен GEMINI_API_KEY) |
| 5 | Claude vision | image-based PDF (нужен ANTHROPIC_API_KEY) |

Confidence считается как доля строк расписания с распознанными временем и занятием.
Поле `parser_used` в данных показывает, какой уровень сработал по факту.

#### Форматы МПГУ-таблиц в PDF

- **Format 1a** — одна группа, день недели написан вертикально (буква за буквой)
- **Format 2** — одна группа, страницы-продолжения без заголовка
- **Format 3** — несколько групп в параллельных колонках
- **Journalism** — время в col 3+ (вместо col 1), день в col 0; нормализуется через `_normalize_journalism_table`
- **Shifted header** — заголовок с группами не проходит `_is_mpgu_timetable_format` из-за пустого col 0; fallback ищет группы во всех таблицах до первой MPGU-таблицы

#### Защиты от потери данных

- `CHANGED_ONLY=false` — принудительный полный перепарс
- Если парсер вернул 0 групп при ненулевом кеше → используется кеш, не перезаписывается
- Anomaly detection: если число групп упало >60% — создаётся GitHub Issue

### DOCX-парсер: три формата

| Формат | Признак | Парсер |
|--------|---------|--------|
| По дням (колонки) | ≥3 дня недели в заголовке | `_parse_day_columns` |
| Несколько групп | `\d{2,3} ГРУППА` в строке заголовка | `_parse_multi_group_cols` |
| Плоский (строки = занятия) | день + время в колонках | `_parse_flat` |

### Финальная очистка: `sanitize_groups`

Единая нормализация, применяемая к результату **любого** парсера перед записью
(`scraper/normalizer/schedule_normalizer.py`, тесты — `scraper/tests/test_sanitize.py`):

- **Дедупликация пар** — внутри дня удаляются только полностью идентичные записи
  (двойной append из нескольких файлов/страниц); различающиеся по преподавателю,
  типу или подгруппе сохраняются.
- **Сортировка** пар внутри дня по времени начала.
- **Подгруппа** — извлекается из subject/teacher/room/notes: скобочный формат
  `(п/г 1)` и свободный `1 п/гр`; длинные слепленные ячейки не трогаются.
- **Аудитория** — убираются маркеры `ауд.` (`ауд. 403` → `403`; PWA сама дописывает
  «ауд. », иначе выходило «ауд. ауд. 403»); несколько аудиторий сохраняются
  (`332 / ауд. 333` → `332 / 333`); препод, затесавшийся в `room`, выносится в `teacher`.
- **slot** — достраивается из времени начала по сетке `TIME_SLOTS`.

Одноразовый backfill уже сохранённых данных без перепарса — `scraper/backfill_sanitize.py`.

---

## Формат данных (ветка `data`)

```
data/
  meta/
    index.json          — список институтов, groups_count, статус, updated_at
    hashes.json         — MD5 всех скачанных файлов (для CHANGED_ONLY)
    teachers.json       — индекс преподавателей
    alerts.json         — аномалии последнего прогона (только если они есть)
  institutes/
    {id}/
      schedule.json         — манифест института (список групп без расписаний)
      groups/{name}.json    — расписание одной группы
      exams.json            — расписание экзаменов/сессии (если есть)
  teachers/
    {slug}.json             — расписание одного преподавателя
```

Расписания вынесены в отдельный файл на группу, чтобы PWA грузила только
нужную группу, а не весь институт. `schedule.json` хранит лёгкий манифест.

### schedule.json (манифест)

```json
{
  "institute_id": "geography",
  "institute_name": "Географический факультет",
  "short_name": "ГФ",
  "academic_year": "2025-2026",
  "updated_at": "2026-05-20T19:31:04Z",
  "parser_used": "pdfplumber",
  "version": 1,
  "groups": [
    { "name": "БOФ34-ГЕО2501", "file": "БOФ34-ГЕО2501",
      "year": null, "form": "full_time", "degree": "bachelor" }
  ]
}
```

### institutes/{id}/groups/{name}.json (одна группа)

```json
{
  "name": "БOФ34-ГЕО2501",
  "year": null,
  "form": "full_time",
  "degree": "bachelor",
  "schedule": {
    "odd_week":  { "monday": [Lesson, ...], "tuesday": [...], ... },
    "even_week": { "monday": [Lesson, ...], ... }
  }
}
```

### Lesson

```json
{
  "slot": 2,
  "time_start": "11:00",
  "time_end": "12:35",
  "subject": "Геоморфология",
  "type": "lecture",
  "teacher": "Доц. Иванов А.В.",
  "room": "А-101",
  "subgroup": null,
  "notes": ""
}
```

---

## PWA

**Стек:** React 18 + TypeScript + Vite + TailwindCSS + Zustand + TanStack Query + idb

**Деплой:** GitHub Pages (`gh-pages` branch), CDN для данных — `raw.githubusercontent.com/…/data`

### Структура (`pwa/src/`)

```
App.tsx                  — корневой компонент, навигация по состоянию
store/index.ts           — Zustand: selectedInstituteId, selectedGroupName, showEvenWeek
services/scheduleApi.ts  — fetch index.json, манифеста, групп, преподавателей, экзаменов
                           (с fallback-зеркалом данных)
hooks/
  useSchedule.ts         — TanStack Query обёртки
  useOfflineCache.ts     — IndexedDB кеш для офлайн-режима
  useNotifications.ts    — push-уведомления о ближайшей паре
components/
  InstituteSelector      — список институтов
  GroupSelector          — список групп института
  WeekSchedule           — расписание на неделю (чётная/нечётная)
  DayCard                — расписание одного дня
  LessonCard             — одно занятие
  TeacherSearch/View     — поиск и расписание преподавателя
  ExamScheduleView       — расписание экзаменов
```

### Офлайн-режим

Данные кешируются в IndexedDB через `useOfflineCache`. При отсутствии сети PWA показывает последние загруженные данные с плашкой "Офлайн".

### Чётность недели

Текущая неделя определяется по ISO-номеру недели: чётный номер = чётная неделя. Пользователь может переключить вручную кнопкой в шапке.

---

## CI/CD

### `scrape.yml` — сбор данных

- Расписание: `0 5,17 * * *` (08:00 и 20:00 МСК)
- Можно запустить вручную с `institute_id` для одного института
- Использует два checkout: `main` (код) + `data` (данные)
- При аномалиях создаёт GitHub Issue

### `deploy-pwa.yml` — деплой фронтенда

- Триггер: push в `main` с изменениями в `pwa/`
- Собирает Vite, деплоит на GitHub Pages
- `VITE_DATA_URL` указывает на raw.githubusercontent.com/…/data

---

## Известные ограничения

| Ограничение | Причина |
|-------------|---------|
| Image-based PDF | Требует GEMINI_API_KEY / ANTHROPIC_API_KEY; без них группы не извлекаются |
| ЗФО (заочная форма) | Использует даты вместо дней недели; парсер не поддерживает |
| DOCX старые форматы | python-docx иногда не читает `.doc` (только `.docx`) |
| Двухподгрупповые ячейки | Препод/аудитория второй подгруппы иногда лежат в `notes`, а не отдельной парой |
