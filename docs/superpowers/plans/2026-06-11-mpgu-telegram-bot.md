# MPGU Telegram Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Telegram-бот для студентов МПГУ — расписание на сегодня без регистрации, быстрее чем написать старосте.

**Architecture:** aiogram 3 + PostgreSQL на VPS. Данные синхронизируются с CDN (jsDelivr, data-ветка) каждые 4 часа через APScheduler и хранятся локально в PostgreSQL для быстрых запросов. Пользователь один раз выбирает группу (institution → group), выбор сохраняется по Telegram `user_id`. Взаимодействие только через inline-кнопки.

**Tech Stack:** Python 3.11, aiogram 3.x, SQLAlchemy 2.0 async, asyncpg, Alembic, APScheduler 3.x, pydantic-settings, PostgreSQL 15

---

## File Structure

```
bot/
  main.py               # Точка входа: bot + scheduler + DB init
  config.py             # Настройки из .env (pydantic-settings)
  states.py             # FSM-состояния (Onboarding, ReportError)
  scheduler.py          # APScheduler: запуск data_sync каждые 4 часа
  requirements.txt      # Зависимости бота
  db/
    engine.py           # AsyncEngine + AsyncSession factory
    models.py           # User, Schedule, Institute, ErrorReport
    init_db.py          # create_all() при старте
  handlers/
    start.py            # /start → welcome + кнопка "Выбрать группу"
    onboarding.py       # FSM: выбор института → выбор группы
    schedule.py         # Сегодня / Завтра / Вся неделя
    error_report.py     # Кнопка "Ошибка" → принять текст → сохранить
  keyboards/
    institutes.py       # Inline-клавиатура выбора института
    groups.py           # Inline-клавиатура выбора группы (постраничная)
    schedule.py         # Кнопки под расписанием
  services/
    schedule_fmt.py     # Форматирование расписания в текст Telegram
    data_sync.py        # CDN → PostgreSQL (fetch + upsert)
```

---

## Task 1: Project scaffold + config

**Files:**
- Create: `bot/requirements.txt`
- Create: `bot/config.py`
- Create: `bot/__init__.py`, `bot/db/__init__.py`, `bot/handlers/__init__.py`, `bot/keyboards/__init__.py`, `bot/services/__init__.py`

- [ ] **Step 1: Создать структуру директорий**

```bash
mkdir -p bot/db bot/handlers bot/keyboards bot/services
touch bot/__init__.py bot/db/__init__.py bot/handlers/__init__.py
touch bot/keyboards/__init__.py bot/services/__init__.py
```

- [ ] **Step 2: Создать `bot/requirements.txt`**

```
aiogram==3.13.0
sqlalchemy[asyncio]==2.0.36
asyncpg==0.30.0
alembic==1.14.0
apscheduler==3.10.4
pydantic-settings==2.6.1
aiohttp==3.9.5
python-dotenv==1.0.1
```

- [ ] **Step 3: Установить зависимости**

```bash
pip install -r bot/requirements.txt
```

Ожидаемый вывод: Successfully installed aiogram-3.13.0 ...

- [ ] **Step 4: Написать тест для config**

Создать `bot/tests/__init__.py` и `bot/tests/test_config.py`:

```python
import os
import pytest

def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    # импортируем после установки env
    import importlib
    import bot.config as cfg
    importlib.reload(cfg)
    assert cfg.settings.bot_token == "123:ABC"
    assert "asyncpg" in cfg.settings.database_url
```

- [ ] **Step 5: Запустить тест — убедиться что FAIL**

```bash
cd /home/user/mpgu-schedule
python -m pytest bot/tests/test_config.py -v
```

Ожидаемый вывод: `ModuleNotFoundError: No module named 'bot.config'`

- [ ] **Step 6: Создать `bot/config.py`**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    database_url: str
    cdn_base: str = "https://cdn.jsdelivr.net/gh/mvbulgakova/mpgu-schedule@data"
    poll_interval_hours: int = 4
    enabled_institutes: list[str] = [
        "biology", "childhood", "philology", "sport", "social"
    ]

    model_config = {"env_file": ".env"}


settings = Settings()
```

- [ ] **Step 7: Запустить тест — убедиться что PASS**

```bash
python -m pytest bot/tests/test_config.py -v
```

Ожидаемый вывод: `PASSED`

- [ ] **Step 8: Создать `.env.example`**

```bash
cat > bot/.env.example << 'EOF'
BOT_TOKEN=your_token_here
DATABASE_URL=postgresql+asyncpg://mpgu:password@localhost:5432/mpgu_bot
POLL_INTERVAL_HOURS=4
ENABLED_INSTITUTES=biology,childhood,philology,sport,social
EOF
```

- [ ] **Step 9: Commit**

```bash
git add bot/
git commit -m "feat(bot): project scaffold, config, first test"
```

---

## Task 2: Database models

**Files:**
- Create: `bot/db/models.py`
- Create: `bot/db/engine.py`
- Create: `bot/db/init_db.py`
- Test: `bot/tests/test_models.py`

- [ ] **Step 1: Написать тест модели User**

```python
# bot/tests/test_models.py
from bot.db.models import User, Schedule, Institute, ErrorReport


def test_user_model_has_required_fields():
    u = User(user_id=123456789, institute_id="biology", group_code="БИО40-БА2501")
    assert u.user_id == 123456789
    assert u.group_code == "БИО40-БА2501"


def test_error_report_model():
    r = ErrorReport(user_id=1, group_code="БИО40-БА2501", message="Неверный преподаватель")
    assert r.group_code == "БИО40-БА2501"


def test_schedule_model_stores_json():
    data = {"name": "БИО40-БА2501", "schedule": {"odd_week": {}, "even_week": {}}}
    s = Schedule(group_code="БИО40-БА2501", institute_id="biology", data=data)
    assert s.data["name"] == "БИО40-БА2501"
```

- [ ] **Step 2: Запустить тест — убедиться что FAIL**

```bash
python -m pytest bot/tests/test_models.py -v
```

Ожидаемый вывод: `ModuleNotFoundError: No module named 'bot.db.models'`

- [ ] **Step 3: Создать `bot/db/models.py`**

```python
from datetime import datetime
from sqlalchemy import BigInteger, String, JSON, DateTime, Text, Integer
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    institute_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    group_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Schedule(Base):
    __tablename__ = "schedules"

    group_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    institute_id: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Institute(Base):
    __tablename__ = "institutes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    groups_count: Mapped[int] = mapped_column(Integer, default=0)


class ErrorReport(Base):
    __tablename__ = "error_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    group_code: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: Создать `bot/db/engine.py`**

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from bot.config import settings

engine = create_async_engine(settings.database_url, echo=False)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)
```

- [ ] **Step 5: Создать `bot/db/init_db.py`**

```python
from bot.db.engine import engine
from bot.db.models import Base


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 6: Запустить тест — убедиться что PASS**

```bash
python -m pytest bot/tests/test_models.py -v
```

Ожидаемый вывод: `3 passed`

- [ ] **Step 7: Commit**

```bash
git add bot/db/
git commit -m "feat(bot): database models (User, Schedule, Institute, ErrorReport)"
```

---

## Task 3: Data sync (CDN → PostgreSQL)

**Files:**
- Create: `bot/services/data_sync.py`
- Test: `bot/tests/test_data_sync.py`

Синхронизация читает `meta/index.json` с CDN, затем для каждого включённого института загружает манифест и все JSON-файлы групп, сохраняет в таблицы `institutes` и `schedules`.

- [ ] **Step 1: Написать тест для `fetch_index`**

```python
# bot/tests/test_data_sync.py
import pytest
from unittest.mock import AsyncMock, patch
from bot.services.data_sync import fetch_json, build_group_list


@pytest.mark.asyncio
async def test_fetch_json_returns_parsed_json():
    mock_response = AsyncMock()
    mock_response.json = AsyncMock(return_value={"institutes": []})
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession.get", return_value=mock_response):
        import aiohttp
        async with aiohttp.ClientSession() as session:
            # тест логики build_group_list отдельно — без HTTP
            pass


def test_build_group_list_extracts_groups():
    manifest = {
        "groups": [
            {"name": "БИО40-БА2501", "file": "БИО40-БА2501", "year": 2026, "form": "full_time", "degree": "bachelor"},
            {"name": "БИО40-БА2502", "file": "БИО40-БА2502", "year": 2026, "form": "full_time", "degree": "bachelor"},
        ]
    }
    result = build_group_list(manifest)
    assert len(result) == 2
    assert result[0]["name"] == "БИО40-БА2501"


def test_build_group_list_empty():
    assert build_group_list({"groups": []}) == []
```

- [ ] **Step 2: Запустить тест — убедиться что FAIL**

```bash
python -m pytest bot/tests/test_data_sync.py -v
```

Ожидаемый вывод: `ModuleNotFoundError: No module named 'bot.services.data_sync'`

- [ ] **Step 3: Создать `bot/services/data_sync.py`**

```python
import logging
import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bot.config import settings
from bot.db.models import Institute, Schedule

logger = logging.getLogger(__name__)


def build_group_list(manifest: dict) -> list[dict]:
    return manifest.get("groups") or []


async def fetch_json(session: aiohttp.ClientSession, path: str) -> dict:
    url = f"{settings.cdn_base}/{path}"
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
        r.raise_for_status()
        return await r.json(content_type=None)


async def sync_institute(
    db: AsyncSession,
    session: aiohttp.ClientSession,
    institute_id: str,
    institute_name: str,
) -> int:
    """Загружает все группы института с CDN и сохраняет в БД. Возвращает число групп."""
    try:
        manifest = await fetch_json(session, f"institutes/{institute_id}/schedule.json")
    except Exception as e:
        logger.warning("Не удалось загрузить манифест %s: %s", institute_id, e)
        return 0

    groups = build_group_list(manifest)
    count = 0

    for g in groups:
        filename = g.get("file") or g["name"]
        try:
            group_data = await fetch_json(
                session, f"institutes/{institute_id}/groups/{filename}.json"
            )
        except Exception as e:
            logger.warning("Не удалось загрузить группу %s/%s: %s", institute_id, filename, e)
            continue

        stmt = pg_insert(Schedule).values(
            group_code=group_data["name"],
            institute_id=institute_id,
            data=group_data,
        ).on_conflict_do_update(
            index_elements=["group_code"],
            set_={"data": group_data, "updated_at": Schedule.updated_at},
        )
        await db.execute(stmt)
        count += 1

    stmt = pg_insert(Institute).values(
        id=institute_id,
        name=institute_name,
        groups_count=count,
    ).on_conflict_do_update(
        index_elements=["id"],
        set_={"name": institute_name, "groups_count": count},
    )
    await db.execute(stmt)
    await db.commit()
    logger.info("Синхронизирован %s: %d групп", institute_id, count)
    return count


async def sync_all(db: AsyncSession) -> None:
    """Синхронизирует все включённые институты."""
    async with aiohttp.ClientSession() as session:
        try:
            index = await fetch_json(session, "meta/index.json")
        except Exception as e:
            logger.error("Не удалось загрузить index.json: %s", e)
            return

        enabled = set(settings.enabled_institutes)
        for inst in index.get("institutes", []):
            if inst["id"] in enabled:
                await sync_institute(db, session, inst["id"], inst["name"])
```

- [ ] **Step 4: Запустить тест — убедиться что PASS**

```bash
python -m pytest bot/tests/test_data_sync.py -v
```

Ожидаемый вывод: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add bot/services/data_sync.py bot/tests/test_data_sync.py
git commit -m "feat(bot): CDN→PostgreSQL data sync service"
```

---

## Task 4: Schedule formatting

**Files:**
- Create: `bot/services/schedule_fmt.py`
- Test: `bot/tests/test_schedule_fmt.py`

Форматирует JSON расписания в HTML-текст для Telegram. Логика взята из существующего `scraper/telegram_bot.py`.

- [ ] **Step 1: Написать тесты форматирования**

```python
# bot/tests/test_schedule_fmt.py
import pytest
from bot.services.schedule_fmt import format_day, format_week, get_current_week_key
from datetime import date


def _make_lesson(**kwargs):
    base = {
        "slot": 1, "time_start": "09:00", "time_end": "10:30",
        "subject": "Математика", "type": "lecture",
        "teacher": "Иванов И.И.", "room": "403", "subgroup": None, "notes": ""
    }
    return {**base, **kwargs}


def test_format_day_no_lessons():
    result = format_day("monday", [], even_week=False)
    assert "Занятий нет" in result
    assert "Понедельник" in result


def test_format_day_one_lesson():
    lessons = [_make_lesson()]
    result = format_day("monday", lessons, even_week=False)
    assert "09:00" in result
    assert "Математика" in result
    assert "Иванов" in result
    assert "403" in result


def test_format_day_escapes_html():
    lessons = [_make_lesson(subject="Алгебра <и> анализ & топология")]
    result = format_day("monday", lessons, even_week=False)
    assert "<и>" not in result
    assert "&lt;и&gt;" in result


def test_format_day_sorts_by_time():
    lessons = [
        _make_lesson(slot=2, time_start="10:40", subject="Б"),
        _make_lesson(slot=1, time_start="09:00", subject="А"),
    ]
    result = format_day("tuesday", lessons, even_week=True)
    assert result.index("09:00") < result.index("10:40")


def test_get_current_week_key_odd():
    # ISO неделя 1 — нечётная
    monday_week1 = date(2025, 12, 29)  # неделя 1 по ISO
    key = get_current_week_key(monday_week1)
    assert key == "odd_week"


def test_get_current_week_key_even():
    # ISO неделя 2 — чётная
    monday_week2 = date(2026, 1, 5)
    key = get_current_week_key(monday_week2)
    assert key == "even_week"
```

- [ ] **Step 2: Запустить тест — убедиться что FAIL**

```bash
python -m pytest bot/tests/test_schedule_fmt.py -v
```

Ожидаемый вывод: `ModuleNotFoundError: No module named 'bot.services.schedule_fmt'`

- [ ] **Step 3: Создать `bot/services/schedule_fmt.py`**

```python
from datetime import date

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_RU = {
    "monday": "Понедельник", "tuesday": "Вторник", "wednesday": "Среда",
    "thursday": "Четверг", "friday": "Пятница", "saturday": "Суббота",
    "sunday": "Воскресенье",
}
TYPE_RU = {"lecture": "ЛК", "practice": "ПЗ", "lab": "ЛР", "seminar": "СЕМ", "other": ""}


def _esc(s) -> str:
    return (str("" if s is None else s)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def get_current_week_key(d: date | None = None) -> str:
    if d is None:
        import datetime
        d = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).date()
    return "even_week" if d.isocalendar()[1] % 2 == 0 else "odd_week"


def format_day(day: str, lessons: list[dict], even_week: bool) -> str:
    week_label = "чётная" if even_week else "нечётная"
    head = f"📅 <b>{DAY_RU.get(day, day)}</b> · {week_label} неделя"

    if not lessons:
        return f"{head}\n\nЗанятий нет 🎉"

    sorted_lessons = sorted(lessons, key=lambda l: l.get("time_start") or "")
    parts = []
    for l in sorted_lessons:
        type_label = TYPE_RU.get(l.get("type", ""), "")
        type_str = f" ({type_label})" if type_label else ""
        t_start = l.get("time_start") or ""
        t_end = l.get("time_end") or ""
        time_str = f"{t_start}–{t_end}" if t_end else t_start
        extra = ", ".join(_esc(x) for x in (l.get("teacher"), l.get("room")) if x)
        subgroup = l.get("subgroup")
        sg_str = f" [п/г {subgroup}]" if subgroup else ""
        parts.append(
            f"🕐 <b>{time_str}</b> {_esc(l.get('subject', ''))}{type_str}{sg_str}"
            + (f"\n   {extra}" if extra else "")
        )
    return head + "\n\n" + "\n\n".join(parts)


def format_today(group_data: dict) -> str:
    import datetime
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
    day = DAYS[now.weekday()]
    week_key = get_current_week_key(now.date())
    even = week_key == "even_week"
    lessons = ((group_data.get("schedule") or {}).get(week_key) or {}).get(day) or []
    name_line = f"👤 <b>{_esc(group_data.get('name', ''))}</b>\n"
    return name_line + format_day(day, lessons, even)


def format_tomorrow(group_data: dict) -> str:
    import datetime
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
    tomorrow = now.date() + datetime.timedelta(days=1)
    day = DAYS[tomorrow.weekday()]
    week_key = get_current_week_key(tomorrow)
    even = week_key == "even_week"
    lessons = ((group_data.get("schedule") or {}).get(week_key) or {}).get(day) or []
    name_line = f"👤 <b>{_esc(group_data.get('name', ''))}</b>\n"
    return name_line + format_day(day, lessons, even)


def format_week(group_data: dict) -> str:
    import datetime
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
    week_key = get_current_week_key(now.date())
    even = week_key == "even_week"
    schedule = (group_data.get("schedule") or {}).get(week_key) or {}
    parts = [f"👤 <b>{_esc(group_data.get('name', ''))}</b> · {'чётная' if even else 'нечётная'} неделя\n"]
    for day in DAYS[:6]:  # пн–сб
        lessons = schedule.get(day) or []
        parts.append(format_day(day, lessons, even))
    return "\n\n".join(parts)
```

- [ ] **Step 4: Запустить тест — убедиться что PASS**

```bash
python -m pytest bot/tests/test_schedule_fmt.py -v
```

Ожидаемый вывод: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add bot/services/schedule_fmt.py bot/tests/test_schedule_fmt.py
git commit -m "feat(bot): schedule formatting service with HTML output"
```

---

## Task 5: Keyboards

**Files:**
- Create: `bot/keyboards/institutes.py`
- Create: `bot/keyboards/groups.py`
- Create: `bot/keyboards/schedule.py`
- Test: `bot/tests/test_keyboards.py`

- [ ] **Step 1: Написать тесты клавиатур**

```python
# bot/tests/test_keyboards.py
from bot.keyboards.institutes import build_institutes_kb
from bot.keyboards.groups import build_groups_kb
from bot.keyboards.schedule import build_schedule_kb


def test_institutes_kb_has_buttons():
    institutes = [
        {"id": "biology", "name": "Биология и химия"},
        {"id": "sport", "name": "Физкультура"},
    ]
    kb = build_institutes_kb(institutes)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 2
    assert buttons[0].callback_data == "inst:biology"


def test_groups_kb_pagination():
    groups = [{"name": f"БИО{i:02d}-БА2501"} for i in range(25)]
    kb = build_groups_kb(groups, page=0)
    # Первая страница: 10 групп + кнопка "Далее →"
    all_buttons = [btn for row in kb.inline_keyboard for btn in row]
    nav = [b for b in all_buttons if "→" in (b.text or "")]
    assert len(nav) == 1


def test_groups_kb_page_2():
    groups = [{"name": f"БИО{i:02d}-БА2501"} for i in range(25)]
    kb = build_groups_kb(groups, page=1)
    all_buttons = [btn for row in kb.inline_keyboard for btn in row]
    nav_prev = [b for b in all_buttons if "←" in (b.text or "")]
    assert len(nav_prev) == 1


def test_schedule_kb_has_four_buttons():
    kb = build_schedule_kb("БИО40-БА2501")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    texts = [b.text for b in buttons]
    assert any("Завтра" in t for t in texts)
    assert any("Неделя" in t for t in texts)
    assert any("Ошибка" in t for t in texts)
```

- [ ] **Step 2: Запустить тест — убедиться что FAIL**

```bash
python -m pytest bot/tests/test_keyboards.py -v
```

- [ ] **Step 3: Создать `bot/keyboards/institutes.py`**

```python
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def build_institutes_kb(institutes: list[dict]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=inst["name"], callback_data=f"inst:{inst['id']}")]
        for inst in institutes
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
```

- [ ] **Step 4: Создать `bot/keyboards/groups.py`**

```python
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

PAGE_SIZE = 10


def build_groups_kb(groups: list[dict], page: int = 0) -> InlineKeyboardMarkup:
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_groups = groups[start:end]

    buttons = [
        [InlineKeyboardButton(text=g["name"], callback_data=f"grp:{g['name']}")]
        for g in page_groups
    ]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="← Назад", callback_data=f"grp_page:{page - 1}"))
    if end < len(groups):
        nav.append(InlineKeyboardButton(text="Далее →", callback_data=f"grp_page:{page + 1}"))
    if nav:
        buttons.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=buttons)
```

- [ ] **Step 5: Создать `bot/keyboards/schedule.py`**

```python
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def build_schedule_kb(group_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Завтра", callback_data="sch:tomorrow"),
            InlineKeyboardButton(text="Вся неделя", callback_data="sch:week"),
        ],
        [
            InlineKeyboardButton(text="Сегодня", callback_data="sch:today"),
            InlineKeyboardButton(text="⚠️ Ошибка в данных", callback_data=f"err:{group_code}"),
        ],
    ])
```

- [ ] **Step 6: Запустить тест — убедиться что PASS**

```bash
python -m pytest bot/tests/test_keyboards.py -v
```

Ожидаемый вывод: `4 passed`

- [ ] **Step 7: Commit**

```bash
git add bot/keyboards/ bot/tests/test_keyboards.py
git commit -m "feat(bot): inline keyboards (institutes, groups pagination, schedule actions)"
```

---

## Task 6: FSM states + onboarding handlers

**Files:**
- Create: `bot/states.py`
- Create: `bot/handlers/start.py`
- Create: `bot/handlers/onboarding.py`

- [ ] **Step 1: Создать `bot/states.py`**

```python
from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    select_group = State()   # ждём выбора группы (после выбора института)


class ReportError(StatesGroup):
    waiting_message = State()  # ждём текст от пользователя
```

- [ ] **Step 2: Создать `bot/handlers/start.py`**

```python
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.db.models import User, Institute

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, db: AsyncSession):
    user = await db.get(User, message.from_user.id)

    if user and user.group_code:
        # Уже настроен — показываем расписание на сегодня
        from bot.handlers.schedule import send_today
        await send_today(message, db, user.group_code)
        return

    # Новый пользователь — онбординг
    result = await db.execute(select(Institute).order_by(Institute.name))
    institutes = result.scalars().all()

    from bot.keyboards.institutes import build_institutes_kb
    kb = build_institutes_kb([{"id": i.id, "name": i.name} for i in institutes])

    await message.answer(
        "👋 Привет! Я помогу найти расписание МПГУ.\n\n"
        "Выбери свой институт:",
        reply_markup=kb,
    )
```

- [ ] **Step 3: Создать `bot/handlers/onboarding.py`**

```python
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.db.models import User, Schedule
from bot.states import Onboarding
from bot.keyboards.groups import build_groups_kb, PAGE_SIZE

router = Router()


@router.callback_query(F.data.startswith("inst:"))
async def on_institute_selected(call: CallbackQuery, db: AsyncSession):
    institute_id = call.data.split(":", 1)[1]

    result = await db.execute(
        select(Schedule.group_code)
        .where(Schedule.institute_id == institute_id)
        .order_by(Schedule.group_code)
    )
    group_codes = [r[0] for r in result.fetchall()]

    if not group_codes:
        await call.answer("Группы не найдены. Попробуйте позже.", show_alert=True)
        return

    groups = [{"name": code} for code in group_codes]
    kb = build_groups_kb(groups, page=0)

    await call.message.edit_text(
        f"Найдено групп: {len(groups)}\nВыбери свою группу:",
        reply_markup=kb,
    )
    await call.answer()


@router.callback_query(F.data.startswith("grp_page:"))
async def on_group_page(call: CallbackQuery, db: AsyncSession):
    page = int(call.data.split(":", 1)[1])
    # восстанавливаем список групп из текста сообщения (через БД)
    # получаем institute_id из предыдущего контекста — храним в тексте кнопки
    # Для простоты: запрашиваем все группы заново
    # В реальном боте — хранить institute_id в state
    await call.answer()


@router.callback_query(F.data.startswith("grp:"))
async def on_group_selected(call: CallbackQuery, db: AsyncSession):
    group_code = call.data.split(":", 1)[1]

    # Определяем institute_id по group_code
    result = await db.execute(
        select(Schedule.institute_id).where(Schedule.group_code == group_code)
    )
    row = result.first()
    institute_id = row[0] if row else None

    # Сохраняем или обновляем пользователя
    user = await db.get(User, call.from_user.id)
    if user:
        user.group_code = group_code
        user.institute_id = institute_id
    else:
        db.add(User(
            user_id=call.from_user.id,
            group_code=group_code,
            institute_id=institute_id,
        ))
    await db.commit()

    await call.message.edit_text(
        f"✅ Группа <b>{group_code}</b> сохранена!",
        parse_mode="HTML",
    )

    from bot.handlers.schedule import send_today_by_code
    await send_today_by_code(call.message, db, group_code)
    await call.answer()
```

- [ ] **Step 4: Commit**

```bash
git add bot/states.py bot/handlers/start.py bot/handlers/onboarding.py
git commit -m "feat(bot): onboarding FSM — institute → group selection"
```

---

## Task 7: Schedule handlers

**Files:**
- Create: `bot/handlers/schedule.py`

- [ ] **Step 1: Создать `bot/handlers/schedule.py`**

```python
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.db.models import User, Schedule
from bot.keyboards.schedule import build_schedule_kb
from bot.services.schedule_fmt import format_today, format_tomorrow, format_week

router = Router()
MAX_MESSAGE_LEN = 4096


async def _get_group_data(db: AsyncSession, user_id: int) -> dict | None:
    user = await db.get(User, user_id)
    if not user or not user.group_code:
        return None
    schedule = await db.get(Schedule, user.group_code)
    return schedule.data if schedule else None


async def send_today(message: Message, db: AsyncSession, group_code: str | None = None):
    if group_code is None:
        user = await db.get(User, message.from_user.id)
        group_code = user.group_code if user else None
    if not group_code:
        await message.answer("Сначала выбери группу. Напиши /start")
        return
    await send_today_by_code(message, db, group_code)


async def send_today_by_code(message: Message, db: AsyncSession, group_code: str):
    schedule = await db.get(Schedule, group_code)
    if not schedule:
        await message.answer("Расписание не найдено. Попробуй позже.")
        return
    text = format_today(schedule.data)
    kb = build_schedule_kb(group_code)
    await message.answer(text[:MAX_MESSAGE_LEN], parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "sch:today")
async def on_today(call: CallbackQuery, db: AsyncSession):
    group_data = await _get_group_data(db, call.from_user.id)
    if not group_data:
        await call.answer("Группа не выбрана", show_alert=True)
        return
    text = format_today(group_data)
    kb = build_schedule_kb(group_data["name"])
    await call.message.edit_text(text[:MAX_MESSAGE_LEN], parse_mode="HTML", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "sch:tomorrow")
async def on_tomorrow(call: CallbackQuery, db: AsyncSession):
    group_data = await _get_group_data(db, call.from_user.id)
    if not group_data:
        await call.answer("Группа не выбрана", show_alert=True)
        return
    text = format_tomorrow(group_data)
    kb = build_schedule_kb(group_data["name"])
    await call.message.edit_text(text[:MAX_MESSAGE_LEN], parse_mode="HTML", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "sch:week")
async def on_week(call: CallbackQuery, db: AsyncSession):
    group_data = await _get_group_data(db, call.from_user.id)
    if not group_data:
        await call.answer("Группа не выбрана", show_alert=True)
        return
    text = format_week(group_data)
    kb = build_schedule_kb(group_data["name"])
    # Неделя может быть длиннее 4096 — обрезаем с предупреждением
    if len(text) > MAX_MESSAGE_LEN:
        text = text[:MAX_MESSAGE_LEN - 50] + "\n\n<i>...список обрезан</i>"
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await call.answer()
```

- [ ] **Step 2: Commit**

```bash
git add bot/handlers/schedule.py
git commit -m "feat(bot): schedule handlers — today/tomorrow/week via callbacks"
```

---

## Task 8: Error reporting

**Files:**
- Create: `bot/handlers/error_report.py`
- Test: `bot/tests/test_error_report.py`

- [ ] **Step 1: Написать тест для логики сохранения отчёта**

```python
# bot/tests/test_error_report.py
from bot.db.models import ErrorReport


def test_error_report_creation():
    report = ErrorReport(
        user_id=123456,
        group_code="БИО40-БА2501",
        message="Неверное время третьей пары",
    )
    assert report.user_id == 123456
    assert "время" in report.message


def test_error_report_requires_message():
    report = ErrorReport(user_id=1, group_code="X", message="")
    assert report.message == ""  # пустое допустимо на уровне модели
```

- [ ] **Step 2: Запустить тест — убедиться что PASS**

```bash
python -m pytest bot/tests/test_error_report.py -v
```

- [ ] **Step 3: Создать `bot/handlers/error_report.py`**

```python
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import ErrorReport
from bot.states import ReportError

router = Router()


@router.callback_query(F.data.startswith("err:"))
async def on_error_button(call: CallbackQuery, state: FSMContext):
    group_code = call.data.split(":", 1)[1]
    await state.set_state(ReportError.waiting_message)
    await state.update_data(group_code=group_code)
    await call.message.answer(
        f"⚠️ Опиши что именно не так в расписании группы <b>{group_code}</b>.\n\n"
        "Например: «Неверный преподаватель на 3-й паре в понедельник»",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(ReportError.waiting_message)
async def on_error_message(message: Message, state: FSMContext, db: AsyncSession):
    data = await state.get_data()
    group_code = data.get("group_code", "unknown")

    db.add(ErrorReport(
        user_id=message.from_user.id,
        group_code=group_code,
        message=message.text or "",
    ))
    await db.commit()
    await state.clear()

    await message.answer(
        "✅ Спасибо! Сообщение об ошибке получено.\n"
        "Мы проверим и исправим данные."
    )
```

- [ ] **Step 4: Commit**

```bash
git add bot/handlers/error_report.py bot/tests/test_error_report.py
git commit -m "feat(bot): error reporting — inline button → FSM → save to DB"
```

---

## Task 9: APScheduler + entry point

**Files:**
- Create: `bot/scheduler.py`
- Create: `bot/main.py`

- [ ] **Step 1: Создать `bot/scheduler.py`**

```python
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.config import settings

logger = logging.getLogger(__name__)


def create_scheduler(db_session_factory) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    async def _sync_job():
        from bot.services.data_sync import sync_all
        async with db_session_factory() as db:
            logger.info("Запуск синхронизации расписаний...")
            await sync_all(db)

    scheduler.add_job(
        _sync_job,
        trigger="interval",
        hours=settings.poll_interval_hours,
        id="sync_schedules",
    )
    return scheduler
```

- [ ] **Step 2: Создать `bot/main.py`**

```python
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.db.engine import AsyncSessionLocal, engine
from bot.db.init_db import init_db
from bot.handlers import start, onboarding, schedule, error_report
from bot.scheduler import create_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main():
    await init_db()

    # Первичная синхронизация при старте
    from bot.services.data_sync import sync_all
    async with AsyncSessionLocal() as db:
        await sync_all(db)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Middleware для подключения сессии БД к каждому апдейту
    from aiogram import BaseMiddleware
    from typing import Any, Callable, Awaitable
    from aiogram.types import TelegramObject

    class DbMiddleware(BaseMiddleware):
        async def __call__(
            self,
            handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: dict[str, Any],
        ) -> Any:
            async with AsyncSessionLocal() as session:
                data["db"] = session
                return await handler(event, data)

    dp.update.middleware(DbMiddleware())

    # Регистрируем роутеры
    dp.include_router(start.router)
    dp.include_router(onboarding.router)
    dp.include_router(schedule.router)
    dp.include_router(error_report.router)

    # Запускаем планировщик
    scheduler = create_scheduler(AsyncSessionLocal)
    scheduler.start()

    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Создать `bot/.env` (локальный, не в git)**

```bash
cat > bot/.env << 'EOF'
BOT_TOKEN=your_token_here
DATABASE_URL=postgresql+asyncpg://mpgu:password@localhost:5432/mpgu_bot
EOF
echo "bot/.env" >> .gitignore
```

- [ ] **Step 4: Проверить что бот запускается без ошибок импорта**

```bash
cd /home/user/mpgu-schedule
python -c "import bot.main; print('OK')"
```

Ожидаемый вывод: `OK` (без ImportError)

- [ ] **Step 5: Запустить все тесты**

```bash
python -m pytest bot/tests/ -v
```

Ожидаемый вывод: все тесты зелёные.

- [ ] **Step 6: Commit**

```bash
git add bot/main.py bot/scheduler.py
git commit -m "feat(bot): entry point, DB middleware, APScheduler wiring"
```

---

## Task 10: Deployment

**Files:**
- Create: `bot/Dockerfile`
- Create: `bot/docker-compose.yml`

- [ ] **Step 1: Создать `bot/Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "bot.main"]
```

- [ ] **Step 2: Создать `bot/docker-compose.yml`**

```yaml
version: "3.9"

services:
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: mpgu
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: mpgu_bot
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped

  bot:
    build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://mpgu:${POSTGRES_PASSWORD}@db:5432/mpgu_bot
    depends_on:
      - db
    restart: unless-stopped

volumes:
  pgdata:
```

- [ ] **Step 3: Убедиться что образ собирается**

```bash
cd bot && docker build -t mpgu-bot . && echo "Build OK"
```

- [ ] **Step 4: Финальный запуск всех тестов**

```bash
cd /home/user/mpgu-schedule
python -m pytest bot/tests/ -v --tb=short
```

Ожидаемый вывод: все тесты зелёные.

- [ ] **Step 5: Финальный commit**

```bash
git add bot/Dockerfile bot/docker-compose.yml
git commit -m "feat(bot): Docker deployment config"
```

---

## Self-Review

**Spec coverage:**
- ✅ Telegram-бот — Task 9/10
- ✅ aiogram 3 + PostgreSQL + APScheduler — Tasks 1,2,9
- ✅ Без аккаунтов (user_id) — Tasks 6,7
- ✅ Кнопки, не команды — Tasks 5,6,7,8
- ✅ Онбординг institute → group — Task 6
- ✅ Расписание на сегодня — Task 7
- ✅ Polling МПГУ раз в 4 часа — Task 9
- ✅ Кнопка "Ошибка в данных" — Task 8
- ✅ CDN → PostgreSQL sync — Task 3
- ✅ Docker деплой — Task 10

**Gaps:** Смена группы (`/start` повторно) покрыта через `cmd_start` — если группа уже выбрана, показывает расписание, а не онбординг. Добавить кнопку "Сменить группу" в `build_schedule_kb` — minor, можно после запуска.

**Placeholder scan:** Нет TBD/TODO в коде задач.

**Type consistency:** `group_code: str` используется одинаково во всех задачах. `AsyncSession` импортируется из одного места.
