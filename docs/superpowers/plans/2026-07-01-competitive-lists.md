# Competitive Lists Position Checker — Implementation Plan (подпроект B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Абитуриент присылает боту уникальный код — бот показывает все направления МПГУ, где он есть в конкурсных списках (позиция, сумма баллов, приоритет, согласие, БВИ, статус, время обновления).

**Architecture:** Периодический скрейп `epk25.mpgu.su` (server-rendered HTML) → индекс `{уникальный код → позиции}` в data-ветке → бот читает индекс через jsDelivr. Парсинг и построение индекса — чистые функции с фикстурами; сеть изолирована. Следует существующему паттерну проекта (`fetchers/`, `parsers/`, `GitStorage`, workflow с checkout data-ветки).

**Tech Stack:** Python 3.12, `requests` (honors HTTPS_PROXY), `beautifulsoup4`+`lxml` (парсинг; bs4 нормализует регистр uppercase-тегов epk25), stdlib. pytest.

---

## File Structure

- Create `scraper/parsers/competitive_list_parser.py` — парсер страницы `view?code=` → строки.
- Create `scraper/fetchers/lists_fetcher.py` — извлечение ссылок 3 уровней (чистые функции) + тонкий обходчик на `requests`.
- Create `scraper/build_lists_index.py` — сборка индекса (чистая `build_index`) + запись через `GitStorage`.
- Create `scraper/abitur/lists.py` — чтение индекса с jsDelivr, `lookup`, `format_positions`.
- Modify `scraper/storage/git_storage.py` — метод `write_lists_index`.
- Modify `scraper/telegram_bot.py` — команда `/spisok` + состояние `AWAITING_CODE` + приоритет ввода.
- Create `.github/workflows/fetch-lists.yml` — периодический скрейп.
- Tests: `scraper/tests/test_competitive_list_parser.py`, `test_lists_fetcher.py`, `test_build_lists_index.py`, `test_abitur_lists.py`, `test_abitur_bot_lists.py`.

Порядок колонок в таблице `view` (стабильный экспорт МПГУ):
`0 № · 1 Уникальный код · 2 Согласие · 3 ПЗ · 4 ОВП · 5 ВПП · 6 Основание БВИ · 7 Сумма конкурсных баллов · 8 Сумма за ВИ · 9 ВИ1 · 10 ВИ2 · 11 ВИ3 · 12 ИД · 13 ПП · 14 Информация о рассмотрении · 15 Причина отказа · 16 Высший проходной приоритет`.

---

## Task 1: Парсер конкурсного списка

**Files:**
- Create: `scraper/parsers/competitive_list_parser.py`
- Test: `scraper/tests/test_competitive_list_parser.py`

- [ ] **Step 1: Написать падающий тест на фикстуре**

Файл `scraper/tests/test_competitive_list_parser.py`:

```python
"""Тесты парсера конкурсного списка epk25.

Запуск: python -m pytest scraper/tests/test_competitive_list_parser.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.parsers.competitive_list_parser import parse_view

# Минимальная фикстура структуры epk25 (uppercase-теги, R-классы, пустые ячейки как <SPAN>).
FIXTURE = """
<HTML><BODY>
<TABLE>
<TR CLASS=R16><TD>№</TD><TD>Уникальный код</TD><TD>Наличие согласия на зачисление</TD>
<TD>ПЗ</TD><TD>ОВП</TD><TD>ВПП</TD><TD>Основание приема БВИ</TD>
<TD>Сумма конкурсных баллов</TD><TD>Сумма баллов за ВИ</TD><TD>ВИ 1</TD><TD>ВИ 2</TD><TD>ВИ 3</TD>
<TD>ИД</TD><TD>ПП</TD><TD>Информация о рассмотрении заявления</TD><TD>Причина отказа</TD>
<TD>Высший проходной приоритет</TD></TR>
<TR CLASS=R18><TD>1</TD><TD>1281839</TD><TD>+</TD><TD>28</TD><TD><SPAN></SPAN></TD><TD><SPAN></SPAN></TD>
<TD><SPAN></SPAN></TD><TD>290</TD><TD>290</TD><TD>96</TD><TD>94</TD><TD>100</TD><TD>0</TD>
<TD><SPAN></SPAN></TD><TD>На рассмотрении</TD><TD><SPAN></SPAN></TD><TD><SPAN></SPAN></TD></TR>
<TR CLASS=R19><TD>2</TD><TD>1300500</TD><TD><SPAN></SPAN></TD><TD>1</TD><TD><SPAN></SPAN></TD><TD><SPAN></SPAN></TD>
<TD>Без ВИ</TD><TD>310</TD><TD>300</TD><TD>100</TD><TD>100</TD><TD>100</TD><TD>10</TD>
<TD><SPAN></SPAN></TD><TD>Рекомендован</TD><TD><SPAN></SPAN></TD><TD><SPAN></SPAN></TD></TR>
</TABLE>
</BODY></HTML>
"""


def test_parse_view_returns_rows():
    rows = parse_view(FIXTURE)
    assert len(rows) == 2
    r = rows[0]
    assert r["position"] == 1
    assert r["unique_code"] == "1281839"
    assert r["consent"] is True
    assert r["priority_pz"] == 28
    assert r["score_total"] == 290
    assert r["id_points"] == 0
    assert r["bvi"] is False
    assert r["status"] == "На рассмотрении"


def test_parse_view_second_row_bvi_and_no_consent():
    rows = parse_view(FIXTURE)
    r = rows[1]
    assert r["unique_code"] == "1300500"
    assert r["consent"] is False
    assert r["bvi"] is True
    assert r["score_total"] == 310
    assert r["status"] == "Рекомендован"


def test_parse_view_empty_table():
    assert parse_view("<HTML><BODY><TABLE></TABLE></BODY></HTML>") == []
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest scraper/tests/test_competitive_list_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: scraper.parsers.competitive_list_parser`.

- [ ] **Step 3: Реализовать `scraper/parsers/competitive_list_parser.py`**

```python
"""Парсер страницы конкурсного списка epk25 (/competitive-list/view?code=...).

Таблица приходит с uppercase-тегами; BeautifulSoup нормализует регистр.
Строки абитуриентов опознаются по первой ячейке-числу (позиция).
"""
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

# Индексы колонок (стабильный порядок экспорта МПГУ).
C_POS, C_CODE, C_CONSENT, C_PZ, C_OVP, C_VPP, C_BVI = 0, 1, 2, 3, 4, 5, 6
C_TOTAL, C_VI_SUM, C_VI1, C_VI2, C_VI3, C_ID, C_PP, C_STATUS, C_REJECT = 7, 8, 9, 10, 11, 12, 13, 14, 15
MIN_CELLS = 15


def _int(s: str) -> Optional[int]:
    s = (s or "").strip()
    return int(s) if s.lstrip("-").isdigit() else None


def _cell(cells: List[str], i: int) -> str:
    return cells[i].strip() if i < len(cells) else ""


def parse_view(html: str) -> List[Dict]:
    soup = BeautifulSoup(html or "", "lxml")
    rows: List[Dict] = []
    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) < MIN_CELLS:
            continue
        pos = _int(_cell(cells, C_POS))
        code = _cell(cells, C_CODE)
        if pos is None or not code.isdigit():
            continue  # заголовки/служебные строки
        rows.append({
            "position": pos,
            "unique_code": code,
            "consent": bool(_cell(cells, C_CONSENT)),
            "priority_pz": _int(_cell(cells, C_PZ)),
            "priority_ovp": _int(_cell(cells, C_OVP)),
            "priority_vpp": _int(_cell(cells, C_VPP)),
            "bvi": bool(_cell(cells, C_BVI)),
            "score_total": _int(_cell(cells, C_TOTAL)),
            "score_vi": _int(_cell(cells, C_VI_SUM)),
            "id_points": _int(_cell(cells, C_ID)),
            "status": _cell(cells, C_STATUS),
            "reject_reason": _cell(cells, C_REJECT),
        })
    return rows
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python -m pytest scraper/tests/test_competitive_list_parser.py -v`
Expected: PASS (3 теста). (Если нет `bs4`/`lxml`: `pip install beautifulsoup4 lxml`.)

- [ ] **Step 5: Коммит**

```bash
git add scraper/parsers/competitive_list_parser.py scraper/tests/test_competitive_list_parser.py
git commit -m "feat(lists): parser for epk25 competitive list pages"
```

---

## Task 2: Извлечение ссылок и обходчик

**Files:**
- Create: `scraper/fetchers/lists_fetcher.py`
- Test: `scraper/tests/test_lists_fetcher.py`

- [ ] **Step 1: Написать падающие тесты извлечения ссылок**

Файл `scraper/tests/test_lists_fetcher.py`:

```python
"""Тесты извлечения ссылок из страниц epk25 (чистые функции, без сети).

Запуск: python -m pytest scraper/tests/test_lists_fetcher.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.fetchers import lists_fetcher as LF

STRUCTURAL = """
<a href="/competitive-list/index">Competitive lists</a>
<a href="/competitive-list/direction?educationLevel=basic_higher_education&amp;university=main_university&amp;structuralUnit=1">Институт истории</a>
<a href="/competitive-list/direction?educationLevel=basic_higher_education&amp;university=anapa_branch">Анапский филиал</a>
"""

DIRECTION = """
<a href="/competitive-list/view?code=000000672">44.03.01 История</a>
<a href="/competitive-list/view?code=000000673">46.03.01 История</a>
<a href="/competitive-list/index">назад</a>
"""


def test_extract_direction_links():
    links = LF.extract_direction_links(STRUCTURAL)
    assert len(links) == 2
    assert all("competitive-list/direction" in u for u in links)
    assert all(u.startswith("https://epk25.mpgu.su") for u in links)


def test_extract_view_codes():
    codes = LF.extract_view_codes(DIRECTION)
    assert codes == ["000000672", "000000673"]


def test_structural_url_for_level():
    u = LF.structural_url("basic_higher_education")
    assert u == ("https://epk25.mpgu.su/competitive-list/structural"
                 "?educationLevel=basic_higher_education")
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest scraper/tests/test_lists_fetcher.py -v`
Expected: FAIL — нет модуля.

- [ ] **Step 3: Реализовать `scraper/fetchers/lists_fetcher.py`**

```python
"""Обход конкурсных списков epk25: уровень → подразделение → направление → view.

Извлечение ссылок — чистые функции (тестируемы без сети). Сетевой обход — тонкий
слой на requests (honors HTTPS_PROXY), с вежливой паузой и ретраями.
"""
import re
import time
from html import unescape
from typing import Dict, List

BASE = "https://epk25.mpgu.su"
LEVELS = ["basic_higher_education", "specialist", "specialized_higher_education",
          "magistracy", "secondary_vocational_education"]

_UA = {"User-Agent": "MPGU-Abitur-Bot/1.0 (+https://mpgu.su)"}


def structural_url(level: str) -> str:
    return f"{BASE}/competitive-list/structural?educationLevel={level}"


def extract_direction_links(html: str) -> List[str]:
    hrefs = re.findall(r'href="(/competitive-list/direction\?[^"]*)"', html or "")
    return [BASE + unescape(h) for h in hrefs]


def extract_view_codes(html: str) -> List[str]:
    codes = re.findall(r'/competitive-list/view\?code=([0-9]+)', html or "")
    seen, out = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


def _get(url: str, retries: int = 3) -> str:
    import requests
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=_UA, timeout=30)
            if r.status_code == 200:
                return r.text
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def crawl(levels: List[str] = None, pause: float = 0.3) -> Dict[str, str]:
    """Возвращает {code -> html страницы view}. Сеть; в тестах не вызывается."""
    levels = levels or LEVELS
    pages: Dict[str, str] = {}
    for lvl in levels:
        try:
            struct = _get(structural_url(lvl))
        except Exception:
            continue
        for dir_url in extract_direction_links(struct):
            time.sleep(pause)
            try:
                dhtml = _get(dir_url)
            except Exception:
                continue
            for code in extract_view_codes(dhtml):
                if code in pages:
                    continue
                time.sleep(pause)
                try:
                    pages[code] = _get(f"{BASE}/competitive-list/view?code={code}")
                except Exception:
                    continue
    return pages
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python -m pytest scraper/tests/test_lists_fetcher.py -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Коммит**

```bash
git add scraper/fetchers/lists_fetcher.py scraper/tests/test_lists_fetcher.py
git commit -m "feat(lists): epk25 link extraction and crawler"
```

---

## Task 3: Построение индекса

**Files:**
- Create: `scraper/build_lists_index.py`
- Modify: `scraper/storage/git_storage.py`
- Test: `scraper/tests/test_build_lists_index.py`

- [ ] **Step 1: Написать падающий тест сборки индекса**

Файл `scraper/tests/test_build_lists_index.py`:

```python
"""Тесты сборки индекса конкурсных списков (чисто, без сети).

Запуск: python -m pytest scraper/tests/test_build_lists_index.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.build_lists_index import build_index

VIEW = """
<TABLE>
<TR><TD>№</TD><TD>Уникальный код</TD><TD>Согласие</TD><TD>ПЗ</TD><TD>ОВП</TD><TD>ВПП</TD>
<TD>БВИ</TD><TD>Сумма</TD><TD>ВИсум</TD><TD>ВИ1</TD><TD>ВИ2</TD><TD>ВИ3</TD><TD>ИД</TD><TD>ПП</TD>
<TD>Статус</TD><TD>Отказ</TD></TR>
<TR><TD>1</TD><TD>111</TD><TD>+</TD><TD>1</TD><TD></TD><TD></TD><TD></TD><TD>290</TD><TD>290</TD>
<TD>96</TD><TD>94</TD><TD>100</TD><TD>0</TD><TD></TD><TD>Рекомендован</TD><TD></TD></TR>
<TR><TD>2</TD><TD>222</TD><TD></TD><TD>2</TD><TD></TD><TD></TD><TD></TD><TD>250</TD><TD>250</TD>
<TD>80</TD><TD>80</TD><TD>90</TD><TD>0</TD><TD></TD><TD>На рассмотрении</TD><TD></TD></TR>
</TABLE>
"""


def test_build_index_maps_codes_to_positions():
    pages = {"000000672": VIEW}
    meta = {"000000672": {"direction": "44.03.01 История",
                          "level": "basic_higher_education", "university": "main_university"}}
    idx = build_index(pages, meta, updated_at="2026-07-01T20:00:00+03:00")
    assert idx["updated_at"] == "2026-07-01T20:00:00+03:00"
    assert idx["lists"]["000000672"]["count"] == 2
    assert idx["lists"]["000000672"]["direction"] == "44.03.01 История"
    e = idx["codes"]["111"][0]
    assert e["list"] == "000000672"
    assert e["position"] == 1
    assert e["score_total"] == 290
    assert e["consent"] is True
    assert idx["codes"]["222"][0]["position"] == 2


def test_build_index_code_in_multiple_lists():
    pages = {"A": VIEW, "B": VIEW}
    meta = {"A": {"direction": "d1"}, "B": {"direction": "d2"}}
    idx = build_index(pages, meta, updated_at="t")
    assert len(idx["codes"]["111"]) == 2
    assert {e["list"] for e in idx["codes"]["111"]} == {"A", "B"}
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest scraper/tests/test_build_lists_index.py -v`
Expected: FAIL — нет модуля.

- [ ] **Step 3: Добавить метод хранения в `scraper/storage/git_storage.py`**

Добавить в класс `GitStorage` (рядом с `write_index`, ориентир — строки 67-79) метод:

```python
    def write_lists_index(self, index: dict):
        _write_json(self.data_path / "admissions" / "lists_index.json", index)
```

(Функция-хелпер `_write_json` уже есть в файле и делает `mkdir(parents=True)`.)

- [ ] **Step 4: Реализовать `scraper/build_lists_index.py`**

```python
"""Сборка индекса конкурсных списков epk25 и запись в data-ветку.

build_index — чистая (given HTML → index). Точка входа main() выполняет обход и коммит.
"""
import datetime as dt
import os
from typing import Dict

from scraper.parsers.competitive_list_parser import parse_view


def build_index(pages: Dict[str, str], meta: Dict[str, dict], updated_at: str) -> dict:
    lists: Dict[str, dict] = {}
    codes: Dict[str, list] = {}
    for code_list, html in pages.items():
        rows = parse_view(html)
        m = dict(meta.get(code_list, {}))
        m["count"] = len(rows)
        m.setdefault("url",
                     f"https://epk25.mpgu.su/competitive-list/view?code={code_list}")
        lists[code_list] = m
        for r in rows:
            codes.setdefault(r["unique_code"], []).append({
                "list": code_list,
                "position": r["position"],
                "score_total": r["score_total"],
                "consent": r["consent"],
                "priority_pz": r["priority_pz"],
                "bvi": r["bvi"],
                "status": r["status"],
            })
    return {"updated_at": updated_at, "campaign": "2026", "lists": lists, "codes": codes}


def main() -> int:
    from scraper.fetchers import lists_fetcher as LF
    from scraper.storage.git_storage import GitStorage

    # meta собираем параллельно обходу: код -> контекст направления.
    # Здесь простая версия — контекст берётся из view-страницы отдельно не парсится,
    # поэтому meta минимальна (url). Расширяемо: прокинуть контекст из crawl().
    pages = LF.crawl()
    meta = {code: {} for code in pages}
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec="seconds")
    index = build_index(pages, meta, updated_at=now)

    data_path = os.environ.get("DATA_PATH", "data")
    storage = GitStorage(data_path)
    storage.write_lists_index(index)
    storage.commit_and_push(f"lists: обновление индекса конкурсных списков ({now})")
    print(f"Списков: {len(index['lists'])}, кодов: {len(index['codes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `python -m pytest scraper/tests/test_build_lists_index.py -v`
Expected: PASS (2 теста).

- [ ] **Step 6: Коммит**

```bash
git add scraper/build_lists_index.py scraper/storage/git_storage.py scraper/tests/test_build_lists_index.py
git commit -m "feat(lists): build competitive-list index and store to data branch"
```

---

## Task 4: Чтение индекса и форматирование в боте

**Files:**
- Create: `scraper/abitur/lists.py`
- Test: `scraper/tests/test_abitur_lists.py`

- [ ] **Step 1: Написать падающие тесты lookup/format**

Файл `scraper/tests/test_abitur_lists.py`:

```python
"""Тесты чтения индекса конкурсных списков (lookup/format), без сети.

Запуск: python -m pytest scraper/tests/test_abitur_lists.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import lists as L

INDEX = {
    "updated_at": "2026-07-01T20:00:00+03:00", "campaign": "2026",
    "lists": {"000000672": {"direction": "44.03.01 История",
                            "url": "https://epk25.mpgu.su/competitive-list/view?code=000000672"}},
    "codes": {"1281839": [{"list": "000000672", "position": 1, "score_total": 290,
                           "consent": False, "priority_pz": 28, "bvi": False,
                           "status": "На рассмотрении"}]},
}


def test_lookup_found_and_missing():
    assert L.lookup(INDEX, "1281839")
    assert L.lookup(INDEX, "0000") == []
    assert L.lookup(INDEX, " 1281839 ") != []  # нормализация пробелов


def test_format_positions_found():
    out = L.format_positions(INDEX, "1281839")
    assert "44.03.01 История" in out
    assert "290" in out and "1" in out
    assert "2026-07-01" in out  # время обновления
    assert "epk25.mpgu.su" in out  # ссылка на официальный список


def test_format_positions_not_found():
    out = L.format_positions(INDEX, "9999")
    assert "не найден" in out.lower()
    assert "epk25.mpgu.su" in out or "mpgu.su" in out
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest scraper/tests/test_abitur_lists.py -v`
Expected: FAIL — нет модуля.

- [ ] **Step 3: Реализовать `scraper/abitur/lists.py`**

```python
"""Чтение индекса конкурсных списков (с jsDelivr) и форматирование ответа."""
import json
import os
import time
import urllib.request
from typing import Dict, List, Optional

DATA_BASE = os.environ.get(
    "DATA_BASE", "https://cdn.jsdelivr.net/gh/mvbulgakova/mpgu-schedule@data")
_INDEX_PATH = "admissions/lists_index.json"
_CACHE = {"ts": 0.0, "data": None}
_TTL = 300  # секунд

_OFFICIAL = "https://epk25.mpgu.su/competitive-list"


def _norm(code: str) -> str:
    return "".join(ch for ch in (code or "") if ch.isdigit())


def fetch_index(force: bool = False) -> Optional[dict]:
    now = time.time()
    if not force and _CACHE["data"] is not None and now - _CACHE["ts"] < _TTL:
        return _CACHE["data"]
    try:
        req = urllib.request.Request(f"{DATA_BASE}/{_INDEX_PATH}",
                                     headers={"User-Agent": "MPGU-Abitur-Bot"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        _CACHE["data"], _CACHE["ts"] = data, now
        return data
    except Exception:
        return _CACHE["data"]


def lookup(index: dict, code: str) -> List[Dict]:
    return (index.get("codes") or {}).get(_norm(code), [])


def format_positions(index: dict, code: str) -> str:
    entries = lookup(index, code)
    updated = (index or {}).get("updated_at", "")
    lists = (index or {}).get("lists") or {}
    if not entries:
        return (f"Уникальный код <b>{_norm(code)}</b> не найден в индексе.\n"
                f"Проверьте номер или посмотрите официальные списки: {_OFFICIAL}\n"
                f"Данные обновляются периодически — возможна задержка.")
    lines = [f"🔎 <b>Ваши позиции по коду {_norm(code)}:</b>", ""]
    for e in entries:
        meta = lists.get(e["list"], {})
        name = meta.get("direction") or e["list"]
        flags = []
        if e.get("consent"):
            flags.append("согласие ✅")
        if e.get("bvi"):
            flags.append("БВИ")
        pri = f", приоритет {e['priority_pz']}" if e.get("priority_pz") is not None else ""
        tail = (" · " + ", ".join(flags)) if flags else ""
        lines.append(f"• <b>{name}</b>\n   место {e['position']}, "
                     f"баллы {e.get('score_total')}{pri} — {e.get('status') or '—'}{tail}")
    if updated:
        lines.append("")
        lines.append(f"Обновлено: {updated}")
    lines.append(f"Официальные списки: {_OFFICIAL}")
    lines.append("⚠️ Данные предварительные — ориентируйтесь на официальные списки и ЛК на Госуслугах.")
    return "\n".join(lines)
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python -m pytest scraper/tests/test_abitur_lists.py -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Коммит**

```bash
git add scraper/abitur/lists.py scraper/tests/test_abitur_lists.py
git commit -m "feat(lists): read index from jsDelivr, lookup and format positions"
```

---

## Task 5: Интеграция `/spisok` в бот

**Files:**
- Modify: `scraper/telegram_bot.py`
- Test: `scraper/tests/test_abitur_bot_lists.py`

- [ ] **Step 1: Написать падающие тесты роутинга `/spisok`**

Файл `scraper/tests/test_abitur_bot_lists.py`:

```python
"""Тесты потока проверки списков в боте (без сети).

Запуск: python -m pytest scraper/tests/test_abitur_bot_lists.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scraper.telegram_bot as bot


def setup_function(_):
    bot.SESSIONS.clear()
    bot.AWAITING_CODE.clear()


def test_spisok_command_asks_for_code(monkeypatch):
    out = bot.handle_message(chat_id=1, text="/spisok")
    assert bot.AWAITING_CODE.get(1) is True
    assert "код" in out.text.lower()


def test_code_after_spisok_is_looked_up(monkeypatch):
    monkeypatch.setattr(bot, "_lookup_code", lambda code: f"POSITIONS for {code}")
    bot.handle_message(chat_id=2, text="/spisok")
    out = bot.handle_message(chat_id=2, text="1281839")
    assert "POSITIONS for 1281839" in out.text
    assert 2 not in bot.AWAITING_CODE  # флаг снят


def test_spisok_with_inline_code(monkeypatch):
    monkeypatch.setattr(bot, "_lookup_code", lambda code: f"POS:{code}")
    out = bot.handle_message(chat_id=3, text="/spisok 999")
    assert "POS:999" in out.text


def test_volunteer_hours_take_priority_over_list_code(monkeypatch):
    # активна сессия калькулятора на шаге achieve → число = часы, не код списка
    monkeypatch.setattr(bot, "_lookup_code", lambda code: "SHOULD_NOT_APPEAR")
    bot.handle_message(chat_id=4, text="/bally")
    bot.handle_callback(chat_id=4, data="c:level:base")
    bot.handle_callback(chat_id=4, data="c:pedagogical:1")
    bot.handle_callback(chat_id=4, data="c:target:0")
    bot.AWAITING_CODE[4] = True  # даже если флаг стоит — калькулятор важнее
    out = bot.handle_message(chat_id=4, text="200")
    assert bot.SESSIONS[4].volunteer_hours == 200
    assert "SHOULD_NOT_APPEAR" not in out.text
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest scraper/tests/test_abitur_bot_lists.py -v`
Expected: FAIL — нет `bot.AWAITING_CODE` / `_lookup_code` / роутинга `/spisok`.

- [ ] **Step 3: Внести правки в `scraper/telegram_bot.py`**

3a. Добавить импорт списков и состояние ожидания кода. Заменить строку импорта
`from scraper.abitur import dialog, faq, llm` на:

```python
from scraper.abitur import dialog, faq, llm, lists
```

и рядом с `SESSIONS` добавить:

```python
# Ожидание уникального кода после /spisok (отдельно от калькулятора).
AWAITING_CODE: Dict[int, bool] = {}
```

3b. Добавить хелпер поиска (рядом с `_answer_free`):

```python
def _lookup_code(code: str) -> str:
    index = lists.fetch_index()
    if not index:
        return ("Индекс списков сейчас недоступен. Официальные списки: "
                "https://epk25.mpgu.su/competitive-list")
    return lists.format_positions(index, code)
```

3c. В `handle_message` перед разбором `intent` — после блока ввода часов волонтёрства —
добавить обработку ожидаемого кода и учесть приоритет калькулятора. Итоговое начало
`handle_message` (заменить текущий блок волонтёрских часов и добавить блок кода):

```python
def handle_message(chat_id: int, text: str) -> Reply:
    text = (text or "")[:MAX_MSG_LEN].strip()
    # 1) ввод часов волонтёрства во время калькулятора — высший приоритет для числа
    sess = SESSIONS.get(chat_id)
    if sess is not None and sess.step == dialog.STEP_ACHIEVE and text.isdigit():
        dialog.set_volunteer_hours(sess, int(text))
        v = dialog.render(sess)
        return Reply(f"Часы волонтёрства: {sess.volunteer_hours}.\n\n{v.text}", v.keyboard)

    # 2) ожидаем уникальный код после /spisok
    if AWAITING_CODE.get(chat_id) and any(ch.isdigit() for ch in text) and not text.startswith("/"):
        AWAITING_CODE.pop(chat_id, None)
        return Reply(_lookup_code(text), [])

    intent, payload = faq.route(text)
    if intent == "start" or intent == "help":
        return Reply(_GREETING, _menu_keyboard())
    if intent == "menu":
        return Reply("Выберите тему:", _menu_keyboard())
    if intent == "calc":
        s = dialog.start()
        SESSIONS[chat_id] = s
        v = dialog.render(s)
        return Reply(v.text, v.keyboard)
    if intent == "spisok":
        if payload:  # /spisok 12345
            return Reply(_lookup_code(payload), [])
        AWAITING_CODE[chat_id] = True
        return Reply("Пришлите ваш <b>уникальный код</b> (номер заявления) одним сообщением.", [])
    # свободный вопрос
    return Reply(_answer_free(payload), [])
```

3d. В `scraper/abitur/faq.py` в функции `route` добавить распознавание `/spisok` и вернуть
код как payload. Заменить блок `if cmd in ("/bally", ...)` окружением, добавив перед `return
("free", t)`:

```python
    if cmd in ("/spisok", "/list", "/spiski"):
        arg = t[len(t.split()[0]):].strip() if t else ""
        return ("spisok", arg)
```

3e. Добавить пункт меню. В `_menu_keyboard` заменить последнюю строку
`rows.append([("➕ Калькулятор баллов", "open:calc")])` на:

```python
    rows.append([("➕ Калькулятор баллов", "open:calc")])
    rows.append([("🔎 Мои списки", "open:spisok")])
    return rows
```

3f. В `handle_callback` добавить ветку для `open:spisok` (рядом с `open:calc`):

```python
    if data == "open:spisok":
        AWAITING_CODE[chat_id] = True
        return Reply("Пришлите ваш <b>уникальный код</b> (номер заявления) одним сообщением.", [])
```

- [ ] **Step 4: Запустить тесты списков в боте + существующие бот-тесты**

Run: `python -m pytest scraper/tests/test_abitur_bot_lists.py scraper/tests/test_abitur_bot.py -v`
Expected: PASS (новые + прежние 6).

- [ ] **Step 5: Коммит**

```bash
git add scraper/telegram_bot.py scraper/abitur/faq.py scraper/tests/test_abitur_bot_lists.py
git commit -m "feat(lists): /spisok flow in bot with unique-code lookup"
```

---

## Task 6: Workflow периодического скрейпа

**Files:**
- Create: `.github/workflows/fetch-lists.yml`

- [ ] **Step 1: Создать `.github/workflows/fetch-lists.yml`**

```yaml
name: Fetch Competitive Lists

# Периодический скрейп конкурсных списков epk25 → индекс в data-ветке.
# Актуально в сроки приёмной кампании.

on:
  workflow_dispatch:
  schedule:
    - cron: "0 */3 * * *"   # каждые 3 часа

concurrency:
  group: fetch-lists
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  fetch:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main

      - name: Checkout data branch
        uses: actions/checkout@v4
        with:
          ref: data
          path: data

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install deps
        run: pip install requests beautifulsoup4 lxml

      - name: Build lists index
        env:
          DATA_PATH: data
        run: python -m scraper.build_lists_index
```

- [ ] **Step 2: Проверить синтаксис workflow (локально) и полный прогон тестов**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/fetch-lists.yml')); print('yaml ok')"`
Expected: `yaml ok`.

Run: `python -m pytest scraper/tests/ -q`
Expected: PASS — все тесты (A + B) зелёные, существующие не сломаны.

- [ ] **Step 3: Коммит**

```bash
git add .github/workflows/fetch-lists.yml
git commit -m "chore(lists): periodic workflow to scrape competitive lists"
```

---

## Self-Review (выполнено автором плана)

**Покрытие спека:**
- Разведка/навигация epk25 (structural→direction→view) — Task 2; парсер `view` — Task 1.
- Индекс `{код → позиции}` + хранение в data-ветке — Task 3; чтение с jsDelivr + формат — Task 4.
- Бот `/spisok` + `AWAITING_CODE` + приоритет «часы vs код» — Task 5.
- Периодический workflow — Task 6.
- Приватность/дисклеймер (только уникальный код, ссылка на официал, updated_at) — Task 4 (`format_positions`).

**Плейсхолдеры:** не найдено — в каждом шаге реальный код/команды. Ограничение: `main()` в
Task 3 собирает `meta` минимально (url); обогащение контекстом направления помечено как
расширение и не влияет на MVP (поиск по коду работает).

**Согласованность типов/имён:** `parse_view` (Task 1) → `build_index` (Task 3) → `lookup`/
`format_positions` (Task 4) → `_lookup_code`/`AWAITING_CODE`/intent `spisok` (Task 5) —
имена и формы данных согласованы; ключи индекса (`updated_at`,`lists`,`codes`,`list`,
`position`,`score_total`,`consent`,`priority_pz`,`bvi`,`status`) едины во всех задачах;
callback `open:spisok` и команда `/spisok` согласованы между `faq.route`, `telegram_bot` и
тестами. Конфликт ввода числа разрешён порядком проверок в `handle_message` (калькулятор
раньше кода).
