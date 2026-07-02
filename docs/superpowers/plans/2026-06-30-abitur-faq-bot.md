# Abitur FAQ Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Превратить Telegram-бот МПГУ в помощника абитуриента: FAQ по приёмной кампании (AI на Haiku 4.5, заземлённый на курируемую базу знаний) + детерминированный калькулятор дополнительных баллов за индивидуальные достижения.

**Architecture:** Новый пакет `scraper/abitur/` с чистыми, изолированно тестируемыми модулями: данные правил (`achievements.py`), чистый расчёт (`calculator.py`), база знаний (`knowledge.md`), FAQ-маршрутизация (`faq.py`), AI-ответ (`llm.py`, переиспользует существующий `claude_client`), диалог калькулятора (`dialog.py`). `telegram_bot.py` переписывается как тонкий слой long-polling, убирающий логику расписания и вызывающий чистые функции. Калькулятор полностью детерминирован — LLM к арифметике не допущен.

**Tech Stack:** Python 3.12, stdlib (`urllib`, `json`, `dataclasses`), `anthropic` SDK (уже в `requirements.txt`), pytest. Деплой — существующий воркфлоу `bot-poll.yml` (GitHub Actions long-polling).

---

## File Structure

- Create `scraper/abitur/__init__.py` — пакет.
- Create `scraper/abitur/achievements.py` — машиночитаемые правила баллов (раздел 9 + Приложение 7).
- Create `scraper/abitur/calculator.py` — чистая логика расчёта (суммы, «один вид спорта», потолки).
- Create `scraper/abitur/knowledge.md` — база знаний для FAQ (человекочитаемая, заземление LLM).
- Create `scraper/abitur/faq.py` — детерминированные FAQ-темы и маршрутизация текста.
- Create `scraper/abitur/llm.py` — AI-ответ на свободный вопрос (Haiku 4.5, заземление на KB).
- Create `scraper/abitur/dialog.py` — конечный автомат диалога калькулятора + inline-клавиатуры.
- Rewrite `scraper/telegram_bot.py` — тонкий long-polling, абитур-онли (расписание убрано).
- Modify `.github/workflows/bot-poll.yml` — проброс `ANTHROPIC_API_KEY`.
- Tests: `scraper/tests/test_abitur_calculator.py`, `test_abitur_faq.py`, `test_abitur_llm.py`, `test_abitur_dialog.py`, `test_abitur_bot.py`.

**Не трогаем:** `scraper/parsers/*`, data-ветку, `app/` — логика расписания остаётся в репозитории, просто не подключена к боту.

---

## Task 1: Пакет и данные правил баллов

**Files:**
- Create: `scraper/abitur/__init__.py`
- Create: `scraper/abitur/achievements.py`
- Test: `scraper/tests/test_abitur_calculator.py`

- [ ] **Step 1: Создать пустой пакет**

```bash
mkdir -p scraper/abitur
printf '"""Помощник абитуриента МПГУ: FAQ и калькулятор доп. баллов."""\n' > scraper/abitur/__init__.py
```

- [ ] **Step 2: Написать падающий тест на данные правил**

Файл `scraper/tests/test_abitur_calculator.py`:

```python
"""Тесты данных правил и калькулятора доп. баллов.

Запуск: python -m pytest scraper/tests/test_abitur_calculator.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import achievements as A


def test_sport_points_table():
    assert A.SPORT["gto_gold"][1] == 5
    assert A.SPORT["gto_silver_bronze"][1] == 4
    assert A.SPORT["master"][1] == 8
    assert A.SPORT["kms"][1] == 6
    assert A.SPORT["champion_olympic"][1] == 10


def test_volunteer_points_base_non_pedagogical():
    f = A.volunteer_points
    assert f("base", False, 50) == 0
    assert f("base", False, 100) == 2
    assert f("base", False, 250) == 3
    assert f("base", False, 300) == 4


def test_volunteer_points_base_pedagogical_is_higher():
    f = A.volunteer_points
    # для пед-направления берётся максимум из общих и пед. ступеней
    assert f("base", True, 100) == 6
    assert f("base", True, 200) == 8
    assert f("base", True, 300) == 10
    assert f("base", True, 90) == 0


def test_volunteer_points_spec():
    f = A.volunteer_points
    assert f("spec", False, 200) == 0
    assert f("spec", False, 300) == 4
    assert f("spec", False, 400) == 5
    assert f("spec", False, 500) == 6
    assert f("spec", True, 100) == 8
    assert f("spec", True, 300) == 10
```

- [ ] **Step 3: Запустить тест — убедиться, что падает**

Run: `python -m pytest scraper/tests/test_abitur_calculator.py -v`
Expected: FAIL — `ModuleNotFoundError: scraper.abitur.achievements`.

- [ ] **Step 4: Реализовать `scraper/abitur/achievements.py`**

```python
"""Машиночитаемые правила начисления доп. баллов за индивидуальные достижения.

Источник: Правила приёма МПГУ 2026/27 (раздел 9) и Приложение 7.
Актуальность: 2026-06-30. При смене кампании — обновить значения здесь.

Уровни: "base" — БВО/бакалавриат/специалитет; "spec" — СПВО/магистратура.
"""
from typing import Optional

LEVELS = ("base", "spec")

# Спортивные достижения. Берётся ОДИН вид (максимальный); знак ГТО — однократно.
# id -> (label, points). Действуют на обоих уровнях.
SPORT = {
    "champion_olympic": ("Чемпион/призёр ОИ/ПИ/СИ, ЧМ/ЧЕ (олимп. виды), чемпион/Кубок России", 10),
    "champion_world": ("Чемпион мира/Европы (неолимпийские виды)", 10),
    "master": ("Мастер спорта (МС)", 8),
    "kms": ("Кандидат в мастера спорта (КМС)", 6),
    "gto_gold": ("Золотой знак ГТО", 5),
    "gto_silver_bronze": ("Серебряный/бронзовый знак ГТО", 4),
}

# Волонтёрство: (level, pedagogical) -> [(min_hours, points), ...].
# Для пед-направления берётся максимум из общих и психолого-педагогических ступеней.
_VOLUNTEER_GENERAL = {
    "base": [(100, 2), (200, 3), (300, 4)],
    "spec": [(300, 4), (400, 5), (500, 6)],
}
_VOLUNTEER_PEDAGOGICAL = {
    "base": [(100, 6), (200, 8), (300, 10)],
    "spec": [(100, 8), (200, 9), (300, 10)],
}


def volunteer_points(level: str, pedagogical: bool, hours: int) -> int:
    """Баллы за волонтёрство: одна максимальная подходящая ступень."""
    tiers = list(_VOLUNTEER_GENERAL.get(level, []))
    if pedagogical:
        tiers += _VOLUNTEER_PEDAGOGICAL.get(level, [])
    eligible = [pts for (mn, pts) in tiers if hours >= mn]
    return max(eligible) if eligible else 0


# Простые достижения по 10 баллов (оба уровня), boolean.
FLAT_10 = {
    "edu_honors": "Аттестат/диплom с отличием или медаль",
    "abilimpiks": "Победитель/призёр «Абилимпикс»",
    "svo": "Военная служба/добровольч. формирования в зоне СВО",
    "do_profile": "Доп. образование в области искусств/спорта (по профилю)",
}

# Олимпиады/перечневые конкурсы: победитель 10 / призёр 5.
OLYMPIAD = {"winner": ("Победитель олимпиады/перечневого конкурса", 10),
            "prizer": ("Призёр олимпиады/перечневого конкурса", 5)}

# Только для уровня "spec" (СПВО/магистратура).
PUBLICATIONS = {"multi": ("Две и более научных публикаций", 10),
                "one": ("Одна научная публикация", 5)}
FIEB = {"gold": ("Золотой сертификат ФИЭБ 2026", 10),
        "silver": ("Серебряный сертификат ФИЭБ 2026", 5)}
PREMIA = {"federal": ("Лауреат премии (наука/образование) фед. уровня", 10),
          "regional": ("Лауреат премии (наука/образование) рег. уровня", 5)}
PATENTS_LABEL = "Патент на изобретение"
PATENTS_POINTS = 10

GENERAL_CAP = 10   # потолок общих ИД суммарно (раздел 9.4)
TARGET_CAP = 5     # доп. потолок целевых ИД на целевой квоте
```

- [ ] **Step 5: Запустить тест — убедиться, что проходит**

Run: `python -m pytest scraper/tests/test_abitur_calculator.py -v`
Expected: PASS (все 4 теста этого файла).

- [ ] **Step 6: Коммит**

```bash
git add scraper/abitur/__init__.py scraper/abitur/achievements.py scraper/tests/test_abitur_calculator.py
git commit -m "feat(abitur): rules data for admission points (section 9 + appendix 7)"
```

---

## Task 2: Чистая логика калькулятора

**Files:**
- Create: `scraper/abitur/calculator.py`
- Test: `scraper/tests/test_abitur_calculator.py` (дополнить)

- [ ] **Step 1: Дописать падающие тесты калькулятора**

Добавить в конец `scraper/tests/test_abitur_calculator.py`:

```python
from scraper.abitur.calculator import CalcInput, calculate


def _base(**kw):
    defaults = dict(level="base", pedagogical=False, target_quota=False,
                    sport=None, edu_honors=False, abilimpiks=False, svo=False,
                    do_profile=False, olympiad=None, volunteer_hours=0,
                    publications=None, patents=False, fieb=None, premia=None,
                    target_points=0)
    defaults.update(kw)
    return CalcInput(**defaults)


def test_calculate_sport_takes_single_max():
    # выбран КМС (6) — спорт даёт только один вид
    r = calculate(_base(sport="kms"))
    assert r.general_raw == 6
    assert r.total == 6
    assert r.capped is False


def test_calculate_caps_general_at_10():
    # медаль(10) + золото ГТО(5) + волонтёрство 300ч(4) = 19 → потолок 10
    r = calculate(_base(edu_honors=True, sport="gto_gold", volunteer_hours=300))
    assert r.general_raw == 19
    assert r.general_capped == 10
    assert r.total == 10
    assert r.capped is True


def test_calculate_pedagogical_volunteering():
    r = calculate(_base(pedagogical=True, volunteer_hours=200))
    assert r.general_raw == 8
    assert r.total == 8


def test_calculate_target_quota_adds_up_to_5():
    # общие: медаль 10 (потолок 10) + целевые 5 → 15
    r = calculate(_base(edu_honors=True, target_quota=True, target_points=7))
    assert r.general_capped == 10
    assert r.target_capped == 5
    assert r.total == 15


def test_calculate_target_points_ignored_without_quota():
    r = calculate(_base(edu_honors=True, target_quota=False, target_points=5))
    assert r.target_capped == 0
    assert r.total == 10


def test_calculate_spec_publications_and_patents():
    r = calculate(_base(level="spec", publications="multi", patents=True))
    assert r.general_raw == 20
    assert r.general_capped == 10


def test_calculate_breakdown_lists_contributors():
    r = calculate(_base(sport="kms", olympiad="prizer"))
    labels = [lbl for (lbl, _) in r.breakdown]
    assert any("КМС" in l for l in labels)
    assert any("Призёр" in l for l in labels)
    assert r.general_raw == 11
    assert r.general_capped == 10
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest scraper/tests/test_abitur_calculator.py -v`
Expected: FAIL — `ModuleNotFoundError: scraper.abitur.calculator`.

- [ ] **Step 3: Реализовать `scraper/abitur/calculator.py`**

```python
"""Чистый детерминированный расчёт доп. баллов. LLM здесь не участвует."""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from scraper.abitur import achievements as A


@dataclass
class CalcInput:
    level: str                       # "base" | "spec"
    pedagogical: bool                # направление 44.xx
    target_quota: bool               # поступление на целевую квоту
    sport: Optional[str]             # ключ A.SPORT или None (один вид)
    edu_honors: bool
    abilimpiks: bool
    svo: bool
    do_profile: bool
    olympiad: Optional[str]          # "winner" | "prizer" | None
    volunteer_hours: int             # 0 = нет
    publications: Optional[str]      # spec: "one" | "multi" | None
    patents: bool                    # spec
    fieb: Optional[str]              # spec: "gold" | "silver" | None
    premia: Optional[str]            # spec: "federal" | "regional" | None
    target_points: int = 0           # целевые ИД (профориентация), сырые


@dataclass
class CalcResult:
    breakdown: List[Tuple[str, int]] = field(default_factory=list)
    general_raw: int = 0
    general_capped: int = 0
    target_capped: int = 0
    total: int = 0
    capped: bool = False


def calculate(inp: CalcInput) -> CalcResult:
    items: List[Tuple[str, int]] = []

    if inp.sport and inp.sport in A.SPORT:
        label, pts = A.SPORT[inp.sport]
        items.append((label, pts))

    if inp.edu_honors:
        items.append((A.FLAT_10["edu_honors"], 10))
    if inp.abilimpiks:
        items.append((A.FLAT_10["abilimpiks"], 10))
    if inp.svo:
        items.append((A.FLAT_10["svo"], 10))
    if inp.do_profile:
        items.append((A.FLAT_10["do_profile"], 10))

    if inp.olympiad in A.OLYMPIAD:
        label, pts = A.OLYMPIAD[inp.olympiad]
        items.append((label, pts))

    vp = A.volunteer_points(inp.level, inp.pedagogical, inp.volunteer_hours)
    if vp:
        items.append((f"Волонтёрство ({inp.volunteer_hours} ч)", vp))

    if inp.level == "spec":
        if inp.publications in A.PUBLICATIONS:
            label, pts = A.PUBLICATIONS[inp.publications]
            items.append((label, pts))
        if inp.patents:
            items.append((A.PATENTS_LABEL, A.PATENTS_POINTS))
        if inp.fieb in A.FIEB:
            label, pts = A.FIEB[inp.fieb]
            items.append((label, pts))
        if inp.premia in A.PREMIA:
            label, pts = A.PREMIA[inp.premia]
            items.append((label, pts))

    general_raw = sum(p for _, p in items)
    general_capped = min(general_raw, A.GENERAL_CAP)
    target_capped = min(inp.target_points, A.TARGET_CAP) if inp.target_quota else 0

    return CalcResult(
        breakdown=items,
        general_raw=general_raw,
        general_capped=general_capped,
        target_capped=target_capped,
        total=general_capped + target_capped,
        capped=general_raw > A.GENERAL_CAP,
    )
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python -m pytest scraper/tests/test_abitur_calculator.py -v`
Expected: PASS (все тесты файла).

- [ ] **Step 5: Коммит**

```bash
git add scraper/abitur/calculator.py scraper/tests/test_abitur_calculator.py
git commit -m "feat(abitur): deterministic points calculator with caps"
```

---

## Task 3: База знаний (knowledge.md)

**Files:**
- Create: `scraper/abitur/knowledge.md`
- Test: `scraper/tests/test_abitur_faq.py` (smoke-проверка наличия якорей)

- [ ] **Step 1: Написать падающий smoke-тест KB**

Файл `scraper/tests/test_abitur_faq.py`:

```python
"""Тесты базы знаний и FAQ-маршрутизации.

Запуск: python -m pytest scraper/tests/test_abitur_faq.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import faq


def test_knowledge_base_has_key_anchors():
    kb = faq.load_knowledge()
    for anchor in ["приёмн", "ЕГЭ", "ДВИ", "общежит", "priem@mpgu.su",
                   "базовое высшее", "индивидуальн"]:
        assert anchor.lower() in kb.lower(), anchor
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest scraper/tests/test_abitur_faq.py -v`
Expected: FAIL — `ModuleNotFoundError: scraper.abitur.faq`.

- [ ] **Step 3: Создать `scraper/abitur/knowledge.md`**

```markdown
# База знаний абитуриента МПГУ — приёмная кампания 2026/27
АКТУАЛЬНОСТЬ: 2026-06-30. Источник — официальные Правила приёма МПГУ и сайт mpgu.su.

## Уровни образования (федеральный пилот)
МПГУ — участник пилота новой системы. Базовое высшее образование (БВО) — основной уровень,
4–6 лет, заменяет бакалавриат/специалитет. Специализированное высшее (СПВО) и магистратура —
углублённая подготовка, 1–3 года. Бакалавриат/специалитет/магистратура существуют параллельно
в переходный период.

## Вступительные испытания (ВИ) и ЕГЭ
Поступающие на обычный бакалавриат/БВО — по результатам ЕГЭ. Внутренние ВИ вместо ЕГЭ вправе
сдавать: выпускники колледжей/СПО, лица с инвалидностью, иностранные граждане, лица с имеющимся
высшим образованием. Формат — письменно, в т.ч. с дистанционными технологиями.

## Дополнительные вступительные испытания (ДВИ)
ДВИ творческой/профессиональной направленности требуются на творческие направления:
журналистика, физическая культура, музыка, изобразительное искусство, дизайн. На обычный
бакалавриат ДВИ не нужны. Все ВИ/ДВИ на 1 курс БВО завершаются не позднее 25 июля.
Перечень ВИ и минимальные баллы по направлениям: https://mpgu.su/postuplenie/ (раздел
«Нормативно-правовое обеспечение приёма», перечень ВИ).

## Сроки (2026)
Приём документов (очно): 9 календарных дней после объявления результатов ЕГЭ. Заочно: до
4 сентября. Зачисление по квотам и БВИ — 30 июля; основной этап (общие основания) — 8 августа.
Медсправка 086/у (для педагогических, шифр 44.xx) — до 25 июля. Договор и оплата на платном —
до 27 августа включительно.

## Особые права и квоты
БВИ (без вступительных испытаний) — победителям и призёрам олимпиад. Квоты: особая, целевая,
отдельная (в т.ч. для участников СВО и их детей); есть преимущественное право зачисления.
Подробности — Приложение 6 к Правилам приёма и https://mpgu.su/postuplenie/.

## Целевое обучение
Заявка через платформу «Работа России»/Госуслуги. Выделяется целевая квота (например, не менее
20% мест на «Прикладной информатике»). На целевой квоте действует повышенный потолок доп. баллов
(общие до 10 + целевые до 5).

## Индивидуальные достижения (доп. баллы)
Учитываются при поступлении, включаются в сумму конкурсных баллов. Потолок — не более 10 баллов
суммарно за общие ИД; на целевой квоте — до 15 (общие 10 + целевые 5). Баллы за один вид
спортивных достижений (максимальный), знак ГТО — однократно. Волонтёрство зависит от уровня и
направления (для психолого-педагогических направлений 44.xx баллы выше). Точный расчёт — командой
/bally. Полный перечень — Приложение 7: https://mpgu.su/wp-content/uploads/2026/03/pk26_prilojenie-7-inye-meropriyatia.pdf

## Документы и подача
Онлайн: https://mpgu.su/podat-dokumenty-onlajn/ ; через Госуслуги; лично. Перечень документов —
на странице поступления.

## Расписание и программы ВИ
Расписание: https://mpgu.su/raspisanie-vstupitelnyih-ispyitaniy/
Программы: https://mpgu.su/postuplenie/entrance-test-programs/

## Общежитие, курсы, дни открытых дверей
Общежитие — иногородним при регистрации свыше 70 км от МКАД. Подготовительные курсы и дни
открытых дверей — на сайте mpgu.su/postuplenie/.

## Стоимость и договор
Платное обучение — по договору; оплата до 27 августа. Договорный приём: dg@mpgu.su,
+7 (495) 438-18-57.

## Проходной балл
Проходной балл — это балл последнего абитуриента, зачисленного на бюджет. Становится известен
ТОЛЬКО после завершения зачисления. Точных цифр заранее не существует.

## Контакты приёмной комиссии
Email: priem@mpgu.su. Телефоны: +7 (499) 702-41-41, +7 (495) 438-18-47. Адрес: пр-т Вернадского,
д. 88, каб. 550. Режим: Пн–Чт 10:00–17:00, Пт 10:00–16:00, Сб 10:00–14:00.
Официальный FAQ: https://mpgu.su/voprosy-otvety-dlja-abiturientov/
```

- [ ] **Step 4: Тест из Task 4 покроет загрузку — пока проверить наличие файла**

Run: `test -f scraper/abitur/knowledge.md && echo OK`
Expected: `OK`. (Сам smoke-тест запустится после Task 4, когда появится `faq.load_knowledge`.)

- [ ] **Step 5: Коммит**

```bash
git add scraper/abitur/knowledge.md scraper/tests/test_abitur_faq.py
git commit -m "feat(abitur): admissions knowledge base for FAQ grounding"
```

---

## Task 4: FAQ-темы и маршрутизация

**Files:**
- Create: `scraper/abitur/faq.py`
- Test: `scraper/tests/test_abitur_faq.py` (дополнить)

- [ ] **Step 1: Дописать падающие тесты маршрутизации**

Добавить в конец `scraper/tests/test_abitur_faq.py`:

```python
def test_route_commands():
    assert faq.route("/start")[0] == "start"
    assert faq.route("/help")[0] == "help"
    assert faq.route("/abitur")[0] == "menu"
    assert faq.route("/bally")[0] == "calc"
    assert faq.route("/bally@MpguBot")[0] == "calc"


def test_route_free_question():
    intent, _ = faq.route("нужна ли справка 086у?")
    assert intent == "free"


def test_topics_have_labels_and_answers():
    assert faq.TOPICS, "темы не заданы"
    for tid, (label, answer) in faq.TOPICS.items():
        assert label and answer
        assert "http" in answer or "mpgu" in answer.lower()


def test_topic_answer_known_and_unknown():
    sroki = faq.topic_answer("sroki")
    assert "25 июля" in sroki or "августа" in sroki
    assert faq.topic_answer("does-not-exist") is None
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest scraper/tests/test_abitur_faq.py -v`
Expected: FAIL — нет `faq.route`/`faq.TOPICS`/`faq.topic_answer`.

- [ ] **Step 3: Реализовать `scraper/abitur/faq.py`**

```python
"""FAQ: загрузка базы знаний, детерминированные темы-кнопки, маршрутизация текста."""
from pathlib import Path
from typing import Dict, Optional, Tuple

_KB_PATH = Path(__file__).with_name("knowledge.md")

# id -> (label кнопки, готовый ответ). Ответы детерминированы, без LLM.
TOPICS: Dict[str, Tuple[str, str]] = {
    "sroki": ("📅 Сроки", (
        "<b>Сроки приёма 2026:</b>\n"
        "• Документы (очно): 9 дней после объявления результатов ЕГЭ\n"
        "• Заочно: до 4 сентября\n"
        "• Зачисление по квотам/БВИ — 30 июля; основной этап — 8 августа\n"
        "• Справка 086/у (педагогические 44.xx) — до 25 июля\n"
        "• Договор и оплата на платном — до 27 августа\n\n"
        "Подробнее: https://mpgu.su/postuplenie/")),
    "documents": ("📄 Документы", (
        "<b>Подача документов:</b> онлайн https://mpgu.su/podat-dokumenty-onlajn/, "
        "через Госуслуги или лично. Перечень документов — на странице поступления "
        "https://mpgu.su/postuplenie/")),
    "vi": ("📝 ВИ и ДВИ", (
        "<b>Вступительные испытания:</b> обычный бакалавриат/БВО — по ЕГЭ. "
        "Внутренние ВИ вместо ЕГЭ — выпускникам колледжей/СПО, лицам с инвалидностью, "
        "иностранцам, лицам с ВО.\n"
        "<b>ДВИ</b> (творческие/проф.) — журналистика, физкультура, музыка, ИЗО, дизайн.\n"
        "Расписание: https://mpgu.su/raspisanie-vstupitelnyih-ispyitaniy/\n"
        "Программы: https://mpgu.su/postuplenie/entrance-test-programs/")),
    "levels": ("🎓 БВО / СПВО", (
        "<b>Уровни (пилот):</b> Базовое высшее образование (БВО) — основной уровень, "
        "4–6 лет, вместо бакалавриата/специалитета. Специализированное высшее (СПВО) и "
        "магистратура — углублённая подготовка, 1–3 года.\n"
        "Подробнее: https://mpgu.su/postuplenie/pilot/")),
    "bally": ("➕ Доп. баллы", (
        "<b>Индивидуальные достижения</b> дают до 10 баллов суммарно (на целевой квоте — до 15). "
        "Считаются один вид спорта (максимум), ГТО однократно; волонтёрство зависит от уровня и "
        "направления.\n"
        "Точный расчёт — команда /bally\n"
        "Перечень: https://mpgu.su/wp-content/uploads/2026/03/pk26_prilojenie-7-inye-meropriyatia.pdf")),
    "obshchezhitie": ("🏠 Общежитие", (
        "<b>Общежитие</b> предоставляется иногородним при регистрации свыше 70 км от МКАД. "
        "Подробности — https://mpgu.su/postuplenie/")),
    "celevoe": ("🎯 Целевое", (
        "<b>Целевое обучение:</b> заявка через «Работа России»/Госуслуги. Есть целевая квота; "
        "на ней повышенный потолок доп. баллов (до 15).\n"
        "Подробнее: https://mpgu.su/postuplenie/")),
    "lgoty": ("⭐ Льготы и квоты", (
        "<b>Особые права:</b> БВИ — победителям/призёрам олимпиад; квоты особая/целевая/отдельная "
        "(в т.ч. для участников СВО и их детей); преимущественное право.\n"
        "Подробнее: https://mpgu.su/postuplenie/")),
    "contacts": ("☎️ Контакты", (
        "<b>Приёмная комиссия МПГУ:</b>\n"
        "Email: priem@mpgu.su\n"
        "Тел.: +7 (499) 702-41-41, +7 (495) 438-18-47\n"
        "Адрес: пр-т Вернадского, 88, каб. 550\n"
        "Режим: Пн–Чт 10–17, Пт 10–16, Сб 10–14\n"
        "Договорный приём: dg@mpgu.su, +7 (495) 438-18-57")),
}


def load_knowledge() -> str:
    return _KB_PATH.read_text(encoding="utf-8")


def topic_answer(topic_id: str) -> Optional[str]:
    item = TOPICS.get(topic_id)
    return item[1] if item else None


def route(text: str) -> Tuple[str, str]:
    """Возвращает (intent, payload). intent: start|help|menu|calc|free."""
    t = (text or "").strip()
    cmd = t.split()[0].lower().split("@")[0] if t else ""
    if cmd in ("/start",):
        return ("start", "")
    if cmd in ("/help",):
        return ("help", "")
    if cmd in ("/abitur", "/menu", "/faq"):
        return ("menu", "")
    if cmd in ("/bally", "/ball", "/calc"):
        return ("calc", "")
    return ("free", t)
```

- [ ] **Step 4: Запустить весь файл — убедиться, что проходит (вкл. smoke из Task 3)**

Run: `python -m pytest scraper/tests/test_abitur_faq.py -v`
Expected: PASS (smoke KB + маршрутизация + темы).

- [ ] **Step 5: Коммит**

```bash
git add scraper/abitur/faq.py scraper/tests/test_abitur_faq.py
git commit -m "feat(abitur): FAQ topics and text routing"
```

---

## Task 5: AI-ответ на свободный вопрос (Haiku 4.5)

**Files:**
- Create: `scraper/abitur/llm.py`
- Test: `scraper/tests/test_abitur_llm.py`

- [ ] **Step 1: Написать падающие тесты с мок-клиентом**

Файл `scraper/tests/test_abitur_llm.py`:

```python
"""Тесты AI-ответа (заземление + обработка ошибок), без реального вызова API.

Запуск: python -m pytest scraper/tests/test_abitur_llm.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import llm


class _FakeBlock:
    type = "text"
    def __init__(self, text): self.text = text


class _FakeResp:
    def __init__(self, text): self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, captured): self._captured = captured
    def create(self, **kwargs):
        self._captured.update(kwargs)
        return _FakeResp("Справка 086/у нужна до 25 июля. https://mpgu.su/postuplenie/")


class _FakeClient:
    def __init__(self, captured): self.messages = _FakeMessages(captured)


def test_answer_grounds_on_kb_and_uses_haiku():
    captured = {}
    out = llm.answer("нужна ли справка?", client=_FakeClient(captured))
    assert "086" in out
    assert captured["model"] == "claude-haiku-4-5"
    # система содержит базу знаний и anti-hallucination инструкции
    system = captured["system"]
    sys_text = system if isinstance(system, str) else system[0]["text"]
    assert "priem@mpgu.su" in sys_text
    assert "не выдум" in sys_text.lower() or "только" in sys_text.lower()


def test_answer_sets_cache_control_on_system():
    captured = {}
    llm.answer("вопрос", client=_FakeClient(captured))
    system = captured["system"]
    assert isinstance(system, list)
    assert system[-1].get("cache_control", {}).get("type") == "ephemeral"


def test_answer_error_falls_back_to_contacts():
    class _Boom:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("api down")
    out = llm.answer("вопрос", client=_Boom())
    assert "priem@mpgu.su" in out


def test_answer_without_client_factory_failure_is_graceful(monkeypatch):
    # эмулируем отсутствие кредов: фабрика клиента бросает
    def _raise():
        raise ValueError("нет ключа")
    out = llm.answer("вопрос", client=None, client_factory=_raise)
    assert "priem@mpgu.su" in out
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest scraper/tests/test_abitur_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: scraper.abitur.llm`.

- [ ] **Step 3: Реализовать `scraper/abitur/llm.py`**

```python
"""AI-ответ на свободный вопрос абитуриента. Заземление на базу знаний, Haiku 4.5.

Переиспользует авторизацию из scraper.utils.claude_client (ANTHROPIC_API_KEY или
session-токен Claude Code remote). Цифры расчёта баллов сюда не попадают — для них /bally.
"""
from typing import Callable, Optional

from scraper.abitur import faq

MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 512

_FALLBACK = ("Не удалось ответить автоматически. Уточните в приёмной комиссии МПГУ: "
             "priem@mpgu.su, +7 (499) 702-41-41. Сайт: https://mpgu.su/postuplenie/")

_SYSTEM_HEADER = (
    "Ты — помощник абитуриента МПГУ. Отвечай ТОЛЬКО на основе базы знаний ниже. "
    "НЕ выдумывай даты, числа, проходные баллы, перечни документов. Если ответа нет в "
    "базе — честно скажи, что точно подскажет приёмная комиссия, и дай её контакты. "
    "Всегда добавляй официальную ссылку из базы. Отвечай кратко, по-русски, дружелюбно. "
    "Если вопрос про точный расчёт индивидуальных баллов — посоветуй команду /bally.\n\n"
    "=== БАЗА ЗНАНИЙ ===\n"
)


def _default_factory():
    from scraper.utils.claude_client import _get_anthropic_client
    return _get_anthropic_client()


def _build_system(kb_text: str):
    return [{"type": "text", "text": _SYSTEM_HEADER + kb_text,
             "cache_control": {"type": "ephemeral"}}]


def answer(question: str, *, client=None,
           client_factory: Optional[Callable] = None,
           kb_text: Optional[str] = None) -> str:
    """Возвращает текст ответа. При любой ошибке — фолбэк с контактами приёмки."""
    try:
        if client is None:
            factory = client_factory or _default_factory
            client = factory()
        system = _build_system(kb_text if kb_text is not None else faq.load_knowledge())
        resp = client.messages.create(
            model=MODEL,
            max_tokens=_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": question}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                return block.text.strip()
        return _FALLBACK
    except Exception:
        return _FALLBACK
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python -m pytest scraper/tests/test_abitur_llm.py -v`
Expected: PASS (4 теста).

- [ ] **Step 5: Коммит**

```bash
git add scraper/abitur/llm.py scraper/tests/test_abitur_llm.py
git commit -m "feat(abitur): grounded AI answer on Haiku 4.5 with graceful fallback"
```

---

## Task 6: Диалог калькулятора (конечный автомат)

**Files:**
- Create: `scraper/abitur/dialog.py`
- Test: `scraper/tests/test_abitur_dialog.py`

Диалог хранит частичный выбор и шаг. Каждый шаг возвращает текст + inline-клавиатуру
(`list[list[(text, callback_data)]]`). callback_data формата `c:<field>:<value>`.

- [ ] **Step 1: Написать падающие тесты автомата**

Файл `scraper/tests/test_abitur_dialog.py`:

```python
"""Тесты конечного автомата калькулятора.

Запуск: python -m pytest scraper/tests/test_abitur_dialog.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import dialog


def test_start_asks_level():
    s = dialog.start()
    view = dialog.render(s)
    assert "уровень" in view.text.lower()
    # есть кнопки выбора уровня
    data = [cb for row in view.keyboard for (_, cb) in row]
    assert "c:level:base" in data and "c:level:spec" in data


def test_flow_to_result_base():
    s = dialog.start()
    s, _ = dialog.handle(s, "c:level:base")
    s, _ = dialog.handle(s, "c:pedagogical:0")
    s, _ = dialog.handle(s, "c:target:0")
    # на шаге достижений включаем медаль и считаем
    s, _ = dialog.handle(s, "c:toggle:edu_honors")
    s, done = dialog.handle(s, "c:done:1")
    assert done is True
    result = dialog.compute(s)
    assert result.total == 10


def test_toggle_is_reversible():
    s = dialog.start()
    s, _ = dialog.handle(s, "c:level:base")
    s, _ = dialog.handle(s, "c:pedagogical:1")
    s, _ = dialog.handle(s, "c:target:0")
    s, _ = dialog.handle(s, "c:toggle:svo")
    assert s.svo is True
    s, _ = dialog.handle(s, "c:toggle:svo")
    assert s.svo is False


def test_volunteer_hours_via_text():
    s = dialog.start()
    s, _ = dialog.handle(s, "c:level:base")
    s, _ = dialog.handle(s, "c:pedagogical:1")
    s, _ = dialog.handle(s, "c:target:0")
    s = dialog.set_volunteer_hours(s, 200)
    assert s.volunteer_hours == 200
    assert dialog.compute(s).total == 8


def test_result_text_includes_disclaimer():
    s = dialog.start()
    s, _ = dialog.handle(s, "c:level:base")
    s, _ = dialog.handle(s, "c:pedagogical:0")
    s, _ = dialog.handle(s, "c:target:0")
    s, _ = dialog.handle(s, "c:toggle:edu_honors")
    text = dialog.result_text(dialog.compute(s))
    assert "приёмной комиссией" in text or "предварительн" in text.lower()
    assert "10" in text
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest scraper/tests/test_abitur_dialog.py -v`
Expected: FAIL — `ModuleNotFoundError: scraper.abitur.dialog`.

- [ ] **Step 3: Реализовать `scraper/abitur/dialog.py`**

```python
"""Конечный автомат диалога калькулятора доп. баллов (детерминированный)."""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from scraper.abitur import achievements as A
from scraper.abitur.calculator import CalcInput, CalcResult, calculate

STEP_LEVEL = "level"
STEP_PED = "pedagogical"
STEP_TARGET = "target"
STEP_ACHIEVE = "achieve"
STEP_DONE = "done"

# Тумблеры-достижения, доступные на шаге достижений (id -> подпись кнопки).
TOGGLES_BASE = {
    "edu_honors": "Аттестат/диплом с отличием",
    "abilimpiks": "Абилимпикс",
    "svo": "СВО / добровольч. формирования",
    "do_profile": "ДО искусства/спорта по профилю",
}
TOGGLES_SPEC_EXTRA = {"patents": "Патент"}


@dataclass
class CalcSession:
    step: str = STEP_LEVEL
    level: Optional[str] = None
    pedagogical: bool = False
    target_quota: bool = False
    sport: Optional[str] = None
    edu_honors: bool = False
    abilimpiks: bool = False
    svo: bool = False
    do_profile: bool = False
    olympiad: Optional[str] = None
    volunteer_hours: int = 0
    publications: Optional[str] = None
    patents: bool = False
    fieb: Optional[str] = None
    premia: Optional[str] = None
    target_points: int = 0


@dataclass
class View:
    text: str
    keyboard: List[List[Tuple[str, str]]] = field(default_factory=list)


def start() -> CalcSession:
    return CalcSession()


def _to_input(s: CalcSession) -> CalcInput:
    return CalcInput(
        level=s.level or "base", pedagogical=s.pedagogical,
        target_quota=s.target_quota, sport=s.sport, edu_honors=s.edu_honors,
        abilimpiks=s.abilimpiks, svo=s.svo, do_profile=s.do_profile,
        olympiad=s.olympiad, volunteer_hours=s.volunteer_hours,
        publications=s.publications, patents=s.patents, fieb=s.fieb,
        premia=s.premia, target_points=s.target_points)


def compute(s: CalcSession) -> CalcResult:
    return calculate(_to_input(s))


def set_volunteer_hours(s: CalcSession, hours: int) -> CalcSession:
    s.volunteer_hours = max(0, int(hours))
    return s


def handle(s: CalcSession, data: str) -> Tuple[CalcSession, bool]:
    """Обрабатывает callback. Возвращает (session, done)."""
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "c":
        return s, False
    _, field_, value = parts

    if field_ == "level":
        s.level = value if value in A.LEVELS else "base"
        s.step = STEP_PED
    elif field_ == "pedagogical":
        s.pedagogical = (value == "1")
        s.step = STEP_TARGET
    elif field_ == "target":
        s.target_quota = (value == "1")
        s.step = STEP_ACHIEVE
    elif field_ == "toggle":
        if hasattr(s, value) and isinstance(getattr(s, value), bool):
            setattr(s, value, not getattr(s, value))
    elif field_ == "done":
        s.step = STEP_DONE
        return s, True
    return s, False


def render(s: CalcSession) -> View:
    if s.step == STEP_LEVEL:
        return View("Шаг 1/4. Выберите уровень обучения:", [
            [("БВО / бакалавриат / специалитет", "c:level:base")],
            [("СПВО / магистратура", "c:level:spec")]])
    if s.step == STEP_PED:
        return View("Шаг 2/4. Направление педагогическое (шифр 44.xx)?", [
            [("Да", "c:pedagogical:1"), ("Нет", "c:pedagogical:0")]])
    if s.step == STEP_TARGET:
        return View("Шаг 3/4. Поступаете на целевую квоту?", [
            [("Да", "c:target:1"), ("Нет", "c:target:0")]])
    if s.step == STEP_ACHIEVE:
        toggles = dict(TOGGLES_BASE)
        if s.level == "spec":
            toggles.update(TOGGLES_SPEC_EXTRA)
        rows = []
        for tid, label in toggles.items():
            mark = "✅ " if getattr(s, tid, False) else "▫️ "
            rows.append([(mark + label, f"c:toggle:{tid}")])
        rows.append([("✔️ Посчитать", "c:done:1")])
        return View(
            "Шаг 4/4. Отметьте достижения (волонтёрство — пришлите число часов сообщением), "
            "затем «Посчитать»:", rows)
    return View("Готово.", [])


def result_text(r: CalcResult) -> str:
    lines = ["<b>Предварительный расчёт доп. баллов</b>", ""]
    for label, pts in r.breakdown:
        lines.append(f"• {label}: +{pts}")
    if not r.breakdown:
        lines.append("• достижения не отмечены")
    lines.append("")
    if r.capped:
        lines.append(f"Сумма {r.general_raw} превышает потолок — учтено {r.general_capped}.")
    if r.target_capped:
        lines.append(f"Целевые ИД: +{r.target_capped}")
    lines.append(f"<b>Итого: {r.total} балл(ов)</b>")
    lines.append("")
    lines.append("⚠️ Расчёт предварительный. Точный учёт — приёмной комиссией по "
                 "подтверждающим документам. Перечень: "
                 "https://mpgu.su/wp-content/uploads/2026/03/pk26_prilojenie-7-inye-meropriyatia.pdf")
    return "\n".join(lines)
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python -m pytest scraper/tests/test_abitur_dialog.py -v`
Expected: PASS (5 тестов).

- [ ] **Step 5: Коммит**

```bash
git add scraper/abitur/dialog.py scraper/tests/test_abitur_dialog.py
git commit -m "feat(abitur): calculator dialog state machine"
```

---

## Task 7: Переписать бот (абитур-онли long-polling)

**Files:**
- Rewrite: `scraper/telegram_bot.py`
- Test: `scraper/tests/test_abitur_bot.py`

Бот: тонкий слой. Чистые функции диспетчеризации тестируем; сетевой цикл — нет.
Состояние калькулятора — in-memory `dict[chat_id → CalcSession]`.

- [ ] **Step 1: Написать падающие тесты диспетчеризации**

Файл `scraper/tests/test_abitur_bot.py`:

```python
"""Тесты диспетчеризации бота (без сети).

Запуск: python -m pytest scraper/tests/test_abitur_bot.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scraper.telegram_bot as bot


def setup_function(_):
    bot.SESSIONS.clear()


def test_start_returns_greeting_with_menu():
    out = bot.handle_message(chat_id=1, text="/start")
    assert out.keyboard, "ожидается меню тем"
    assert "абитур" in out.text.lower() or "поступл" in out.text.lower()


def test_menu_lists_topics():
    out = bot.handle_message(chat_id=1, text="/abitur")
    data = [cb for row in out.keyboard for (_, cb) in row]
    assert any(cb.startswith("t:") for cb in data)


def test_calc_command_starts_dialog():
    out = bot.handle_message(chat_id=1, text="/bally")
    assert 1 in bot.SESSIONS
    assert "уровень" in out.text.lower()


def test_volunteer_hours_message_during_calc():
    bot.handle_message(chat_id=2, text="/bally")
    bot.handle_callback(chat_id=2, data="c:level:base")
    bot.handle_callback(chat_id=2, data="c:pedagogical:1")
    bot.handle_callback(chat_id=2, data="c:target:0")
    out = bot.handle_message(chat_id=2, text="200")
    assert bot.SESSIONS[2].volunteer_hours == 200
    assert "200" in out.text or "Шаг" in out.text


def test_topic_callback_returns_answer():
    out = bot.handle_callback(chat_id=3, data="t:contacts")
    assert "priem@mpgu.su" in out.text


def test_free_question_without_credentials_falls_back(monkeypatch):
    # фабрика клиента бросает → деградация без падения
    monkeypatch.setattr(bot, "_answer_free",
                        lambda q: "Спросите кнопками /abitur или у приёмной комиссии: priem@mpgu.su")
    out = bot.handle_message(chat_id=4, text="а когда подавать документы?")
    assert "priem@mpgu.su" in out.text
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest scraper/tests/test_abitur_bot.py -v`
Expected: FAIL — у `telegram_bot` нет `handle_message`/`handle_callback`/`SESSIONS`.

- [ ] **Step 3: Переписать `scraper/telegram_bot.py`**

```python
"""Telegram-бот абитуриента МПГУ на long-polling (GitHub Actions).

Без хостинга/вебхуков: воркфлоу периодически запускает скрипт, он опрашивает getUpdates
~55 минут и отвечает почти мгновенно, затем выходит; крон перезапускает.
Нужны секреты: BOT_TOKEN (Telegram) и ANTHROPIC_API_KEY (для AI-ответов; без него
кнопки и калькулятор работают, AI-ветка деградирует).

Локальный прогон логики (без Telegram):
    python -m scraper.telegram_bot --selftest "/bally"
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from scraper.abitur import dialog, faq, llm

RUN_SECONDS = int(os.environ.get("RUN_SECONDS", "3300"))
MAX_MSG_LEN = 1000

# In-memory состояние калькулятора по chat_id (эфемерно, теряется при рестарте).
SESSIONS: Dict[int, dialog.CalcSession] = {}


@dataclass
class Reply:
    text: str
    keyboard: List[List[Tuple[str, str]]] = field(default_factory=list)


def _menu_keyboard() -> List[List[Tuple[str, str]]]:
    rows, row = [], []
    for tid, (label, _) in faq.TOPICS.items():
        row.append((label, f"t:{tid}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([("➕ Калькулятор баллов", "open:calc")])
    return rows


_GREETING = ("👋 Я помощник абитуриента МПГУ.\n\n"
             "Спросите про поступление или выберите тему ниже. "
             "Команда /bally — калькулятор дополнительных баллов.")


def _answer_free(question: str) -> str:
    return llm.answer(question)


def handle_message(chat_id: int, text: str) -> Reply:
    text = (text or "")[:MAX_MSG_LEN].strip()
    # ввод часов волонтёрства во время калькулятора
    sess = SESSIONS.get(chat_id)
    if sess is not None and sess.step == dialog.STEP_ACHIEVE and text.isdigit():
        dialog.set_volunteer_hours(sess, int(text))
        v = dialog.render(sess)
        return Reply(f"Часы волонтёрства: {sess.volunteer_hours}.\n\n{v.text}", v.keyboard)

    intent, payload = faq.route(text)
    if intent == "start":
        return Reply(_GREETING, _menu_keyboard())
    if intent == "help":
        return Reply(_GREETING, _menu_keyboard())
    if intent == "menu":
        return Reply("Выберите тему:", _menu_keyboard())
    if intent == "calc":
        s = dialog.start()
        SESSIONS[chat_id] = s
        v = dialog.render(s)
        return Reply(v.text, v.keyboard)
    # свободный вопрос
    return Reply(_answer_free(payload), [])


def handle_callback(chat_id: int, data: str) -> Reply:
    if data.startswith("t:"):
        ans = faq.topic_answer(data[2:])
        return Reply(ans or "Тема не найдена.", [])
    if data == "open:calc":
        s = dialog.start()
        SESSIONS[chat_id] = s
        v = dialog.render(s)
        return Reply(v.text, v.keyboard)
    if data.startswith("c:"):
        s = SESSIONS.get(chat_id) or dialog.start()
        SESSIONS[chat_id] = s
        s, done = dialog.handle(s, data)
        if done:
            result = dialog.compute(s)
            SESSIONS.pop(chat_id, None)
            return Reply(dialog.result_text(result), [])
        v = dialog.render(s)
        return Reply(v.text, v.keyboard)
    return Reply("Неизвестная команда.", [])


# ── Telegram I/O ──────────────────────────────────────────────────────────────

def _api(token: str, method: str, **params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _markup(keyboard: List[List[Tuple[str, str]]]) -> Optional[str]:
    if not keyboard:
        return None
    return json.dumps({"inline_keyboard": [
        [{"text": t, "callback_data": cb} for (t, cb) in row] for row in keyboard]})


def _send(token: str, chat_id: int, reply: Reply):
    params = {"chat_id": chat_id, "text": reply.text, "parse_mode": "HTML",
              "disable_web_page_preview": "true"}
    mk = _markup(reply.keyboard)
    if mk:
        params["reply_markup"] = mk
    _api(token, "sendMessage", **params)


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        print(handle_message(0, sys.argv[2]).text)
        return 0
    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN не задан — пропускаю. Выход.")
        return 0
    deadline = time.time() + RUN_SECONDS
    offset = None
    print(f"Бот запущен на {RUN_SECONDS}s")
    while time.time() < deadline:
        try:
            resp = _api(token, "getUpdates", offset=offset or "", timeout=30,
                        allowed_updates='["message","callback_query"]')
        except Exception as e:
            print(f"getUpdates error: {e}"); time.sleep(3); continue
        for upd in resp.get("result", []):
            offset = upd["update_id"] + 1
            try:
                if "message" in upd:
                    msg = upd["message"]
                    chat = (msg.get("chat") or {}).get("id")
                    text = msg.get("text") or ""
                    if chat and text:
                        _send(token, chat, handle_message(chat, text))
                elif "callback_query" in upd:
                    cq = upd["callback_query"]
                    chat = (((cq.get("message") or {}).get("chat")) or {}).get("id")
                    data = cq.get("data") or ""
                    try:
                        _api(token, "answerCallbackQuery", callback_query_id=cq["id"])
                    except Exception:
                        pass
                    if chat and data:
                        _send(token, chat, handle_callback(chat, data))
            except Exception as e:
                print(f"handle error: {e}")
    print("Время вышло, выход")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Запустить тест бота и весь набор abitur**

Run: `python -m pytest scraper/tests/test_abitur_bot.py scraper/tests/test_abitur_calculator.py scraper/tests/test_abitur_faq.py scraper/tests/test_abitur_llm.py scraper/tests/test_abitur_dialog.py -v`
Expected: PASS (все тесты).

- [ ] **Step 5: Проверить selftest вручную**

Run: `python -m scraper.telegram_bot --selftest "/bally"`
Expected: вывод с текстом «Шаг 1/4. Выберите уровень обучения:».

- [ ] **Step 6: Коммит**

```bash
git add scraper/telegram_bot.py scraper/tests/test_abitur_bot.py
git commit -m "feat(abitur): rewrite bot as admissions-only (FAQ + calculator), drop schedule"
```

---

## Task 8: Деплой и документация

**Files:**
- Modify: `.github/workflows/bot-poll.yml`
- Modify: `cloudflare-worker-bot/README.md`

- [ ] **Step 1: Пробросить `ANTHROPIC_API_KEY` в воркфлоу бота**

В `.github/workflows/bot-poll.yml` в шаге `Run bot (long-polling)` блок `env:` дополнить
(было только `BOT_TOKEN` и `RUN_SECONDS`):

```yaml
      - name: Run bot (long-polling)
        env:
          BOT_TOKEN: ${{ secrets.BOT_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          RUN_SECONDS: "3300"
        run: python -m scraper.telegram_bot
```

- [ ] **Step 2: Обновить README бота**

Заменить описание в `cloudflare-worker-bot/README.md` (или добавить раздел), отразив, что
бот теперь абитуриентский: команды `/start`, `/help`, `/abitur` (меню тем), `/bally`
(калькулятор доп. баллов), свободные вопросы — AI на Haiku 4.5 по базе знаний
`scraper/abitur/knowledge.md`; нужны секреты `BOT_TOKEN` и `ANTHROPIC_API_KEY`.

- [ ] **Step 3: Финальный прогон всех тестов**

Run: `python -m pytest scraper/tests/ -v`
Expected: PASS — новые abitur-тесты зелёные, существующие (`test_build_ical`, `test_sanitize`) не сломаны.

- [ ] **Step 4: Коммит**

```bash
git add .github/workflows/bot-poll.yml cloudflare-worker-bot/README.md
git commit -m "chore(abitur): wire ANTHROPIC_API_KEY into bot workflow, update README"
```

---

## Self-Review (выполнено автором плана)

**Покрытие спека:**
- KB (knowledge.md) — Task 3; темы FAQ — Task 4; AI-ответ Haiku + заземление + фолбэк — Task 5.
- Калькулятор: данные правил — Task 1; чистый расчёт с потолками/«один вид спорта»/волонтёрство — Task 2; диалог/состояние/inline — Task 6; интеграция в бот — Task 7.
- Абитур-онли (расписание убрано из бота, парсеры в репо сохранены) — Task 7.
- Деградация без ключа — Task 5 (фолбэк) + Task 7 (диспетчеризация) + Task 8 (env).
- Списки `epk25` — намеренно вне плана (подпроект B).

**Плейсхолдеры:** не найдено — в каждом шаге реальный код/команды.

**Согласованность типов:** `CalcInput`/`CalcResult` (Task 2) используются в `dialog` (Task 6) и тестах единообразно; `Reply` и `SESSIONS` бота (Task 7) согласованы с тестами; `faq.TOPICS`/`route`/`topic_answer` (Task 4) совпадают по сигнатурам в боте и тестах; callback-форматы `c:*`/`t:*`/`open:calc` согласованы между `dialog`, `telegram_bot` и тестами.
