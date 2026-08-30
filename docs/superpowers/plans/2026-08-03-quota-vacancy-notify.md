# Возврат вакантных квотных/БВИ мест в общий конкурс — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать пользователю (админу бота) инструмент, чтобы вручную посмотреть,
по каким направлениям есть незанятые квотные места (которые по правилам
должны вернуться в общий конкурс, но epk25 ещё не пересчитал), и разово
разослать подписчикам конкретного списка предварительную оценку их новой
позиции.

**Architecture:** Три новых поля из HTML epk25 (`seats_open`, `enrolled`,
`page_updated_at`) добавляются в существующий `build_lists_index.py` как
чисто аддитивные — старые формулы `places`/`general_seats`/`quota_seats` не
трогаем. Вся расчётная логика вакансий и текст уведомления живут в одном
чистом модуле `scraper/abitur/quota_vacancy.py` (без сети, без файлов —
только словарь `lists` на входе), поверх которого — два тонких CLI: один
read-only отчёт (я запускаю сама в чате) и один отправитель (запускается
только вручную через новый GitHub Actions workflow, т.к. только там есть
токен бота и подписчики).

**Tech Stack:** Python 3.12, pytest, stdlib `re`/`argparse`/`json`, GitHub
Actions (`workflow_dispatch` + `actions/cache`).

Спека: `docs/superpowers/specs/2026-08-03-quota-vacancy-notify-design.md`.

---

### Task 1: Новые поля epk25 в `build_lists_index.py`

**Files:**
- Modify: `scraper/build_lists_index.py:20-25` (регексы), `scraper/build_lists_index.py:140-143` (запись полей в `build_index`)
- Test: `scraper/tests/test_build_lists_index.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `scraper/tests/test_build_lists_index.py`:

```python
def test_build_index_parses_seats_open_enrolled_and_updated_at():
    # Реальный формат страницы epk25 (проверено вручную 03.08.26):
    # "Контрольные цифры приёма: 33 Зачислено: 3 Мест для зачисления: 30
    #  &nbsp; Дата и время обновления: 03.08.2026. 18:00 &nbsp; ..."
    view = VIEW_SIM.replace("<TABLE>",
        "Вид мест: основные места в рамках КЦП Контрольные цифры приёма: 33 "
        "Зачислено: 3 Мест для зачисления: 30 &nbsp; "
        "Дата и время обновления: 03.08.2026. 18:00 &nbsp; <TABLE>")
    meta = {"G": {"direction": "44.03.01 Тест", "form": "очная", "kind": "бюджет"}}
    md, _ = build_index({"G": view}, meta, updated_at="t", places_fn=lambda m: 33)
    g = md["lists"]["G"]
    assert g["seats_open"] == 30
    assert g["enrolled"] == 3
    assert g["page_updated_at"] == "2026-08-03T18:00:00+03:00"


def test_build_index_missing_new_fields_are_absent():
    meta = {"G": {"direction": "44.03.01 Тест", "form": "очная", "kind": "бюджет"}}
    md, _ = build_index({"G": VIEW_SIM}, meta, updated_at="t", places_fn=lambda m: 10)
    g = md["lists"]["G"]
    assert "seats_open" not in g
    assert "enrolled" not in g
    assert "page_updated_at" not in g
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `python -m pytest scraper/tests/test_build_lists_index.py::test_build_index_parses_seats_open_enrolled_and_updated_at -v`
Expected: FAIL — `assert 'seats_open' in g` fails (`KeyError`/`AssertionError`, поля ещё нет).

- [ ] **Step 3: Добавить регексы и парсинг**

В `scraper/build_lists_index.py` заменить блок регексов (строки 20-25):

```python
_KCP_RE = re.compile(r"Контрольные цифры при[её]ма:\s*(\d+)")
# «Вид мест» отличает общий конкурс от квотных списков, а «Учебное структурное
# подразделение» — головной кампус от филиалов (у филиала свой КЦП и свой
# конкурс, но одинаковое с кампусом название направления).
_VID_RE = re.compile(r"Вид мест:\s*([^\r\n]{0,80})")
_UNIT_RE = re.compile(r"Учебное структурное подразделение:\s*([^\r\n]{0,80})")
# Появляются на странице epk25 после того, как вуз обработал приказ о
# зачислении по этому списку. «Мест для зачисления» = КЦП минус уже
# зачисленные (открытые места), «Зачислено» — сколько уже зачислено именно
# по этому списку. «Дата и время обновления» — момент, когда САМА страница
# в последний раз пересчитывалась (не момент обхода нашим краулером) —
# нужно, чтобы понять, догнал ли epk25 конкретный подписанный приказ.
_SEATS_OPEN_RE = re.compile(r"Мест для зачисления:\s*(\d+)")
_ENROLLED_RE = re.compile(r"Зачислено:\s*(\d+)")
_UPDATED_RE = re.compile(
    r"Дата и время обновления:\s*(\d{2})\.(\d{2})\.(\d{4})\.\s*(\d{2}):(\d{2})")
```

Добавить рядом с `_parse_field` (после строки, где сейчас заканчивается
`_parse_field`, перед `_is_main_kcp`):

```python
def _parse_int_field(html: str, rx) -> Optional[int]:
    m = rx.search(_flat(html))
    return int(m.group(1)) if m else None


def _parse_updated_at(html: str) -> Optional[str]:
    m = _UPDATED_RE.search(_flat(html))
    if not m:
        return None
    day, month, year, hour, minute = (int(x) for x in m.groups())
    return dt.datetime(year, month, day, hour, minute,
                       tzinfo=dt.timezone(dt.timedelta(hours=3))
                       ).isoformat(timespec="seconds")
```

В `build_index()`, сразу после блока `unit = _parse_field(html, _UNIT_RE)` /
`if unit: m["unit"] = unit` (сейчас строки 140-142), добавить:

```python
        seats_open = _parse_int_field(html, _SEATS_OPEN_RE)
        if seats_open is not None:
            m["seats_open"] = seats_open
        enrolled = _parse_int_field(html, _ENROLLED_RE)
        if enrolled is not None:
            m["enrolled"] = enrolled
        page_updated_at = _parse_updated_at(html)
        if page_updated_at is not None:
            m["page_updated_at"] = page_updated_at
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `python -m pytest scraper/tests/test_build_lists_index.py -v`
Expected: PASS — все тесты в файле, включая два новых.

- [ ] **Step 5: Коммит**

```bash
git add scraper/build_lists_index.py scraper/tests/test_build_lists_index.py
git commit -m "feat: parse seats_open/enrolled/page_updated_at from epk25 pages"
```

---

### Task 2: `quota_vacancy.compute_group_vacancies` + `general_list_for_key`

**Files:**
- Create: `scraper/abitur/quota_vacancy.py`
- Test: `scraper/tests/test_quota_vacancy.py`

- [ ] **Step 1: Написать падающий тест**

Создать `scraper/tests/test_quota_vacancy.py`:

```python
"""Тесты расчёта вакантных квотных мест и текста уведомления (чисто, без сети).

Запуск: python -m pytest scraper/tests/test_quota_vacancy.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur.quota_vacancy import (compute_group_vacancies,
                                           general_list_for_key)

KEY = ("44.03.01 Русский язык и Литература", "очная", "Институт филологии")


def _quota_list(vid, kcp_epk, enrolled):
    return {"quota": True, "direction": KEY[0], "form": KEY[1], "unit": KEY[2],
            "vid_mest": vid, "kcp_epk": kcp_epk, "enrolled": enrolled}


def test_full_data_sums_vacant_across_quota_kinds():
    # Реальный кейс 03.08.26: особая 1/1, целевая 1/1, отдельная 7/9 —
    # 2 вакантных места по отдельной квоте, суммарно по группе.
    lists = {
        "Q1": _quota_list("особая квота", 1, 1),
        "Q2": _quota_list("целевая детализированная квота", 1, 1),
        "Q3": _quota_list("отдельная квота", 9, 7),
    }
    groups = compute_group_vacancies(lists)
    assert groups[KEY]["vacant"] == 2
    assert groups[KEY]["breakdown"] == [
        ("особая квота", 1, 1),
        ("целевая детализированная квота", 1, 1),
        ("отдельная квота", 9, 7),
    ]


def test_incomplete_data_excludes_whole_group():
    # Если хоть у одного квотного списка группы неизвестен enrolled —
    # группа целиком не участвует (не даём заниженного/ложного числа).
    lists = {
        "Q1": _quota_list("особая квота", 9, None),   # enrolled не распарсился
        "Q2": _quota_list("отдельная квота", 9, 7),
    }
    assert compute_group_vacancies(lists) == {}


def test_zero_vacant_group_not_included():
    lists = {"Q1": _quota_list("особая квота", 1, 1)}
    assert compute_group_vacancies(lists) == {}


def test_general_list_for_key_finds_main_kcp_match():
    lists = {
        "G": {"main_kcp": True, "direction": KEY[0], "form": KEY[1], "unit": KEY[2]},
        "Q1": _quota_list("особая квота", 1, 1),
    }
    assert general_list_for_key(lists, KEY) == "G"
    assert general_list_for_key(lists, ("другое", "очная", "X")) is None
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `python -m pytest scraper/tests/test_quota_vacancy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.abitur.quota_vacancy'`

- [ ] **Step 3: Реализовать**

Создать `scraper/abitur/quota_vacancy.py`:

```python
"""Незанятые квотные места программы и предварительная оценка позиции.

Считаем только по данным, которые epk25 уже отдал явно (`kcp_epk`,
`enrolled` на квотных списках) — при неполных данных группы честно
пропускаем, а не занижаем/завышаем (тот же принцип, что и в
build_lists_index.quota_by_key — см. спек 2026-08-03).
"""
from typing import Dict, List, Optional, Tuple

Key = Tuple[Optional[str], Optional[str], Optional[str]]


def _key(m: dict) -> Key:
    return (m.get("direction"), m.get("form"), m.get("unit"))


def compute_group_vacancies(lists: Dict[str, dict]) -> Dict[Key, dict]:
    """{(direction, form, unit): {"vacant": int, "breakdown": [(vid_mest, kcp_epk, enrolled), ...]}}

    Только для групп квотных списков, где у ВСЕХ известны и kcp_epk, и
    enrolled, и суммарный vacant > 0.
    """
    groups: Dict[Key, list] = {}
    for m in lists.values():
        if not m.get("quota"):
            continue
        groups.setdefault(_key(m), []).append(m)

    result: Dict[Key, dict] = {}
    for key, members in groups.items():
        if any(m.get("kcp_epk") is None or m.get("enrolled") is None
               for m in members):
            continue
        vacant = sum(max(m["kcp_epk"] - m["enrolled"], 0) for m in members)
        if vacant <= 0:
            continue
        result[key] = {
            "vacant": vacant,
            "breakdown": [(m.get("vid_mest"), m["kcp_epk"], m["enrolled"])
                          for m in members],
        }
    return result


def general_list_for_key(lists: Dict[str, dict], key: Key) -> Optional[str]:
    """Код общего списка (main_kcp=True) для той же (direction, form, unit)."""
    for lc, m in lists.items():
        if m.get("main_kcp") and _key(m) == key:
            return lc
    return None
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `python -m pytest scraper/tests/test_quota_vacancy.py -v`
Expected: PASS — все 4 теста.

- [ ] **Step 5: Коммит**

```bash
git add scraper/abitur/quota_vacancy.py scraper/tests/test_quota_vacancy.py
git commit -m "feat: compute vacant quota seats grouped by direction/form/unit"
```

---

### Task 3: `quota_vacancy.vacancy_for_list` + `format_report`

**Files:**
- Modify: `scraper/abitur/quota_vacancy.py`
- Test: `scraper/tests/test_quota_vacancy.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в `scraper/tests/test_quota_vacancy.py` (после существующих
импортов заменить строку импорта на):

```python
from scraper.abitur.quota_vacancy import (compute_group_vacancies,
                                           format_report,
                                           general_list_for_key,
                                           vacancy_for_list)
```

И добавить в конец файла:

```python
def test_vacancy_for_list_looks_up_by_general_code():
    lists = {
        "G": {"main_kcp": True, "direction": KEY[0], "form": KEY[1],
              "unit": KEY[2], "kcp_epk": 33},
        "Q1": _quota_list("отдельная квота", 9, 7),
    }
    info = vacancy_for_list(lists, "G")
    assert info["vacant"] == 2
    assert vacancy_for_list(lists, "НЕТ_ТАКОГО") is None


def test_format_report_lists_only_groups_with_vacancy():
    lists = {
        "G": {"main_kcp": True, "direction": KEY[0], "form": KEY[1],
              "unit": KEY[2], "kcp_epk": 33},
        "Q1": _quota_list("особая квота", 1, 1),
        "Q2": _quota_list("целевая детализированная квота", 1, 1),
        "Q3": _quota_list("отдельная квота", 9, 7),
    }
    report = format_report(lists)
    assert KEY[0] in report
    assert "вакантно квот: 2" in report
    assert "отдельная квота: 7/9" in report


def test_format_report_empty_when_no_vacancies():
    assert format_report({}) == "Незанятых квотных мест не найдено."
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `python -m pytest scraper/tests/test_quota_vacancy.py -v`
Expected: FAIL — `ImportError: cannot import name 'vacancy_for_list'`

- [ ] **Step 3: Реализовать**

Добавить в конец `scraper/abitur/quota_vacancy.py`:

```python
def vacancy_for_list(lists: Dict[str, dict], list_code: str) -> Optional[dict]:
    """Вакансии группы, к которой принадлежит ОБЩИЙ список list_code.

    Пересчитывает группировку заново (не кэш) — вызывающий (notify-скрипт)
    должен видеть самые свежие данные на момент отправки, а не отчётный снимок.
    """
    m = lists.get(list_code)
    if not m:
        return None
    return compute_group_vacancies(lists).get(_key(m))


def format_report(lists: Dict[str, dict]) -> str:
    """Текстовая таблица направлений с незанятыми квотными местами."""
    groups = compute_group_vacancies(lists)
    if not groups:
        return "Незанятых квотных мест не найдено."
    lines = []
    for key, info in sorted(groups.items(), key=lambda kv: -kv[1]["vacant"]):
        direction, form, unit = key
        general_code = general_list_for_key(lists, key)
        gm = lists.get(general_code, {}) if general_code else {}
        kcp = gm.get("kcp_epk")
        kcp_str = kcp if kcp is not None else "?"
        lines.append(f"{direction} | {form} | {unit or '-'} | "
                     f"список {general_code or '?'} | КЦП {kcp_str} | "
                     f"вакантно квот: {info['vacant']}")
        for vid, kcp_q, enrolled in info["breakdown"]:
            lines.append(f"    {vid}: {enrolled}/{kcp_q}")
    return "\n".join(lines)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `python -m pytest scraper/tests/test_quota_vacancy.py -v`
Expected: PASS — все 7 тестов в файле.

- [ ] **Step 5: Коммит**

```bash
git add scraper/abitur/quota_vacancy.py scraper/tests/test_quota_vacancy.py
git commit -m "feat: quota_vacancy.vacancy_for_list + human-readable report"
```

---

### Task 4: `quota_vacancy.format_notification`

**Files:**
- Modify: `scraper/abitur/quota_vacancy.py`
- Test: `scraper/tests/test_quota_vacancy.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в импорт (заменить строку импорта на):

```python
from scraper.abitur.quota_vacancy import (compute_group_vacancies,
                                           format_notification, format_report,
                                           general_list_for_key,
                                           vacancy_for_list)
```

И в конец файла:

```python
def test_format_notification_exact_text():
    expected = (
        "Предварительно: сейчас вы примерно 45-е из 33 (бюджет, "
        "«44.03.01 Тест», очная). По квотам этого направления пока есть "
        "незанятые места (~2) — по правилам они должны перейти в общий "
        "конкурс, но ещё не добавлены. Если добавят, ориентировочно вы "
        "будете ~45-е из ~35.\n\n"
        "Это предварительная прикидка по открытым данным, а не "
        "официальная информация — точная позиция обновится в живом "
        "списке. Следите: /spisok 1234567"
    )
    text = format_notification(pos=45, kcp=33, vacant=2,
                               direction="44.03.01 Тест", form="очная",
                               code="1234567")
    assert text == expected
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `python -m pytest scraper/tests/test_quota_vacancy.py::test_format_notification_exact_text -v`
Expected: FAIL — `ImportError: cannot import name 'format_notification'`

- [ ] **Step 3: Реализовать**

Добавить в конец `scraper/abitur/quota_vacancy.py`:

```python
def format_notification(pos: int, kcp: int, vacant: int, direction: str,
                        form: str, code: str) -> str:
    """Текст разового предупреждения подписчику общего списка.

    Явно помечен как прикидка (не гарантия) — те же формулировки, что и в
    prediction.format_prediction, чтобы не создавать ложной точности.
    """
    return (
        f"Предварительно: сейчас вы примерно {pos}-е из {kcp} (бюджет, "
        f"«{direction}», {form}). По квотам этого направления пока есть "
        f"незанятые места (~{vacant}) — по правилам они должны перейти в "
        f"общий конкурс, но ещё не добавлены. Если добавят, ориентировочно "
        f"вы будете ~{pos}-е из ~{kcp + vacant}.\n\n"
        f"Это предварительная прикидка по открытым данным, а не "
        f"официальная информация — точная позиция обновится в живом "
        f"списке. Следите: /spisok {code}"
    )
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `python -m pytest scraper/tests/test_quota_vacancy.py -v`
Expected: PASS — все 8 тестов в файле.

- [ ] **Step 5: Коммит**

```bash
git add scraper/abitur/quota_vacancy.py scraper/tests/test_quota_vacancy.py
git commit -m "feat: quota_vacancy.format_notification preliminary-estimate text"
```

---

### Task 5: CLI-отчёт `scraper/report_quota_vacancies.py`

**Files:**
- Create: `scraper/report_quota_vacancies.py`
- Test: `scraper/tests/test_report_quota_vacancies.py`

- [ ] **Step 1: Написать падающий тест**

Создать `scraper/tests/test_report_quota_vacancies.py`:

```python
"""Тест CLI-отчёта по вакантным квотным местам (read-only).

Запуск: python -m pytest scraper/tests/test_report_quota_vacancies.py -v
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.report_quota_vacancies import main


def test_report_prints_vacancy_table(tmp_path, capsys):
    meta = {"lists": {
        "G": {"main_kcp": True, "direction": "44.03.01 Тест", "form": "очная",
              "unit": "ИФ", "kcp_epk": 33},
        "Q1": {"quota": True, "direction": "44.03.01 Тест", "form": "очная",
               "unit": "ИФ", "vid_mest": "отдельная квота",
               "kcp_epk": 9, "enrolled": 7},
    }}
    meta_path = tmp_path / "lists_meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    rc = main([str(meta_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "вакантно квот: 2" in out


def test_report_no_vacancies_message(tmp_path, capsys):
    meta_path = tmp_path / "lists_meta.json"
    meta_path.write_text(json.dumps({"lists": {}}), encoding="utf-8")

    rc = main([str(meta_path)])

    assert rc == 0
    assert "Незанятых квотных мест не найдено." in capsys.readouterr().out
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `python -m pytest scraper/tests/test_report_quota_vacancies.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.report_quota_vacancies'`

- [ ] **Step 3: Реализовать**

Создать `scraper/report_quota_vacancies.py`:

```python
"""CLI: отчёт по незанятым квотным местам (read-only, без секретов, без сети).

Читает admissions/lists_meta.json (по умолчанию текущий каталог) и печатает
направления, где по квотам есть незанятые места, которые по правилам должны
вернуться в общий конкурс. Только для ручного просмотра перед решением, по
какому списку слать /notify_quota_seats.py — ничего не отправляет и не меняет.

Запуск: python -m scraper.report_quota_vacancies /tmp/data-wt/admissions/lists_meta.json
"""
import argparse
import json

from scraper.abitur import quota_vacancy


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("meta_path", nargs="?",
                        default="admissions/lists_meta.json")
    args = parser.parse_args(argv)
    with open(args.meta_path, encoding="utf-8") as f:
        lists = json.load(f)["lists"]
    print(quota_vacancy.format_report(lists))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `python -m pytest scraper/tests/test_report_quota_vacancies.py -v`
Expected: PASS — 2 теста.

- [ ] **Step 5: Коммит**

```bash
git add scraper/report_quota_vacancies.py scraper/tests/test_report_quota_vacancies.py
git commit -m "feat: read-only CLI report of vacant quota seats"
```

---

### Task 6: CLI-отправитель `scraper/notify_quota_seats.py`

**Files:**
- Create: `scraper/notify_quota_seats.py`
- Test: `scraper/tests/test_notify_quota_seats.py`

- [ ] **Step 1: Написать падающий тест**

Создать `scraper/tests/test_notify_quota_seats.py`:

```python
"""Тест CLI-отправителя предварительных уведомлений (сеть замокана).

Запуск: python -m pytest scraper/tests/test_notify_quota_seats.py -v
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scraper.notify_quota_seats as NQ


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_sends_only_to_subscribers_with_known_position(tmp_path, monkeypatch):
    meta = {"lists": {
        "G": {"main_kcp": True, "direction": "44.03.01 Тест", "form": "очная",
              "unit": "ИФ", "kcp_epk": 33},
        "Q1": {"quota": True, "direction": "44.03.01 Тест", "form": "очная",
               "unit": "ИФ", "vid_mest": "отдельная квота",
               "kcp_epk": 9, "enrolled": 7},
    }}
    meta_path = _write(tmp_path, "lists_meta.json", meta)
    subs = {
        "111": {"code": "1234567", "last": {"G": 45}},
        "222": {"code": "7654321", "last": {}},   # нет сохранённой позиции
    }
    subs_path = _write(tmp_path, "subs.json", subs)

    sent = []
    monkeypatch.setattr(NQ, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))
    monkeypatch.setattr(NQ.time, "sleep", lambda s: None)
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NQ.main(["--code", "G", "--subs-path", str(subs_path),
                 "--meta-path", str(meta_path)])

    assert rc == 0
    assert len(sent) == 1
    assert sent[0][0] == 111
    assert "45-е из 33" in sent[0][1]
    assert "~35" in sent[0][1]


def test_no_send_without_vacancy(tmp_path, monkeypatch, capsys):
    meta = {"lists": {
        "G": {"main_kcp": True, "direction": "D", "form": "очная",
              "unit": "U", "kcp_epk": 33},
    }}
    meta_path = _write(tmp_path, "lists_meta.json", meta)
    subs_path = _write(tmp_path, "subs.json", {})

    sent = []
    monkeypatch.setattr(NQ, "_send",
                        lambda token, chat_id, reply: sent.append((chat_id, reply.text)))
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    rc = NQ.main(["--code", "G", "--subs-path", str(subs_path),
                 "--meta-path", str(meta_path)])

    assert rc == 0
    assert sent == []
    assert "не найдено" in capsys.readouterr().out


def test_missing_bot_token_aborts(tmp_path, monkeypatch):
    meta_path = _write(tmp_path, "lists_meta.json", {"lists": {}})
    subs_path = _write(tmp_path, "subs.json", {})
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    rc = NQ.main(["--code", "G", "--subs-path", str(subs_path),
                 "--meta-path", str(meta_path)])

    assert rc == 1
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `python -m pytest scraper/tests/test_notify_quota_seats.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.notify_quota_seats'`

- [ ] **Step 3: Реализовать**

Создать `scraper/notify_quota_seats.py`:

```python
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

    with open(args.meta_path, encoding="utf-8") as f:
        lists = json.load(f)["lists"]
    m = lists.get(args.code)
    if not m:
        print(f"Список {args.code} не найден в {args.meta_path}.")
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
    sent, skipped = 0, 0
    for chat, sub in subs.items():
        pos = (sub.get("last") or {}).get(args.code)
        if pos is None:
            skipped += 1
            continue
        text = quota_vacancy.format_notification(
            pos=pos, kcp=kcp, vacant=info["vacant"],
            direction=m.get("direction", "?"), form=m.get("form", "?"),
            code=sub["code"])
        try:
            _send(token, int(chat), Reply(text, []))
            sent += 1
        except Exception as e:
            print(f"notify error {chat}: {e}")
            skipped += 1
        time.sleep(0.1)
    print(f"Отправлено: {sent}, пропущено: {skipped} "
         f"(всего подписчиков: {len(subs)}), вакантно квот: {info['vacant']}, "
         f"КЦП: {kcp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `python -m pytest scraper/tests/test_notify_quota_seats.py -v`
Expected: PASS — 3 теста.

- [ ] **Step 5: Коммит**

```bash
git add scraper/notify_quota_seats.py scraper/tests/test_notify_quota_seats.py
git commit -m "feat: one-off CLI to notify list subscribers of vacant quota seats"
```

---

### Task 7: Workflow `quota-notify.yml`

**Files:**
- Create: `.github/workflows/quota-notify.yml`

Ручного теста тут нет (workflow_dispatch не запускается локально) — проверка
только через реальный запуск пользователем в GitHub UI после мёржа. Шаги
ниже — просто написание файла и коммит.

- [ ] **Step 1: Создать workflow**

Создать `.github/workflows/quota-notify.yml`:

```yaml
name: Quota Notify

# Ручной запуск (Actions → Quota Notify → Run workflow, ввести код общего
# списка). Разовая рассылка подписчикам этого списка предварительной оценки
# позиции с учётом вакантных квотных мест — см. docs/superpowers/specs/
# 2026-08-03-quota-vacancy-notify-design.md. НЕ автоматизировано намеренно:
# решение слать или нет — за пользователем, после просмотра
# scraper/report_quota_vacancies.py.
# Секреты репозитория: BOT_TOKEN (Settings → Secrets → Actions).

on:
  workflow_dispatch:
    inputs:
      list_code:
        description: "Код общего списка (например 000000700)"
        required: true

permissions:
  contents: read

jobs:
  notify:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install deps
        run: pip install "anthropic>=0.30"

      # Тот же кэш, что использует bot-poll.yml, — восстанавливаем ТЕКУЩИЙ
      # снимок подписок (актуальность до часа, этого достаточно для прикидки).
      - name: Restore subscriptions
        uses: actions/cache/restore@v4
        with:
          path: subs.json
          key: bot-state-notify-${{ github.run_id }}
          restore-keys: |
            bot-state-
            bot-subs-

      - name: Fetch fresh lists_meta.json from data branch
        run: |
          git fetch --depth=1 origin data
          git show origin/data:admissions/lists_meta.json > lists_meta.json

      - name: Send notification
        env:
          BOT_TOKEN: ${{ secrets.BOT_TOKEN }}
          SUBS_PATH: subs.json
          LISTS_META_PATH: lists_meta.json
          LIST_CODE: ${{ github.event.inputs.list_code }}
        run: python -m scraper.notify_quota_seats --code "$LIST_CODE"
```

- [ ] **Step 2: Коммит**

```bash
git add .github/workflows/quota-notify.yml
git commit -m "ci: add manual workflow to notify list subscribers of quota vacancies"
```

---

### Task 8: Полный прогон тестов и публикация ветки

**Files:** нет новых — только проверка.

- [ ] **Step 1: Прогнать весь набор тестов**

Run: `python -m pytest scraper/tests/ -v`
Expected: PASS — все тесты, включая существующие (никаких регрессов в
`places`/`general_seats`/`quota_seats`, т.к. Task 1 только добавляет новые
поля).

- [ ] **Step 2: Запушить ветку**

```bash
git push -u origin claude/bot-document-submission-loe0v6
```

- [ ] **Step 3: Сообщить пользователю**

После пуша — сказать, что можно запускать
`python -m scraper.report_quota_vacancies <путь до lists_meta.json>` в чате
по запросу, и что рассылка по конкретному списку теперь доступна как
workflow «Quota Notify» в Actions (ввод — код списка).
