"""Оркестратор: обход всех институтов, парсинг, сохранение данных."""
import asyncio
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

load_dotenv()

from scraper.fetchers.site_fetcher import fetch_schedule_links
from scraper.fetchers.file_fetcher import fetch_file, check_changed, save_to_temp
from scraper.parsers.excel_parser import ExcelParser
from scraper.parsers.gsheets_parser import GSheetsParser, gsheets_to_csv_url
from scraper.parsers.nextcloud_parser import NextcloudParser, nextcloud_download_url
from scraper.fetchers.site_fetcher import GDRIVE_FILE_PATTERN


def gdrive_to_download_url(url: str) -> str:
    m = GDRIVE_FILE_PATTERN.search(url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url
from scraper.parsers.docx_parser import DocxParser
from scraper.storage.git_storage import GitStorage
from scraper.utils.hash_tracker import HashTracker, md5_of_bytes

try:
    from scraper.parsers.pdf_parser import PDFParser
except ImportError as _pdf_import_err:
    print(f"⚠ PDF парсер недоступен: {_pdf_import_err}", file=sys.stderr)
    PDFParser = None  # type: ignore

CONFIG_PATH = Path(__file__).parent / "config" / "institutes.json"
DATA_PATH = os.environ.get("DATA_PATH", "./data")
CHANGED_ONLY = os.environ.get("CHANGED_ONLY", "true").lower() == "true"
INSTITUTE_FILTER = os.environ.get("INSTITUTE_ID")  # конкретный институт или все
SKIP_TEACHERS = os.environ.get("SKIP_TEACHERS", "false").lower() == "true"
TEACHERS_ONLY = os.environ.get("TEACHERS_ONLY", "false").lower() == "true"


def load_institutes() -> list[dict]:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    institutes = data["institutes"]
    if INSTITUTE_FILTER:
        institutes = [i for i in institutes if i["id"] == INSTITUTE_FILTER]
    return institutes


def get_parser(parser_type: str, config: dict):
    mapping = {
        "excel": ExcelParser,
        "gsheets": GSheetsParser,
        "nextcloud": NextcloudParser,
        "docx": DocxParser,
    }
    if PDFParser is not None:
        mapping["pdf"] = PDFParser
    cls = mapping.get(parser_type) or mapping.get("pdf")
    if cls is None:
        raise RuntimeError(f"Парсер для типа '{parser_type}' недоступен")
    return cls(config)


async def process_institute(
    session: aiohttp.ClientSession,
    institute: dict,
    tracker: HashTracker,
    storage: GitStorage,
) -> dict:
    inst_id = institute["id"]
    inst_name = institute["name"]
    print(f"\n▶ {inst_name} ({inst_id})")

    schedule_url = institute["schedule_url"]
    parser_type = institute.get("parser_type", "pdf")
    fallback_type = institute.get("fallback_parser_type")

    # Запоминаем прежнее количество групп для детектирования аномалий
    existing_before = storage.read_schedule(inst_id)
    prev_count = len(existing_before.get("groups", [])) if existing_before else 0

    try:
        links = await fetch_schedule_links(session, schedule_url)
        print(f"  Найдено ссылок: {len(links)}")
    except Exception as e:
        print(f"  Ошибка при получении ссылок: {e}")
        return _error_entry(inst_id, inst_name, str(e))

    for sub in institute.get("sub_faculties", []):
        try:
            sub_links = await fetch_schedule_links(session, sub["schedule_url"])
            links.extend(sub_links)
            print(f"  sub_faculty '{sub['name']}': {len(sub_links)} ссылок")
        except Exception as e:
            print(f"  sub_faculty '{sub['name']}' ошибка: {e}")

    min_year = institute.get("link_min_year")
    if min_year:
        before = len(links)
        links = [
            lnk for lnk in links
            if not re.findall(r'/(\d{4})/', lnk["url"])
            or any(int(y) >= min_year for y in re.findall(r'/(\d{4})/', lnk["url"]))
        ]
        print(f"  Фильтр по году ≥{min_year}: {len(links)} из {before} ссылок")

    # Дедупликация по URL (один и тот же файл может появиться из main + sub_faculty)
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for lnk in links:
        if lnk["url"] not in seen_urls:
            seen_urls.add(lnk["url"])
            deduped.append(lnk)
    if len(deduped) < len(links):
        print(f"  Дедупликация: {len(links) - len(deduped)} дублей убрано")
    links = deduped

    all_groups = []
    parser_used = parser_type
    file_hashes: dict[str, str] = {}

    for link in links:
        url = link["url"]
        link_type = link["type"]
        link_key = f"{inst_id}:{url}"

        # выбираем парсер под тип ссылки
        actual_type = link_type if link_type in {"pdf", "excel", "gsheets", "nextcloud", "docx"} else parser_type

        # Google Sheets — конвертируем URL и скачиваем CSV
        if actual_type == "gsheets":
            csv_url = gsheets_to_csv_url(url)
            try:
                content, md5 = await fetch_file(session, csv_url)
            except Exception as e:
                print(f"  ✗ gsheets {url}: {e}")
                continue
        elif actual_type == "nextcloud":
            dl_url = nextcloud_download_url(url)
            try:
                content, md5 = await fetch_file(session, dl_url)
            except Exception as e:
                print(f"  ✗ nextcloud {url}: {e}")
                continue
        elif actual_type == "pdf" and GDRIVE_FILE_PATTERN.search(url):
            dl_url = gdrive_to_download_url(url)
            try:
                content, md5 = await fetch_file(session, dl_url)
            except Exception as e:
                print(f"  ✗ gdrive {url}: {e}")
                continue
        else:
            try:
                content, md5 = await fetch_file(session, url)
            except Exception as e:
                print(f"  ✗ {url}: {e}")
                continue

        # пропускаем если не изменилось
        if CHANGED_ONLY and not tracker.has_changed(link_key, md5):
            print(f"  ↔ без изменений: {url[-60:]}")
            continue

        file_hashes[link_key] = md5

        # сохраняем во временный файл и парсим
        if actual_type == "pdf":
            ext = ".pdf"
        elif actual_type in {"excel"}:
            ext = ".xlsx"
        elif actual_type == "docx":
            ext = ".docx"
        else:
            ext = ".bin"  # nextcloud/gsheets — расширение определяется по содержимому
        tmp_path = save_to_temp(content, ext)

        try:
            parser = get_parser(actual_type, institute)
            result = await asyncio.to_thread(parser.parse, tmp_path)

            is_auth_error = any("авторизации" in w or "HTML" in w for w in result.warnings)
            if is_auth_error:
                # не обновляем хеш — нужно попробовать снова в следующий раз
                file_hashes.pop(link_key, None)
                print(f"  ✗ недоступен (HTML/авторизация): {url[-50:]}")
                for w in result.warnings:
                    print(f"    ⚠ {w}")
            else:
                print(f"  ✓ {result.parser_used} conf={result.confidence:.2f} "
                      f"групп={len(result.groups)} [{url[-50:]}]")
                all_groups.extend(result.groups)
                parser_used = result.parser_used
                if result.warnings:
                    for w in result.warnings:
                        print(f"    ⚠ {w}")
        except Exception as e:
            print(f"  ✗ Ошибка парсинга {url}: {e}")
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    # обновляем хеши
    for key, md5 in file_hashes.items():
        tracker.update(key, key.split(":", 1)[1], md5, 0, datetime.now(timezone.utc).isoformat())

    # Детектирование аномалий: файлы изменились, но результат подозрительный
    alerts = _detect_anomalies(inst_id, inst_name, all_groups, prev_count, file_hashes)
    for alert in alerts:
        print(f"  ⚠ АНОМАЛИЯ [{alert['type']}]: {alert['message']}")

    if not all_groups:
        existing = storage.read_schedule(inst_id)
        if existing and existing.get("groups"):
            print(f"  ↔ нет новых данных, используем кеш ({len(existing['groups'])} групп)")
            entry = {
                "id": inst_id,
                "name": inst_name,
                "short_name": institute.get("short_name", existing.get("short_name", "")),
                "campus": institute.get("campus"),
                "campus_address": institute.get("campus_address"),
                "groups_count": len(existing["groups"]),
                "updated_at": existing.get("updated_at", datetime.now(timezone.utc).isoformat()),
                "status": "ok",
                "parser_used": existing.get("parser_used", parser_type),
            }
            entry["alerts"] = alerts
            return entry
        err = _error_entry(inst_id, inst_name, "Группы не найдены")
        err["alerts"] = alerts
        return err

    all_groups = _filter_invalid_groups(all_groups)
    all_groups = _clean_lessons(all_groups)
    all_groups = _merge_duplicate_groups(all_groups)

    now = datetime.now(timezone.utc).isoformat()
    schedule_doc = {
        "institute_id": inst_id,
        "institute_name": inst_name,
        "short_name": institute.get("short_name", ""),
        "academic_year": _current_academic_year(),
        "updated_at": now,
        "parser_used": parser_used,
        "groups": all_groups,
    }
    storage.write_schedule(inst_id, schedule_doc)

    return {
        "id": inst_id,
        "name": inst_name,
        "short_name": institute.get("short_name", ""),
        "campus": institute.get("campus"),
        "campus_address": institute.get("campus_address"),
        "groups_count": len(all_groups),
        "updated_at": now,
        "status": "ok",
        "parser_used": parser_used,
        "alerts": alerts,
    }


async def main():
    institutes = load_institutes()
    storage = GitStorage(DATA_PATH)
    hashes_path = os.path.join(DATA_PATH, "meta", "hashes.json")
    tracker = HashTracker(hashes_path)

    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            process_institute(session, institute, tracker, storage)
            for institute in institutes
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    index_entries = []
    all_alerts = []
    for inst, result in zip(institutes, results):
        if isinstance(result, Exception):
            index_entries.append(_error_entry(inst["id"], inst["name"], str(result)))
        else:
            all_alerts.extend(result.pop("alerts", []))
            index_entries.append(result)

    tracker.save()
    storage.write_hashes(json.loads(Path(hashes_path).read_text()) if Path(hashes_path).exists() else {})

    # When running for a single institute, preserve the rest of the index
    if INSTITUTE_FILTER:
        existing = storage.read_index()
        if existing:
            merged = {e["id"]: e for e in existing.get("institutes", [])}
            for entry in index_entries:
                merged[entry["id"]] = entry
            index_entries = list(merged.values())

    storage.write_index({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "academic_year": _current_academic_year(),
        "institutes": index_entries,
    })

    # Пишем/удаляем файл аномалий
    alerts_path = Path(DATA_PATH) / "meta" / "alerts.json"
    if all_alerts:
        alerts_path.write_text(
            json.dumps(all_alerts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    elif alerts_path.exists():
        alerts_path.unlink()

    ok = sum(1 for e in index_entries if e.get("status") == "ok")
    print(f"\n{'='*50}")
    print(f"Готово: {ok}/{len(index_entries)} институтов обработано успешно")
    if all_alerts:
        print(f"⚠ Аномалий: {len(all_alerts)} — проверьте meta/alerts.json")

    # Build per-teacher schedule files if teacher DB exists (skip in matrix scrape jobs)
    teachers_db = Path(DATA_PATH) / "meta" / "teachers.json"
    if teachers_db.exists() and not SKIP_TEACHERS:
        print("\n[TEACHERS] Строим расписания преподавателей …")
        try:
            from scraper.build_teacher_schedules import build as build_teacher_schedules
            build_teacher_schedules(DATA_PATH)
        except Exception as e:
            print(f"  ⚠ Ошибка построения расписаний преподавателей: {e}")


def _current_academic_year() -> str:
    now = datetime.now()
    year = now.year if now.month >= 9 else now.year - 1
    return f"{year}-{year + 1}"


def _detect_anomalies(
    inst_id: str,
    inst_name: str,
    new_groups: list,
    prev_count: int,
    file_hashes: dict,
) -> list[dict]:
    """Возвращает список аномалий, если файлы изменились, но результат подозрительный."""
    alerts = []
    changed = len(file_hashes)
    if changed == 0:
        return alerts  # файлы не менялись — нечего проверять

    new_count = len(new_groups)

    if new_count == 0 and prev_count > 0:
        alerts.append({
            "type": "parser_broken",
            "severity": "high",
            "institute_id": inst_id,
            "institute_name": inst_name,
            "message": (
                f"После обновления {changed} файл(ов) парсер вернул 0 групп "
                f"(раньше было {prev_count}). Возможно, изменился формат."
            ),
            "prev_count": prev_count,
            "new_count": 0,
            "changed_files": changed,
        })
    elif new_count > 0 and prev_count >= 10 and new_count < prev_count * 0.4:
        alerts.append({
            "type": "groups_dropped",
            "severity": "medium",
            "institute_id": inst_id,
            "institute_name": inst_name,
            "message": (
                f"Количество групп резко сократилось: {prev_count} → {new_count} "
                f"после обновления {changed} файл(ов)."
            ),
            "prev_count": prev_count,
            "new_count": new_count,
            "changed_files": changed,
        })

    return alerts


_DAY_NAMES_RU = {
    "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
    "пн", "вт", "ср", "чт", "пт", "сб", "вс",
}

# Слова, с которых начинаются заголовки секций, а не коды групп
_SECTION_HEADER_STARTS = re.compile(
    r"^(курс|семестр|расписание|группы|форма|очная|заочная|очно|бакалавр|магистр|специалитет|"
    r"направление|направленность|история|государственный|педагогическое|современные|"
    r"аудитория|кафедра|институт|факультет|отделение)\b",
    re.IGNORECASE,
)

# Код специальности (44.03.01 и подобные) где угодно в строке
_SPECIALTY_CODE = re.compile(r"\d{2}\.\d{2}\.\d{2}")

# Фамилия преподавателя заглавными буквами (ГОРДЕЕВА, ИВАНОВ и т.п.)
_SURNAME_CAPS = re.compile(r"^[А-ЯЁ]{3,}\s*$")

# Пробел внутри кода группы: «БОЛ01 5-XXX» вместо «БОЛОУС-XXX»
_SPACE_IN_CODE = re.compile(r"^[А-ЯЁA-Z]{2,}\d+\s+\d")

# subject, который является числом или временем — не настоящий предмет
_NUMERIC_SUBJECT = re.compile(r"^\d+$")
_TIME_SUBJECT = re.compile(r"^\d{1,2}:\d{2}")
# time_start/time_end без ведущего нуля: '9:00' → нужно '09:00'
_SHORT_TIME = re.compile(r"^\d:\d{2}$")

# Паттерны для извлечения teacher+room из поля room, когда teacher пустой.
_TEACHER_TITLE_RE = re.compile(
    r"^(?:проф(?:ессор)?|доц(?:ент)?|зав\.?\s*каф(?:едрой)?|"
    r"ст\.?\s*(?:преп(?:\w*)?|пр\.?)|пр(?:еп(?:одаватель)?)?|"
    r"асс(?:ист(?:ент)?)?|ассист)\.?\s*",
    re.IGNORECASE,
)
# То же, но без якоря ^ — для поиска в середине строки
_TEACHER_TITLE_ANYWHERE_RE = re.compile(
    r"(?:проф(?:ессор)?|доц(?:ент)?|зав\.?\s*каф(?:едрой)?|"
    r"ст\.?\s*(?:преп(?:\w*)?|пр\.?)|пр(?:еп(?:одаватель)?)?|"
    r"асс(?:ист(?:ент)?)?|ассист)\.?\s+[А-ЯЁA-Z]",
    re.IGNORECASE,
)
# Суффиксы типа занятия "(ПЗ 18)", "(ЛК 36)", "п/г", "п\г" в конце строки
_LESSON_TYPE_SUFFIX_RE = re.compile(
    r"\s*\(?(?:[А-ЯЁ]{1,3}|ПЗ|ЛК|СЗ|ЛР|СМ)\s*\d*\)?\s*$", re.IGNORECASE
)
_TEACHER_NAME_TOK_RE = re.compile(
    r"[А-ЯЁA-Z][а-яёa-z]+|[А-ЯЁA-Z]\.[А-ЯЁA-Z]\.?|[А-ЯЁA-Z]\.",
    re.IGNORECASE,
)
# Слова, при которых нужно остановить поглощение имени (начало описания аудитории)
_ROOM_KWD_RE = re.compile(
    r"^(?:ауд|зал|корп(?:ус)?|каб(?:инет)?|ул(?:ица)?|дом|этаж|онлайн|дист)\b",
    re.IGNORECASE,
)
_AUD_NUM_RE = re.compile(r"ауд\.?\s*(\d[\w\-/]*(?:-\d+)?)", re.IGNORECASE)


def _extract_teacher_room(room_str: str) -> tuple[str, str | None] | None:
    """Если room содержит «ФИО + аудитория», возвращает (teacher, room) или None.

    Обрабатывает форматы:
    - «Доц. М.К. Чиняков(ауд. 58)»
    - «Ст.преп. С.В.Десятская (ауд. 637)»
    - «доц. К.Ю. Машков (спортивный зал)»
    - «ассист. Артемов Д.Ю., ауд. 405»
    - «проф. Елена Игоревна Корзинова, (Краснодарская улица, дом 59, ауд. 109)»
    """
    s = room_str.strip()
    pos = 0

    # 1. Consume optional title (ст.преп., доц., etc.)
    m_title = _TEACHER_TITLE_RE.match(s, pos)
    if m_title:
        pos = m_title.end()

    # 2. Consume name tokens; allow no space between initials and surname
    #    (handles «С.В.Десятская»). Stop at room keywords (ауд, зал, корп…).
    name_start = pos
    tok = _TEACHER_NAME_TOK_RE.match(s, pos)
    if not tok:
        return None  # no name token → not a teacher pattern
    pos = tok.end()

    while pos < len(s):
        ws = re.match(r"\s*", s[pos:])
        npos = pos + (ws.end() if ws else 0)
        if _ROOM_KWD_RE.match(s[npos:]):
            break
        tok2 = _TEACHER_NAME_TOK_RE.match(s, npos)
        if not tok2:
            break
        pos = tok2.end()

    teacher_raw = s[name_start:pos].strip().rstrip(",").strip()

    # Validate: teacher string must contain Cyrillic
    if not re.search(r"[А-ЯЁа-яё]", teacher_raw):
        return None

    # Must have title OR initials OR multiple tokens — reject single bare words like «ауд»
    has_title = m_title is not None
    has_initials = bool(re.search(r"[А-ЯЁA-Z]\.[А-ЯЁA-Z]", teacher_raw))
    multi_token = bool(re.search(r"\s", teacher_raw) or re.search(r"\.", teacher_raw))
    if not (has_title or has_initials or multi_token):
        return None

    # Prepend title
    if name_start > 0:
        teacher_raw = s[:name_start].strip().rstrip(".").strip() + ". " + teacher_raw

    rest = s[pos:].strip().lstrip(",").strip()

    if not rest:
        # Just a teacher name with no room
        if has_title or has_initials:
            return (teacher_raw, None)
        return None

    # Pattern A: "(room_content)" — parens form
    m_paren = re.match(r"^\(([^)]+)\)", rest)
    if m_paren:
        room_content = m_paren.group(1).strip()
        m_aud = _AUD_NUM_RE.search(room_content)
        if m_aud:
            return (teacher_raw, m_aud.group(1).strip())
        return (teacher_raw, room_content)

    # Pattern B: "ауд. NNN" directly
    m_aud = re.match(r"^ауд\.?\s*(\d[\w\-/]*)", rest, re.IGNORECASE)
    if m_aud:
        return (teacher_raw, m_aud.group(1).strip())

    # Pattern C: rest is a short room label with no Cyrillic surname words
    if len(rest) < 60 and not re.search(r"[А-ЯЁ][а-яё]{3,}", rest):
        return (teacher_raw, rest.rstrip(".").strip() if rest else None)

    return None


def _filter_invalid_groups(groups: list[dict]) -> list[dict]:
    """Отфильтровывает группы с явно невалидными именами."""
    result = []
    for g in groups:
        name = g["name"].strip()
        reason = None
        if name.lower() in _DAY_NAMES_RU:
            reason = "день недели"
        elif len(name) < 4:
            reason = "слишком короткое"
        elif name.replace(".", "").replace(" ", "").isdigit():
            reason = "только цифры"
        elif _SPECIALTY_CODE.search(name):
            reason = "код специальности"
        elif len(name) > 60:
            reason = "слишком длинное"
        elif _SECTION_HEADER_STARTS.match(name):
            reason = "заголовок секции"
        elif _SURNAME_CAPS.match(name):
            reason = "фамилия заглавными"
        elif _SPACE_IN_CODE.match(name):
            reason = "пробел в коде"
        if reason:
            print(f"  ✗ фильтр [{reason}]: {name!r}")
            continue
        result.append(g)
    return result


def _clean_lesson(lesson: dict) -> dict | None:
    """Очищает поля одного занятия. Возвращает None если занятие нужно выбросить."""
    subj = (lesson.get("subject") or "").strip()

    # Числовой subject или одиночный символ — мусор (разделитель строки, номер ауд.)
    if not subj or _NUMERIC_SUBJECT.match(subj) or len(subj) < 3:
        return None

    # subject — это время ('09:00', '09:00-10:30') — мусор
    if _TIME_SUBJECT.match(subj):
        return None

    # Исправляем '9:00' → '09:00'
    for field in ("time_start", "time_end"):
        t = lesson.get(field) or ""
        if _SHORT_TIME.match(t):
            lesson[field] = "0" + t

    # Разбиваем room = "Иванов И.И. (ауд.301)" → teacher + room
    room = (lesson.get("room") or "").strip()
    teacher = (lesson.get("teacher") or "").strip()
    if not teacher:
        # Case 1: room starts with teacher info
        if room:
            result = _extract_teacher_room(room)
            if result is not None:
                lesson["teacher"] = result[0]
                lesson["room"] = result[1]

        # Case 2: subject == room — AI put full "SUBJECT TEACHER ROOM" in both fields
        room2 = (lesson.get("room") or "").strip()
        if not lesson.get("teacher") and subj and room2 and subj == room2:
            m_title = _TEACHER_TITLE_ANYWHERE_RE.search(subj)
            if m_title and m_title.start() > 4:
                clean_subj = subj[:m_title.start()].strip().rstrip(",").strip()
                clean_subj = _LESSON_TYPE_SUFFIX_RE.sub("", clean_subj).strip()
                teacher_room_str = subj[m_title.start():]
                tres = _extract_teacher_room(teacher_room_str)
                if tres and clean_subj:
                    lesson["subject"] = clean_subj
                    lesson["teacher"] = tres[0]
                    lesson["room"] = tres[1]

    return lesson


def _clean_lessons(groups: list[dict]) -> list[dict]:
    """Применяет _clean_lesson ко всем занятиям всех групп."""
    for group in groups:
        for week in ("odd_week", "even_week"):
            for day in list(group["schedule"][week].keys()):
                cleaned = []
                for lesson in group["schedule"][week][day]:
                    result = _clean_lesson(lesson)
                    if result is not None:
                        cleaned.append(result)
                group["schedule"][week][day] = cleaned
    return groups


def _merge_duplicate_groups(groups: list[dict]) -> list[dict]:
    """Объединяет расписания групп с одинаковым именем из разных файлов.

    Если одна и та же группа встречается в нескольких PDF/DOCX,
    уроки объединяются (без дублей по time_start + subject).
    """
    merged: dict[str, dict] = {}
    for g in groups:
        name = g["name"]
        if name not in merged:
            merged[name] = g
            continue
        existing = merged[name]
        for week in ("odd_week", "even_week"):
            for day, lessons in g["schedule"][week].items():
                target = existing["schedule"][week][day]
                seen = {(l["time_start"], l["subject"]) for l in target}
                for lesson in lessons:
                    key = (lesson["time_start"], lesson["subject"])
                    if key not in seen:
                        target.append(lesson)
                        seen.add(key)
    return list(merged.values())


def _error_entry(inst_id, inst_name, error):
    return {
        "id": inst_id,
        "name": inst_name,
        "groups_count": 0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "error",
        "error": error,
        "alerts": [],
    }


_BAD_TEACHER_PREFIXES = re.compile(
    r"^\s*[\(\[]|"          # starts with ( or [
    r"^\s*(лк|пз|лаб|ауд|каб|каф|зал)\b",  # room/type prefixes
    re.IGNORECASE,
)


def _is_valid_teacher_name(name: str) -> bool:
    if len(name) > 70:
        return False
    if _BAD_TEACHER_PREFIXES.search(name):
        return False
    # must have at least one Cyrillic letter
    if not re.search(r"[а-яёА-ЯЁ]", name):
        return False
    return True


def _build_teacher_index(storage) -> None:
    """Строит meta/teachers.json — индекс всех преподавателей по всем институтам."""
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config_by_id = {i["id"]: i for i in config["institutes"]}

    teachers: dict[str, list] = {}

    sched_root = Path(DATA_PATH) / "institutes"
    for inst_dir in sorted(sched_root.iterdir()):
        sched_path = inst_dir / "schedule.json"
        if not sched_path.exists():
            continue
        try:
            data = json.loads(sched_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        inst_id = data.get("institute_id", inst_dir.name)
        cfg = config_by_id.get(inst_id, {})
        inst_short = data.get("short_name") or cfg.get("short_name", inst_id)

        groups_dir = inst_dir / "groups"
        for group_meta in data.get("groups", []):
            group_name = group_meta.get("name", "")
            group_file = group_meta.get("file", "")

            # Новый формат: расписание в отдельном файле groups/{file}.json
            group_data: dict = {}
            if group_file and groups_dir.exists():
                gpath = groups_dir / f"{group_file}.json"
                if gpath.exists():
                    try:
                        group_data = json.loads(gpath.read_text(encoding="utf-8"))
                    except Exception:
                        pass
            # Старый формат: расписание встроено в запись манифеста
            if not group_data.get("schedule"):
                group_data = group_meta

            for week in ("odd_week", "even_week"):
                for day, lessons in group_data.get("schedule", {}).get(week, {}).items():
                    for lesson in lessons:
                        teacher = lesson.get("teacher")
                        if not teacher or not teacher.strip():
                            continue
                        teacher = teacher.strip()
                        if not _is_valid_teacher_name(teacher):
                            continue
                        entry = {
                            "ii": inst_id,
                            "is": inst_short,
                            "g": group_name,
                            "w": week,
                            "d": day,
                            "sl": lesson.get("slot"),
                            "ts": lesson.get("time_start"),
                            "te": lesson.get("time_end"),
                            "s": lesson.get("subject", ""),
                            "t": lesson.get("type", "other"),
                            "r": lesson.get("room"),
                            "sg": lesson.get("subgroup"),
                        }
                        if teacher not in teachers:
                            teachers[teacher] = []
                        teachers[teacher].append(entry)

    teacher_list = [
        {"name": name, "lessons": lessons}
        for name, lessons in sorted(teachers.items())
    ]

    out_path = Path(DATA_PATH) / "meta" / "teachers.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {"generated_at": datetime.now(timezone.utc).isoformat(), "teachers": teacher_list},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"  Индекс преподавателей: {len(teacher_list)} чел.")


def _entry():
    if TEACHERS_ONLY:
        teachers_db = Path(DATA_PATH) / "meta" / "teachers.json"
        if not teachers_db.exists():
            print("[SKIP] teachers.json not found — run build_teachers first")
            return
        print("[TEACHERS_ONLY] Rebuilding per-teacher schedule files …")
        from scraper.build_teacher_schedules import build as build_teacher_schedules
        build_teacher_schedules(DATA_PATH)
        return
    asyncio.run(main())


if __name__ == "__main__":
    _entry()
