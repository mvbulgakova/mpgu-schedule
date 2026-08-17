# Chances Calculator (/shansy) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Команда `/shansy`: абитуриент присылает свои ЕГЭ («русский 78, общество 84, история 90») — бот подбирает программы МПГУ строго по его предметам (Приложение 1), для каждой показывает живую позицию из списков epk25 (баллы топ-K против КЦП-2026) и исторический диапазон проходных (архив mpgu.su, с ~2015), с честными дисклеймерами.

**Architecture:** Статические справочники (программы+ВИ+КЦП из официальных PDF) извлекаются один раз в закоммиченный `scraper/abitur/programs_2026.json`. История проходных собирается обходом архивных хабов mpgu.su (по ссылкам, не по шаблонам) в `admissions/history.json` на data-ветке (редкий workflow). Живой сигнал — существующий индекс списков epk25 (расширяется названиями направлений). Вся логика `/shansy` детерминирована, LLM не участвует.

**Tech Stack:** Python 3.12, requests+bs4+lxml (как в lists), pymupdf только в offline-скрипте извлечения. pytest.

---

## File Structure

- Create `scraper/abitur/extract_programs.py` — офлайн-скрипт: тексты Приложения 1 и КЦП → `programs_2026.json` (запускается один раз при реализации, результат коммитится).
- Create `scraper/abitur/programs_2026.json` — справочник: программа → код, направленность, форма, слоты ВИ (альтернативы), места КЦП-2026, платность(*).
- Modify `scraper/fetchers/lists_fetcher.py` — `crawl()` дополнительно возвращает meta: название направления/уровень для каждого кода списка.
- Modify `scraper/build_lists_index.py` — прокидывает meta в индекс.
- Create `scraper/fetchers/history_fetcher.py` — обход архивных хабов, поиск страниц «Конкурс и проходной балл».
- Create `scraper/parsers/passing_score_parser.py` — таблица года → строки {код, программа, форма, проходной, конкурс}.
- Create `scraper/build_admissions_index.py` — история по годам → `admissions/history.json` (матчинг к программам по коду+направленности+форме).
- Modify `scraper/storage/git_storage.py` — `write_admissions_history`.
- Create `.github/workflows/fetch-admissions.yml` — workflow_dispatch (история меняется раз в год).
- Create `scraper/abitur/shansy.py` — разбор сообщения с баллами, подбор программ, сборка ответа (live+история+места).
- Modify `scraper/telegram_bot.py` — `/shansy`, состояние `AWAITING_SCORES`, кнопка меню.
- Tests: `scraper/tests/test_programs_json.py`, `test_passing_score_parser.py`, `test_history_fetcher.py`, `test_shansy.py`, + дополнение `test_abitur_bot.py`.

---

## Task 1: Справочник программ (Приложение 1 + КЦП → JSON)

**Files:** Create `scraper/abitur/extract_programs.py`, `scraper/abitur/programs_2026.json`; Test `scraper/tests/test_programs_json.py`.

- [ ] **Step 1: Тест-инварианты справочника (падает — файла нет)**

```python
"""Инварианты справочника программ 2026 (Приложение 1 + КЦП)."""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

P = Path(__file__).resolve().parents[1] / "abitur" / "programs_2026.json"

def _load():
    return json.loads(P.read_text(encoding="utf-8"))

def test_file_exists_and_nonempty():
    data = _load()
    assert len(data["programs"]) > 80  # в Приложении 1 их сотни

def test_every_program_shape():
    for p in _load()["programs"]:
        assert re.match(r"\d{2}\.\d{2}\.\d{2}$", p["code"])
        assert p["name"] and p["form"]
        assert 2 <= len(p["exam_slots"]) <= 3
        subs = [s for slot in p["exam_slots"] for s in slot]
        assert any("русский" in s.lower() for s in subs)

def test_kcp_matched_for_most_budget_programs():
    progs = _load()["programs"]
    budget = [p for p in progs if not p.get("paid_only")]
    with_places = [p for p in budget if p.get("places")]
    assert len(with_places) >= 0.7 * len(budget)
```

- [ ] **Step 2: Реализовать `extract_programs.py`** — парсит `/tmp/pk26/programmy.txt` (блоки: код+направленность → форма → нумерованные слоты «1./2./3.» с альтернативами через «/», берём колонку «на базе среднего общего»; помета `*` → `paid_only`) и `/tmp/pk26/kcp_bvo.txt`+`kcp_spvo.txt` (программа+форма → места; матчинг по коду+нормализованной направленности+форме). Запустить, закоммитить JSON. Ошибки матчинга печатать в stderr для ручной проверки.
- [ ] **Step 3: Тесты зелёные; выборочная ручная сверка 5 программ с PDF.**
- [ ] **Step 4: Commit** `feat(shansy): programs+KCP reference extracted from official Appendix 1`.

## Task 2: Названия направлений в индексе списков

**Files:** Modify `scraper/fetchers/lists_fetcher.py`, `scraper/build_lists_index.py`; Test дополнить `test_lists_fetcher.py`.

- [ ] **Step 1: Тест:** `extract_view_links(html)` возвращает `[(code, title)]` — из `<a href=".../view?code=000000672">44.03.01 История</a>` берётся и код, и текст ссылки.
- [ ] **Step 2:** Реализовать `extract_view_links` (регэксп по `<a ...view?code=...>(.*?)</a>`, strip тегов); `crawl()` → `(pages, meta)` где `meta[code] = {"direction": title, "level": lvl}`; `build_lists_index.main` передаёт meta.
- [ ] **Step 3:** Тесты зелёные. **Step 4: Commit.**

## Task 3: История проходных (фетчер + парсер таблиц)

**Files:** Create `scraper/fetchers/history_fetcher.py`, `scraper/parsers/passing_score_parser.py`; Tests `test_history_fetcher.py`, `test_passing_score_parser.py`.

- [ ] **Step 1: Тест парсера** на фикстуре, повторяющей реальную структуру 2019 (заголовок «Направление подготовки / Образовательные программы, форма / Конкурс / Проходной балл», строки-факультеты без чисел пропускаются):

```python
FIX = """<table><tr><td>Направление подготовки</td><td>Образовательные программы, форма</td>
<td>Конкурс в 2019</td><td>Проходной балл 2019 года</td></tr>
<tr><td>Географический факультет</td></tr>
<tr><td>05.03.02\nГеография</td><td>Общая география\nОчная, 4 года</td><td>17.2</td><td>205</td></tr>
<tr><td>44.03.01\nПедагогическое образование</td><td>География\nОчная, 4 года</td><td>12.6</td><td>220</td></tr>
</table>"""
def test_parse_year_table():
    rows = parse_score_table(FIX, year=2019)
    assert rows[0] == {"year": 2019, "code": "05.03.02", "program": "Общая география",
                       "form": "очная", "passing": 205, "competition": 17.2}
    assert len(rows) == 2
```

- [ ] **Step 2: Реализовать парсер** (bs4; код — регэксп `\d\d\.\d\d\.\d\d` в 1-й ячейке; программа/форма — 2-я ячейка до/после переноса, форма нормализуется в {очная, очно-заочная, заочная}; проходной — int 3-значный; конкурс — float если есть; строки без кода/проходного пропускаются).
- [ ] **Step 3: Тест фетчера** (чистые функции): `find_year_pages(hub_html) -> {year: url}` по ссылкам, содержащим «конкурс» и «проходн» + год в тексте/URL; сетевой `collect_history(years)` идёт по известным хабам `priemnaja-kampanija-*` и «двухуровневым» ссылкам (в тестах не вызывается).
- [ ] **Step 4: Реализовать фетчер** (requests, ретраи как в lists_fetcher; список хабов константой — реальные URL из архива, включая `-2020-2021-gg`, `-2021-2022-gg`, `-2022`, `-2023`, `-2024`, `-2025`).
- [ ] **Step 5:** Тесты зелёные; живой мини-прогон на 2019 (≥200 строк). **Step 6: Commit.**

## Task 4: Индекс истории на data-ветке + workflow

**Files:** Create `scraper/build_admissions_index.py`, `.github/workflows/fetch-admissions.yml`; Modify `git_storage.py`; Test `test_build_admissions.py`.

- [ ] **Step 1: Тест** `build_history(rows, programs)`: строки лет матчятся к программам справочника по `code` + пересечению нормализованных слов направленности + форме; результат `{program_key: {"history": {2019: 220, ...}, "range3": [min,max], "last": (год, балл)}}`; программы без матча идут в `unmatched` (не теряются молча).
- [ ] **Step 2: Реализовать** + `GitStorage.write_admissions_history` (`admissions/history.json`).
- [ ] **Step 3: Workflow** `fetch-admissions.yml` — только `workflow_dispatch` (история статична), шаги как в `fetch-lists.yml`, запуск `python -m scraper.build_admissions_index`.
- [ ] **Step 4:** Тесты зелёные. **Step 5: Commit.**

## Task 5: Логика /shansy

**Files:** Create `scraper/abitur/shansy.py`; Test `scraper/tests/test_shansy.py`.

- [ ] **Step 1: Тесты:**

```python
def test_parse_scores_message():
    s = shansy.parse_scores("русский 78, общество 84 история 90")
    assert s == {"русский язык": 78, "обществознание": 84, "история": 90}

def test_parse_scores_rejects_garbage():
    assert shansy.parse_scores("привет") is None
    assert shansy.parse_scores("русский 178") is None  # балл 0..100

def test_match_programs_respects_exam_slots():
    programs = [{"code": "44.03.01", "name": "История и Обществознание", "form": "очная",
                 "exam_slots": [["история", "иностранный язык"], ["обществознание"], ["русский язык"]],
                 "places": 25}]
    got = shansy.match_programs({"русский язык": 70, "обществознание": 80, "история": 90}, programs)
    assert got[0]["total"] == 240
    # без обществознания программа не подходит
    assert shansy.match_programs({"русский язык": 70, "история": 90}, programs) == []

def test_format_includes_disclaimer_and_history():
    text = shansy.format_answer(matches=[...], history={...}, lists_index={...})
    assert "не гарант" in text.lower()
```

- [ ] **Step 2: Реализовать:** `SUBJECT_ALIASES` (рус/русский→«русский язык», общество/общага/общ→«обществознание», матем/профильная→«математика (профильная)», иняз/англ→«иностранный язык», информатика, физика, химия, биология, география, литература, история); `parse_scores` (пары «слово число», 0<балл≤100, минимум 2 предмета, обязателен русский); `match_programs` (на каждый слот — лучший из имеющихся предметов; все слоты закрыты → sum; сортировка по total-желаемости; программы с ДВИ помечаются «нужно ДВИ», paid_only — помечаются); `attach_live` (матч программы к спискам epk25 по коду+пересечению слов направленности; при уверенном матче — позиция суммы среди score_total и баллы топ-places); `format_answer` (топ-5: название, форма, места, live-строка, история range3+last, пометки) + дисклеймер.
- [ ] **Step 3:** Тесты зелёные. **Step 4: Commit.**

## Task 6: Интеграция в бот

**Files:** Modify `scraper/telegram_bot.py`, `scraper/abitur/faq.py`; Test дополнить `test_abitur_bot.py`.

- [ ] **Step 1: Тесты:** `/shansy` просит прислать баллы и ставит `AWAITING_SCORES`; сообщение с баллами при флаге → ответ подбора (с моком индексов); приоритет ввода: калькулятор часов > код списка > баллы; кнопка меню `open:shansy`.
- [ ] **Step 2: Реализовать:** intent `shansy` в `faq.route`; `AWAITING_SCORES: Dict[int,bool]`; в `handle_message` ветка после `AWAITING_CODE`; `_shansy_answer(text)` грузит `programs_2026.json` + `lists.fetch_index()` + history с CDN (свой `fetch_history()` в shansy с кэшем, graceful при отсутствии — «истории пока нет, показываю живые данные»).
- [ ] **Step 3:** Все тесты зелёные; selftest `/shansy`. **Step 4: Commit.**

## Task 7: Деплой

- [ ] Полный прогон тестов; merge в `main`; push; ручной запуск «Fetch Admissions» (история) и «Fetch Competitive Lists» (обновит meta с направлениями); проверка `/shansy` в Telegram.

## Self-Review
- Спек покрыт: подбор по своим ЕГЭ (T1+T5), live-позиция (T2+T5), история с ~2015 (T3+T4), диапазон вместо точки + дисклеймер (T5), приватность (история — только агрегаты таблиц, приказы в MVP не парсим — отмечено как расширение в спеке).
- Типы согласованы: `programs_2026.json` (T1) читают T4/T5; meta списков (T2) читает `attach_live` (T5); `history.json` (T4) читает T5.
- Плейсхолдеров нет; extraction-скрипт T1 запускается в ходе реализации, JSON коммитится и защищён инвариант-тестами.
