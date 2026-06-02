"""PDF парсер с четырьмя уровнями: pdfplumber → camelot → Tesseract OCR → Claude vision."""
import os
import re
from pathlib import Path

import pdfplumber

from scraper.parsers.base import BaseParser, ParseResult
from scraper.normalizer.schedule_normalizer import (
    normalize_day, normalize_lesson_type, normalize_time,
    normalize_week_type, make_schedule_skeleton, lesson_obj, TIME_SLOTS,
    extract_subgroup,
)

CONFIDENCE_THRESHOLD = 0.65


class PDFParser(BaseParser):
    def parse(self, source: str | bytes) -> ParseResult:
        path = source if isinstance(source, str) else _bytes_to_tmp(source, ".pdf")
        accumulated_warnings = []

        result = self._try_pdfplumber(path)
        if result.confidence >= CONFIDENCE_THRESHOLD:
            return result
        # Принимаем разреженные расписания с реальными кодами групп (напр. магистратура)
        if result.groups and all(g["name"] != "группа" for g in result.groups):
            total = sum(
                sum(len(d) for d in g["schedule"]["odd_week"].values()) +
                sum(len(d) for d in g["schedule"]["even_week"].values())
                for g in result.groups
            )
            if total > 0:
                return result
        is_image_based = any("image-based" in w for w in result.warnings)
        accumulated_warnings.extend(result.warnings)

        if not is_image_based:
            result = self._try_camelot(path)
            if result.confidence >= CONFIDENCE_THRESHOLD:
                return result
            accumulated_warnings.extend(result.warnings)

        # Уровень 3: Tesseract OCR (бесплатно, работает офлайн)
        result = self._try_tesseract(path)
        if result.confidence >= CONFIDENCE_THRESHOLD:
            result.warnings = accumulated_warnings + result.warnings
            return result
        if result.groups:
            # Принимаем разреженный результат от Tesseract
            accumulated_warnings.extend(result.warnings)
            result.warnings = accumulated_warnings
            return result
        accumulated_warnings.extend(result.warnings)

        # Уровень 4: Gemini vision
        result = self._try_gemini(path)
        if result.confidence >= CONFIDENCE_THRESHOLD or (result.groups and not any(
            "провалился" in w for w in result.warnings
        )):
            result.warnings = accumulated_warnings + result.warnings
            return result
        accumulated_warnings.extend(result.warnings)

        # Уровень 5: Claude vision
        result = self._try_claude(path)
        result.warnings = accumulated_warnings + result.warnings
        return result

    # ── уровень 1: pdfplumber ─────────────────────────────────────────────────

    def _try_pdfplumber(self, path: str) -> ParseResult:
        try:
            with pdfplumber.open(path) as pdf:
                # Detect image-based PDFs: sample first 3 pages for extractable text
                sample = ""
                for page in pdf.pages[:3]:
                    sample += page.extract_text() or ""
                    if len(sample) > 100:
                        break
                if len(sample) < 50:
                    return ParseResult(groups=[], parser_used="pdfplumber", confidence=0.0,
                                       warnings=["image-based PDF"])

                all_tables = []
                for page in pdf.pages:
                    tables = page.extract_tables({
                        "vertical_strategy": "lines",
                        "horizontal_strategy": "lines",
                        "intersection_tolerance": 5,
                    })
                    all_tables.extend(tables or [])

                if not all_tables:
                    return ParseResult(groups=[], parser_used="pdfplumber", confidence=0.0,
                                       warnings=["Таблицы не найдены"])

                groups = _parse_tables(all_tables)
                confidence = _compute_confidence(groups)
                return ParseResult(groups=groups, parser_used="pdfplumber", confidence=confidence)
        except Exception as e:
            return ParseResult(groups=[], parser_used="pdfplumber", confidence=0.0,
                               warnings=[str(e)])

    # ── уровень 2: camelot ────────────────────────────────────────────────────

    def _try_camelot(self, path: str) -> ParseResult:
        try:
            import camelot
            tables = camelot.read_pdf(path, pages="all", flavor="lattice")
            if not tables or len(tables) == 0:
                tables = camelot.read_pdf(path, pages="all", flavor="stream")

            raw_tables = [t.df.values.tolist() for t in tables]
            groups = _parse_tables(raw_tables)
            confidence = _compute_confidence(groups)
            return ParseResult(groups=groups, parser_used="camelot", confidence=confidence)
        except Exception as e:
            return ParseResult(groups=[], parser_used="camelot", confidence=0.0,
                               warnings=[str(e)])

    # ── уровень 3: Tesseract OCR ──────────────────────────────────────────────

    def _try_tesseract(self, path: str) -> ParseResult:
        try:
            from pdf2image import convert_from_path
            import pytesseract  # noqa: F401 — проверка доступности

            images = convert_from_path(path, dpi=300, fmt="jpeg")
            all_tables: list[list[list]] = []
            for img in images:
                tables = _ocr_image_to_tables(img)
                all_tables.extend(tables)

            if not all_tables:
                return ParseResult(groups=[], parser_used="tesseract", confidence=0.0,
                                   warnings=["Tesseract: таблицы не найдены"])

            groups = _parse_tables(all_tables)

            # Если дни не распознаны (вертикальный текст в MPGU-формате) —
            # выводим дни из повторений временных слотов и парсим повторно.
            if _is_day_distribution_skewed(groups):
                fixed = _inject_days_from_time_sequence(all_tables)
                groups = _parse_tables(fixed)

            if not groups:
                return ParseResult(groups=[], parser_used="tesseract", confidence=0.0,
                                   warnings=["Tesseract: не удалось извлечь расписание"])

            confidence = _compute_confidence(groups)
            return ParseResult(groups=groups, parser_used="tesseract", confidence=confidence)
        except Exception as e:
            return ParseResult(groups=[], parser_used="tesseract", confidence=0.0,
                               warnings=[f"Tesseract fallback провалился: {e}"])

    # ── уровень 4: Gemini vision ──────────────────────────────────────────────

    def _try_gemini(self, path: str) -> ParseResult:
        try:
            from scraper.utils.gemini_client import GeminiClient
            client = GeminiClient()
            raw = client.parse_pdf(path)
            groups = raw.get("groups", [])
            confidence = 0.85 if groups else 0.0
            return ParseResult(groups=groups, parser_used="gemini", confidence=confidence,
                               warnings=["Использован Gemini fallback"])
        except Exception as e:
            return ParseResult(groups=[], parser_used="gemini", confidence=0.0,
                               warnings=[f"Gemini fallback провалился: {e}"])

    # ── уровень 4: Claude vision ──────────────────────────────────────────────

    def _try_claude(self, path: str) -> ParseResult:
        try:
            from scraper.utils.claude_client import ClaudeClient
            client = ClaudeClient()
            raw = client.parse_pdf_pages(path)
            groups = raw.get("groups", [])
            confidence = 0.85 if groups else 0.0
            return ParseResult(groups=groups, parser_used="claude", confidence=confidence,
                               warnings=["Использован Claude vision fallback"])
        except Exception as e:
            return ParseResult(groups=[], parser_used="claude", confidence=0.0,
                               warnings=[f"Claude fallback провалился: {e}"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _ocr_image_to_tables(img) -> list[list[list[str]]]:
    """Конвертирует PIL-изображение в список таблиц через OpenCV + Tesseract.

    Алгоритм:
    1. OpenCV морфология → находим горизонтальные и вертикальные линии таблицы
    2. Проецируем линии → получаем координаты строк и столбцов (с фильтром шума)
    3. OCR каждой ячейки индивидуально (--psm 6)
    4. Для ячеек первого столбца, у которых height >> width (вертикальный текст),
       дополнительно пробуем поворот на 90° — это читает слова вида «Понедельник»
       написанные вертикально в merged-ячейках MPGU-расписаний
    """
    import cv2
    import numpy as np
    import pytesseract

    img_np = np.array(img.convert("RGB"))
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h_img, w_img = bw.shape

    # ── детекция линий ────────────────────────────────────────────────────────
    h_kern = cv2.getStructuringElement(cv2.MORPH_RECT, (w_img // 15, 1))
    v_kern = cv2.getStructuringElement(cv2.MORPH_RECT, (1, h_img // 20))
    h_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, h_kern, iterations=2)
    v_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, v_kern, iterations=2)

    row_ys = _merge_close_coords(_projection_peaks(h_lines.sum(axis=1)), min_gap=25)
    col_xs = _merge_close_coords(_projection_peaks(v_lines.sum(axis=0)), min_gap=25)

    if len(row_ys) < 3 or len(col_xs) < 2:
        return []

    # ── OCR каждой ячейки ────────────────────────────────────────────────────
    n_rows = len(row_ys) - 1
    n_cols = len(col_xs) - 1
    table: list[list[str]] = [[""] * n_cols for _ in range(n_rows)]

    for ri in range(n_rows):
        y1, y2 = row_ys[ri] + 2, row_ys[ri + 1] - 2
        if y2 <= y1 + 4:
            continue
        for ci in range(n_cols):
            x1, x2 = col_xs[ci] + 2, col_xs[ci + 1] - 2
            if x2 <= x1 + 4:
                continue
            cell_img = gray[y1:y2, x1:x2]

            cell_h, cell_w = cell_img.shape
            text = _ocr_cell(cell_img)

            # Для первого столбца с высокими узкими ячейками — пробуем поворот
            # (вертикальный текст «Понедельник», «Вторник» в MPGU-таблицах)
            if ci == 0 and cell_h > cell_w * 1.5 and not text.strip():
                rotated = cv2.rotate(cell_img, cv2.ROTATE_90_COUNTERCLOCKWISE)
                text_rot = _ocr_cell(rotated)
                if text_rot.strip():
                    text = text_rot

            table[ri][ci] = text.strip()

    # Убираем полностью пустые строки
    table = [row for row in table if any(c.strip() for c in row)]
    if len(table) < 3:
        return []
    return [table]


def _ocr_cell(cell_img) -> str:
    """OCR одной ячейки с лёгкой предобработкой."""
    import cv2
    import numpy as np
    import pytesseract

    if cell_img.size == 0:
        return ""
    # Увеличиваем маленькие ячейки для лучшего OCR
    h, w = cell_img.shape[:2]
    if h < 40 or w < 40:
        scale = max(40 / h, 40 / w, 1.0)
        cell_img = cv2.resize(cell_img, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_CUBIC)
    # Адаптивная бинаризация улучшает читаемость при неравномерном освещении
    cell_bin = cv2.adaptiveThreshold(
        cell_img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2,
    )
    text = pytesseract.image_to_string(
        cell_bin, lang="rus+eng",
        config="--psm 6 --oem 1",
    )
    return text.replace("\n", " ").strip()


def _projection_peaks(proj, min_val: int = 3000) -> list[int]:
    """Возвращает координаты центров «пиков» на проекции (суммарный сигнал линий)."""
    coords = []
    in_peak = False
    start = 0
    for i, v in enumerate(proj):
        if v > min_val and not in_peak:
            in_peak = True
            start = i
        elif v <= min_val and in_peak:
            in_peak = False
            coords.append((start + i) // 2)
    if in_peak:
        coords.append((start + len(proj)) // 2)
    return coords


def _merge_close_coords(coords: list[int], min_gap: int) -> list[int]:
    """Сливает координаты линий, которые ближе min_gap друг к другу."""
    if not coords:
        return []
    merged = [coords[0]]
    for c in coords[1:]:
        if c - merged[-1] < min_gap:
            merged[-1] = (merged[-1] + c) // 2
        else:
            merged.append(c)
    return merged


_OCR_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]


def _inject_days_from_time_sequence(tables: list[list[list[str]]]) -> list[list[list[str]]]:
    """Заполняет столбец дней, используя повторения временных слотов.

    В MPGU-расписании каждый день начинается с тех же временных слотов
    (09:00-10:30, 10:40-12:10, ...). Когда одно и то же время встречается
    повторно — значит, началась следующий день.

    Это позволяет обходиться без OCR вертикального текста в столбце дней.
    """
    fixed = []
    for table in tables:
        if len(table) < 3:
            fixed.append(table)
            continue

        # Ищем столбец со временем (содержит больше всего валидных временных строк)
        time_col = _find_time_col(table)
        if time_col is None:
            fixed.append(table)
            continue

        # Заполняем столбец 0 именами дней на основе повторений времени
        seen_times: set[str] = set()
        day_idx = 0
        new_table = [row[:] for row in table]

        for ri, row in enumerate(new_table):
            cell = str(row[time_col]).strip() if time_col < len(row) else ""
            t = normalize_time(cell)
            if not t:
                continue
            time_key = t[0]  # "09:00"

            if time_key in seen_times:
                # Временной слот повторяется — перешли к следующему дню
                day_idx = min(day_idx + 1, len(_OCR_DAYS) - 1)
                seen_times = {time_key}
            else:
                seen_times.add(time_key)

            # Записываем день в первый столбец если он пустой или нечитаемый
            if len(new_table[ri]) > 0:
                existing = normalize_day(str(new_table[ri][0]))
                if not existing:
                    new_table[ri][0] = _OCR_DAYS[day_idx]

        fixed.append(new_table)
    return fixed


def _find_time_col(table: list[list[str]]) -> int | None:
    """Возвращает индекс столбца с наибольшим количеством временных значений."""
    if not table:
        return None
    n_cols = max(len(row) for row in table)
    best_col, best_count = None, 0
    for ci in range(min(n_cols, 4)):  # время обычно в первых 4 столбцах
        count = sum(1 for row in table if ci < len(row) and normalize_time(str(row[ci])))
        if count > best_count:
            best_count, best_col = count, ci
    return best_col if best_count >= 2 else None


def _is_day_distribution_skewed(groups: list[dict], threshold: float = 0.6) -> bool:
    """True если >threshold занятий приходится на один день (артефакт OCR)."""
    day_counts: dict[str, int] = {}
    for g in groups:
        for week in ("odd_week", "even_week"):
            for day, lessons in g["schedule"][week].items():
                day_counts[day] = day_counts.get(day, 0) + len(lessons)
    total = sum(day_counts.values())
    if total < 4:
        return False
    return max(day_counts.values()) / total > threshold


def _bytes_to_tmp(data: bytes, ext: str) -> str:
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=ext)
    os.write(fd, data)
    os.close(fd)
    return path


def _parse_tables(tables: list[list[list]]) -> list[dict]:
    """Определяет формат таблицы и парсит группы."""
    valid = [t for t in tables if t and len(t) >= 2]

    # Normalize journalism-style tables (time in col>1) to standard layout.
    # Once a time_col is found in any table, apply it to all tables with the same
    # column count (continuation pages share the same physical column layout).
    journ_tc: dict[int, int] = {}  # ncols → time_col
    for t in valid:
        ncols = len(t[0]) if t else 0
        if ncols not in journ_tc:
            tc = _find_journalism_time_col(t)
            if tc is not None:
                journ_tc[ncols] = tc
    normalized = []
    for t in valid:
        ncols = len(t[0]) if t else 0
        tc = journ_tc.get(ncols)
        normalized.append(_normalize_journalism_table(t, tc) if tc is not None else t)
    valid = normalized

    if any(_is_mpgu_timetable_format(t) for t in valid):
        return _parse_mpgu_timetable_pages(valid)

    groups = []
    for table in valid:
        header = [str(c or "").strip().lower() for c in table[0]]
        if _is_day_column_format(header):
            groups.extend(_parse_day_columns(table))
        elif _is_day_row_format(header):
            groups.extend(_parse_day_rows(table))
        else:
            groups.extend(_parse_heuristic(table))
    return groups


_SKIP_CELLS = {"День самоподготовки", "—", "-", "–"}

# Код группы МПГУ (с возможными пробелами вокруг дефиса), для сегментации страниц
_GROUP_CODE_RE = re.compile(r"[А-ЯЁа-яёA-Za-z]{2,6}\d{2}\s*-\s*[А-ЯЁа-яёA-Za-z]{2,6}\d{4}")


def _try_parse_time_cell(c1: str) -> tuple[str, str] | None:
    """Extracts (HH:MM, HH:MM) from a time cell string, trying multiple formats."""
    # Format: HH:MM or HH.MM with newline/dash separator (e.g. '09:15\n-\n10:50', '09.00-\n10.30')
    m = re.search(r"(\d{1,2}[:.]\d{2})\s*[-–\n]+\s*(\d{1,2}[:.]\d{2})", c1, re.DOTALL)
    if m:
        t1, t2 = _norm_hm(m.group(1)), _norm_hm(m.group(2))
        if _valid_time(t1) and _valid_time(t2) and t1 < t2:
            return t1, t2
    # Format: 4-digit HHMM direct (e.g. '0900-1030')
    m = re.search(r"(\d{4})\D+(\d{4})", c1)
    if m:
        t1, t2 = _fmt_time(m.group(1)), _fmt_time(m.group(2))
        if _valid_time(t1) and _valid_time(t2) and t1 < t2:
            return t1, t2
    # Format: 4-digit reversed (e.g. '0301-0090' = '0900-1030' reversed)
    m = re.search(r"(\d{4})\D+(\d{4})", c1[::-1])
    if m:
        t1, t2 = _fmt_time(m.group(1)), _fmt_time(m.group(2))
        if _valid_time(t1) and _valid_time(t2) and t1 < t2:
            return t1, t2
    # Fallback: two HH:MM patterns with up to 25 non-digit chars between (mixed content)
    m = re.search(r"(\d{1,2}[:.]\d{2})\D{0,25}?(\d{1,2}[:.]\d{2})", c1, re.DOTALL)
    if m:
        t1, t2 = _norm_hm(m.group(1)), _norm_hm(m.group(2))
        if _valid_time(t1) and _valid_time(t2) and t1 < t2:
            return t1, t2
    return None


def _norm_hm(s: str) -> str:
    """'9.15' or '9:15' → '09:15'"""
    s = s.replace(".", ":")
    parts = s.split(":")
    if len(parts) == 2:
        try:
            return f"{int(parts[0]):02d}:{parts[1]}"
        except ValueError:
            pass
    return s


def _valid_time(t: str) -> bool:
    try:
        h, m = map(int, t.split(":"))
        return 7 <= h <= 22 and 0 <= m <= 59
    except Exception:
        return False


def _find_journalism_time_col(table: list[list]) -> int | None:
    """Detects journalism-style format: 'Время' header in col>=2, day names in col0."""
    if not table or len(table[0]) < 5:
        return None
    time_col = None
    for row in table[:15]:
        for ci, cell in enumerate(row):
            if ci >= 2 and "время" in str(cell or "").strip().lower():
                time_col = ci
                break
        if time_col is not None:
            break
    if time_col is None:
        return None
    # Verify col0 has recognizable day names in data rows
    for row in table:
        raw = str(row[0] or "").replace("\n", "").strip()
        if len(raw) > 4 and (normalize_day(raw.lower()) or
                             normalize_day("".join(reversed(raw)).lower())):
            return time_col
    return None


def _normalize_journalism_table(table: list[list], time_col: int) -> list[list]:
    """Normalize: keep col0 (day), then time_col onwards, dropping empty filler cols."""
    return [[row[0]] + list(row[time_col:]) for row in table]


def _is_mpgu_timetable_format(table: list[list]) -> bool:
    """Формат МПГУ: колонка 0 = день, колонка 1 = время, колонка 2+ = занятие."""
    if len(table) < 3 or not table[0] or len(table[0]) < 3:
        return False
    # Явный заголовок "День\nнедели" в одной ячейке (форматы 1a и 3)
    for row in table[:8]:
        c0 = str(row[0] or "").strip().lower()
        c1 = str(row[1] or "").strip().lower()
        if "день" in c0 and "недели" in c0:
            return True
        if "группа" in c1 and "время" in c1:
            return True
    # Продолжение (нет заголовка): col0 содержит буквы дня, col1 — время
    has_day_letter = False
    has_time = False
    for row in table:
        c0 = str(row[0] or "").strip()
        c1 = str(row[1] or "").strip() if len(row) > 1 else ""
        raw = c0.replace("\n", "").strip()
        chars = [ch for ch in c0.split("\n") if ch.strip()]
        if chars and all(len(ch.strip()) == 1 for ch in chars):
            has_day_letter = True
        elif len(raw) > 4 and (normalize_day(raw.lower()) or
                               normalize_day("".join(reversed(raw)).lower())):
            has_day_letter = True
        if re.search(r"\d{4}", c1) or re.search(r"\d{1,2}[:.]\d{2}", c1):
            has_time = True
        if has_day_letter and has_time:
            return True
    return False


def _parse_mpgu_timetable_pages(tables: list[list[list]]) -> list[dict]:
    """Объединяет несколько таблиц одного PDF, возвращает список групп.

    Поддерживает:
    - Один PDF = одна группа (Format 1a: перевёрнутое название дня)
    - Один PDF = несколько групп (Format 3: прямое название дня, несколько колонок-групп)
    - Продолжение страниц без заголовка (Format 2: буквы по одной в отдельных строках)
    - Несколько групп-сеток в одном PDF: каждая страница со СВОИМИ кодами групп
      (напр. «1 курс»/«2 курс» на разных страницах) — отдельный сегмент.
    """
    if not tables:
        return []

    # Разбиваем таблицы на сегменты: новый сегмент начинается там, где у таблицы
    # есть собственные коды групп (а не унаследованные от предыдущей страницы).
    # «Продолжения» (Format 2, без кодов) приклеиваются к текущему сегменту.
    segments: list[list[list]] = []
    for t in tables:
        gc, _, _, _ = _extract_timetable_groups(t)
        has_own_codes = gc != [("группа", 2)] and any(
            _GROUP_CODE_RE.search(name) for name, _ in gc
        )
        if has_own_codes or not segments:
            segments.append([t])
        else:
            segments[-1].append(t)

    if len(segments) > 1:
        result: list[dict] = []
        for seg in segments:
            result.extend(_parse_mpgu_segment(seg, all_tables=tables))
        return result
    return _parse_mpgu_segment(tables, all_tables=tables)


def _parse_mpgu_segment(tables: list[list[list]], all_tables: list[list[list]]) -> list[dict]:
    """Парсит один сегмент (одна группа-сетка + её продолжения)."""
    if not tables:
        return []

    # Извлекаем группы из первой МПГУ-таблицы (может быть не tables[0])
    first_mpgu = next((t for t in tables if _is_mpgu_timetable_format(t)), tables[0])
    group_cols, form, degree, year = _extract_timetable_groups(first_mpgu)

    # Если МПГУ-таблица не содержит кодов групп, ищем в таблицах до неё:
    # в некоторых форматах заголовок с кодами групп предшествует данным,
    # но не проходит _is_mpgu_timetable_format (пустой col 0 или время в col 3+).
    if group_cols == [("группа", 2)]:
        first_mpgu_idx = next((i for i, t in enumerate(tables) if t is first_mpgu), len(tables))
        for candidate in tables[:first_mpgu_idx]:
            gc0, f0, d0, y0 = _extract_timetable_groups(candidate)
            if gc0 != [("группа", 2)]:
                group_cols, form, degree, year = gc0, f0, d0, y0
                # Перемапируем индексы колонок: в таблицах данных группы начинаются с col 2
                min_col = min(col for _, col in group_cols)
                if min_col > 2:
                    col_offset = min_col - 2
                    group_cols = [(name, col - col_offset) for name, col in group_cols]
                break

    # group_cols: list of (name, col_idx)

    schedules: dict[str, dict] = {name: make_schedule_skeleton() for name, _ in group_cols}
    # Range-based mapping: cols between group N and group N+1 belong to group N
    max_col = max((len(row) for t in tables for row in t if row), default=20)
    col_to_group: dict[int, str] = {}
    for i, (name, col) in enumerate(group_cols):
        end = group_cols[i + 1][1] if i + 1 < len(group_cols) else max_col
        for ci in range(col, end):
            col_to_group[ci] = name
    default_group = group_cols[0][0] if group_cols else "группа"

    current_day: str | None = None
    day_acc: list[str] = []  # накопитель для формата с одной буквой на строку

    for table in tables:
        has_header = any(
            "день" in str(row[0] or "").lower() and "недели" in str(row[0] or "").lower()
            for row in table[:8]
        )
        current_day, day_acc = _fill_mpgu_schedule_multi(
            table, schedules, col_to_group, default_group,
            data_started=not has_header,
            current_day=current_day, day_acc=day_acc,
        )

    result = []
    for name, col in group_cols:
        sched = schedules[name]
        has_lessons = any(sched["odd_week"][d] for d in sched["odd_week"]) or \
                      any(sched["even_week"][d] for d in sched["even_week"])
        if has_lessons:
            result.append({"name": name, "year": year, "form": form,
                           "degree": degree, "schedule": sched})
    return result


_SPLIT_TIME_START_RE = re.compile(r"^(\d{3,4})\s*[-–]\s*$")
_SPLIT_TIME_END_RE = re.compile(r"^(\d{3,4})$")

# Маркеры чётной/нечётной недели на отдельной строке
_WEEK_ODD_MARKER = re.compile(
    r"^(?:числитель|числ\.?|нечётная|нечетная|нечёт\.?|нечет\.?|н/?)\s*$",
    re.IGNORECASE,
)
_WEEK_EVEN_MARKER = re.compile(
    r"^(?:знаменатель|знам\.?|чётная|четная|чёт\.?|чет\.?|з/?)\s*$",
    re.IGNORECASE,
)


def _is_metadata_line(line: str) -> bool:
    """True если строка — метаданные занятия (тип, преподаватель, аудитория, маркер недели)."""
    s = line.strip()
    if not s:
        return True
    if re.match(r"^\([А-ЯЁа-яёA-Za-z.]{2,4}\)$", s):
        return True
    if re.search(r"\b(проф|доц|ст\.?\s*преп|асс|преп)\b", s, re.I):
        return True
    if "//" in s:
        return True
    if re.search(r"(ауд\.?\s*\d|\d+\s+корп\.|спортзал|стадион)", s, re.I):
        return True
    if _WEEK_ODD_MARKER.match(s) or _WEEK_EVEN_MARKER.match(s):
        return True
    return False


def _split_timetable_content(content: str) -> list[tuple[str, str]]:
    """Делит контент ячейки на [(текст, тип_недели)] с учётом маркеров чётности.

    Если в ячейке два занятия (числитель + знаменатель), возвращает два сегмента.
    Если маркер один — возвращает один сегмент с нужным типом недели.
    Без маркеров — [(content, 'both')].
    """
    lines = content.split("\n")
    odd_pos: list[int] = []
    even_pos: list[int] = []
    for i, line in enumerate(lines):
        s = line.strip()
        if _WEEK_ODD_MARKER.match(s):
            odd_pos.append(i)
        elif _WEEK_EVEN_MARKER.match(s):
            even_pos.append(i)

    marker_set = set(odd_pos) | set(even_pos)

    # Нет маркеров — оба типа недели
    if not odd_pos and not even_pos:
        return [(content, "both")]

    # Только один тип маркера
    if odd_pos and not even_pos:
        clean = "\n".join(l for i, l in enumerate(lines) if i not in marker_set)
        return [(clean.strip(), "odd")]
    if even_pos and not odd_pos:
        clean = "\n".join(l for i, l in enumerate(lines) if i not in marker_set)
        return [(clean.strip(), "even")]

    # Оба типа: пытаемся разбить на два занятия
    all_markers = sorted([(p, "odd") for p in odd_pos] + [(p, "even") for p in even_pos])
    m1_pos, week1 = all_markers[0]
    m2_pos, week2 = all_markers[1]

    # Ищем начало второго занятия: первая не-метаданная строка между m1 и m2
    second_start = m1_pos + 1
    for i in range(m1_pos + 1, m2_pos):
        if lines[i].strip() and not _is_metadata_line(lines[i]):
            second_start = i
            break

    part1 = "\n".join(l for i, l in enumerate(lines) if i < second_start and i not in marker_set)
    part2 = "\n".join(l for i, l in enumerate(lines) if i >= second_start and i not in marker_set)

    result = []
    if part1.strip():
        result.append((part1.strip(), week1))
    if part2.strip():
        result.append((part2.strip(), week2))
    return result if result else [(content, "both")]


def _fill_mpgu_schedule_multi(
    table: list[list],
    schedules: dict[str, dict],
    col_to_group: dict[int, str],
    default_group: str,
    data_started: bool = False,
    current_day: str | None = None,
    day_acc: list[str] | None = None,
) -> tuple[str | None, list[str]]:
    """Читает одну таблицу и добавляет занятия в schedules. Возвращает (current_day, day_acc)."""
    if day_acc is None:
        day_acc = []

    current_time: tuple[str, str] | None = None
    # partial_start: начало времени из split-row формата (e.g. '900 -' / '1030')
    partial_start: str | None = None
    # pending: {(group_name, col_idx): [fragments]}
    pending: dict[tuple[str, int], list[str]] = {}

    def flush():
        nonlocal pending
        if not pending or not current_day or not current_time:
            pending = {}
            return
        t_start, t_end = current_time
        for (gname, ci), frags in pending.items():
            sched = schedules.get(gname)
            if sched is None:
                continue
            content = "\n".join(frags)
            for seg_content, week_type in _split_timetable_content(content):
                lesson = _parse_timetable_cell(seg_content, t_start, t_end, None)
                if lesson:
                    if week_type in ("odd", "both"):
                        sched["odd_week"][current_day].append(lesson)
                    if week_type in ("even", "both"):
                        sched["even_week"][current_day].append({**lesson})
        pending = {}

    for row in table:
        c0 = str(row[0] or "").strip()
        c1 = str(row[1] or "").strip() if len(row) > 1 else ""

        if not data_started:
            if "день" in c0.lower() and "недели" in c0.lower():
                data_started = True
            continue

        # Определяем день
        if c0:
            raw = c0.replace("\n", "").strip()
            if raw:
                # 1) Пробуем как полное название дня — прямое (Format 3) или обратное (Format 1a)
                day = normalize_day(raw.lower())
                if not day and len(raw) > 1:
                    day = normalize_day("".join(reversed(raw)).lower())
                if day:
                    current_day = day
                    day_acc = []
                elif len(raw) == 1:
                    # 2) Накапливаем одиночные буквы (Format 2)
                    day_acc.append(raw.upper())
                    candidate = "".join(day_acc)
                    day = normalize_day(candidate.lower())
                    if day:
                        current_day = day
                        day_acc = []
                # Если len>1 и не день — это, скорее всего, фрагмент (напр. 'ИК'), игнорируем

        # Новый временной слот — три варианта: split-start, split-end, полное время
        sm = _SPLIT_TIME_START_RE.match(c1) if c1 else None
        em = _SPLIT_TIME_END_RE.match(c1) if (c1 and partial_start is not None) else None

        if sm:
            # Начало split-time: сохраняем предыдущий слот и запоминаем начало
            flush()
            partial_start = sm.group(1).zfill(4)
        elif em:
            # Конец split-time: собираем полное время и активируем слот
            combined = f"{partial_start}-{em.group(1)}"
            parsed_time = _try_parse_time_cell(combined)
            if parsed_time:
                current_time = parsed_time
            partial_start = None
        else:
            # Обычная строка: пробуем распарсить полное время из c1
            parsed_time = _try_parse_time_cell(c1)
            if parsed_time:
                flush()
                current_time = parsed_time
                partial_start = None

        # Собираем содержимое всех колонок с занятиями (col2+).
        # Включаем строки с partial_start, чтобы не потерять фрагменты до получения end-time.
        if current_day and (current_time is not None or partial_start is not None):
            for ci in range(2, len(row)):
                cell = str(row[ci] or "").strip()
                if cell and cell not in _SKIP_CELLS:
                    gname = col_to_group.get(ci, default_group)
                    key = (gname, ci)
                    if key not in pending:
                        pending[key] = []
                    pending[key].append(cell)

    flush()
    return current_day, day_acc


def _parse_mpgu_timetable(table: list[list], data_started: bool = False) -> list[dict]:
    """Парсит формат МПГУ: один PDF = одна группа, день — вертикальный текст."""
    group_name, form, degree, year = _extract_timetable_header(table)
    schedule = make_schedule_skeleton()

    current_day: str | None = None
    current_time: tuple[str, str] | None = None
    pending: list[str] = []  # content cells накопленные для текущего слота

    for row in table:
        c0 = str(row[0] or "").strip()
        c1 = str(row[1] or "").strip() if len(row) > 1 else ""
        c2 = str(row[2] or "").strip() if len(row) > 2 else ""

        # Начинаем читать данные после строки-заголовка "День недели / Время / ..."
        if not data_started:
            if "день" in c0.lower() and "недели" in c0.lower():
                data_started = True
            continue

        # Определяем день (перевёрнутый текст в col0)
        if c0:
            reversed_text = "".join(reversed(c0.replace("\n", "")))
            day = normalize_day(reversed_text.strip().lower())
            if day:
                current_day = day

        # Определяем временной слот в col1
        time_match = re.search(r"(\d{4})\D+(\d{4})", c1)
        if time_match:
            # Сбрасываем накопленные занятия предыдущего слота
            if pending and current_day and current_time:
                _assign_timetable_lessons(schedule, current_day, current_time, pending)
            pending = []
            t_start = _fmt_time(time_match.group(1))
            t_end = _fmt_time(time_match.group(2))
            current_time = (t_start, t_end)

        # Собираем контент текущего слота
        if c2 and c2 not in {"День самоподготовки", "—", "-"} and current_day and current_time:
            pending.append(c2)

    # Последний слот
    if pending and current_day and current_time:
        _assign_timetable_lessons(schedule, current_day, current_time, pending)

    has_lessons = any(schedule["odd_week"][d] for d in schedule["odd_week"]) or \
                  any(schedule["even_week"][d] for d in schedule["even_week"])
    if not has_lessons:
        return []

    return [{"name": group_name, "year": year, "form": form, "degree": degree,
             "schedule": schedule}]


def _extract_timetable_groups(table: list[list]) -> tuple:
    """Извлекает список групп (name, col_idx), форму, степень и курс из заголовка таблицы.

    Возвращает: ([(group_name, col_idx), ...], form, degree, year)
    """
    # Допускаем пробелы вокруг дефиса (напр. 'ЗОГ34 - ГУМ2501')
    GROUP_RE = re.compile(r"[А-ЯЁа-яёA-Za-z]{2,6}\d{2}\s*-\s*[А-ЯЁа-яёA-Za-z]{2,6}\d{4}")
    groups: list[tuple[str, int]] = []
    form = "full_time"
    degree = "bachelor"
    year = None

    def _norm_group_name(raw: str) -> str:
        """Нормализует код группы: убирает пробелы вокруг дефиса."""
        return re.sub(r"\s*-\s*", "-", raw.strip())

    for row in table[:20]:
        for ci, cell in enumerate(row):
            text = str(cell or "").strip()
            if not text:
                continue
            tl = text.lower()
            if "заочная форма" in tl:
                form = "correspondence"
            elif "очно-заочная" in tl:
                form = "part_time"
            if "магистр" in tl:
                degree = "master"
            elif "специалит" in tl:
                degree = "specialist"
            m = re.search(r"(\d)\s+курс", tl)
            if m and year is None:
                year = int(m.group(1))
            if ci >= 2:
                # Ищем код группы: сначала с начала строки, затем вложенный (напр. '1 курс\nВZГ34-...')
                gm = GROUP_RE.match(text) or GROUP_RE.search(text)
                if gm:
                    name = _norm_group_name(gm.group(0))
                    if not any(n == name for n, _ in groups):
                        groups.append((name, ci))

    if not groups:
        # Запасной вариант: ищем любую ячейку с кодом группы (без ограничения по ci)
        for row in table[:20]:
            for ci, cell in enumerate(row):
                text = str(cell or "").strip()
                gm = GROUP_RE.search(text)
                if gm:
                    name = _norm_group_name(gm.group(0))
                    if not any(n == name for n, _ in groups):
                        groups.append((name, ci))
    if not groups:
        groups = [("группа", 2)]

    return groups, form, degree, year


def _extract_timetable_header(table: list[list]) -> tuple:
    """Совместимость: возвращает первую группу как строку."""
    groups, form, degree, year = _extract_timetable_groups(table)
    return groups[0][0], form, degree, year


def _assign_timetable_lessons(
    schedule: dict, day: str, times: tuple[str, str], contents: list[str]
) -> None:
    """Добавляет занятия в расписание; несколько content = подгруппы."""
    t_start, t_end = times
    lessons = []
    for i, content in enumerate(contents):
        sg = i + 1 if len(contents) > 1 else None
        lesson = _parse_timetable_cell(content, t_start, t_end, sg)
        if lesson:
            lessons.append(lesson)
    for lesson in lessons:
        schedule["odd_week"][day].append(lesson)
        schedule["even_week"][day].append({**lesson})


def _parse_timetable_cell(content: str, t_start: str, t_end: str,
                           subgroup: int | None) -> dict | None:
    """Парсит ячейку занятия: предмет, тип, преподаватель, аудитория."""
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    if not lines:
        return None

    # Извлекаем подгруппу из любой строки
    if subgroup is None:
        for i, line in enumerate(lines):
            cleaned, sg = extract_subgroup(line)
            if sg is not None:
                subgroup = sg
                lines[i] = cleaned
                break

    subject = lines[0]
    lesson_type = "other"
    teacher: str | None = None
    room: str | None = None

    TYPE_MAP = {"лк": "lecture", "пз": "practice", "лаб": "lab", "лб": "lab",
                "сем": "seminar", "сем.": "seminar"}

    for line in lines:
        # Тип занятия в скобках
        m = re.search(r"\(([А-ЯЁA-Zа-яёa-z.]{2,4})\)", line)
        if m:
            t = TYPE_MAP.get(m.group(1).lower())
            if t:
                lesson_type = t
            if line.strip().startswith("(") and line.strip().endswith(")"):
                continue  # строка только с типом — не предмет

        # teacher // room
        if "//" in line:
            parts = line.split("//", 1)
            left, right = parts[0].strip(), parts[1].strip()
            if re.search(r"\b(проф|доц|ст\.?\s*преп|асс|преп)\b", left, re.I):
                teacher = left
            if right and re.search(r"\d", right):
                room = right
            continue

        # Только аудитория
        if re.search(r"\d+\s+корп\.", line, re.I) or re.search(r"ауд\.?\s*\d", line, re.I) \
                or re.search(r"спортзал|зал|стадион", line, re.I):
            if room is None:
                room = line
            continue

        # Преподаватель
        if re.search(r"\b(проф|доц|ст\.?\s*преп|асс|преп)\b", line, re.I):
            if teacher is None:
                teacher = re.sub(r"\(ауд\.?[^)]*\)", "", line).strip().rstrip(",. ")
            continue

    # Очищаем предмет от маркеров типа
    subject = re.sub(r"\([А-ЯЁа-яёA-Za-z.]{2,4}\)", "", subject).strip(" ,.")
    if not subject:
        return None

    return lesson_obj(None, t_start, t_end, subject, lesson_type, teacher, room, subgroup)


def _fmt_time(hhmm: str) -> str:
    """'0900' → '09:00'"""
    return f"{hhmm[:2]}:{hhmm[2:]}"


def _is_day_column_format(header: list[str]) -> bool:
    """Заголовок содержит дни недели как столбцы."""
    day_keywords = {"понедельник", "пн", "вторник", "вт", "среда", "ср",
                    "четверг", "чт", "пятница", "пт", "суббота", "сб"}
    matches = sum(1 for h in header if any(d in h for d in day_keywords))
    return matches >= 3


def _is_day_row_format(header: list[str]) -> bool:
    """Заголовок содержит 'день', 'время', 'предмет'."""
    kw = {"день", "время", "предмет", "дисциплина", "преподаватель", "аудитор"}
    return sum(1 for h in header if any(k in h for k in kw)) >= 2


def _parse_day_columns(table: list[list]) -> list[dict]:
    """Формат: первый столбец — время, остальные — дни недели."""
    header = [str(c or "").strip() for c in table[0]]
    day_indices = {}
    for i, h in enumerate(header):
        day = normalize_day(h)
        if day:
            day_indices[i] = day

    schedule = make_schedule_skeleton()
    current_time = None

    for row in table[1:]:
        if not row:
            continue
        time_raw = str(row[0] or "").strip()
        if time_raw:
            parsed = normalize_time(time_raw)
            if parsed:
                current_time = parsed

        if current_time is None:
            continue

        for col_i, day in day_indices.items():
            if col_i >= len(row):
                continue
            cell = str(row[col_i] or "").strip()
            if not cell:
                continue

            for lesson in _parse_cell(cell, current_time[0], current_time[1]):
                week = lesson.pop("_week", "both")
                if week in ("odd", "both"):
                    schedule["odd_week"][day].append(lesson)
                if week in ("even", "both"):
                    schedule["even_week"][day].append({**lesson})

    if not any(schedule["odd_week"][d] for d in schedule["odd_week"]):
        return []

    return [{
        "name": "группа",
        "year": None,
        "form": "full_time",
        "degree": "bachelor",
        "schedule": schedule,
    }]


def _parse_day_rows(table: list[list]) -> list[dict]:
    """Формат: каждая строка — одно занятие с колонками день/время/предмет/..."""
    header = [str(c or "").strip().lower() for c in table[0]]

    col = {
        "day": _find_col(header, ["день", "дн"]),
        "time": _find_col(header, ["время", "пара"]),
        "subject": _find_col(header, ["предмет", "дисциплина", "название"]),
        "type": _find_col(header, ["вид", "тип", "форма"]),
        "teacher": _find_col(header, ["преподаватель", "педагог", "фио"]),
        "room": _find_col(header, ["аудитор", "кабинет", "зал"]),
        "group": _find_col(header, ["группа"]),
    }

    groups_data: dict[str, dict] = {}

    for row in table[1:]:
        if not row:
            continue

        day_raw = _get(row, col["day"])
        day = normalize_day(day_raw) if day_raw else None
        if not day:
            continue

        time_raw = _get(row, col["time"]) or ""
        times = normalize_time(time_raw)
        if not times:
            continue

        subject = _get(row, col["subject"]) or ""
        lesson_type = normalize_lesson_type(_get(row, col["type"]) or subject)
        teacher = _get(row, col["teacher"])
        room = _get(row, col["room"])
        group_name = _get(row, col["group"]) or "группа"

        lesson = lesson_obj(None, times[0], times[1], subject, lesson_type, teacher, room)

        if group_name not in groups_data:
            groups_data[group_name] = {
                "name": group_name,
                "year": None,
                "form": "full_time",
                "degree": "bachelor",
                "schedule": make_schedule_skeleton(),
            }

        groups_data[group_name]["schedule"]["odd_week"][day].append(lesson)
        groups_data[group_name]["schedule"]["even_week"][day].append({**lesson})

    return list(groups_data.values())


def _parse_heuristic(table: list[list]) -> list[dict]:
    """Последний шанс — пробуем угадать формат по содержимому."""
    # если первая колонка содержит времена — это day_columns без заголовка дней
    first_col = [str(r[0] or "") for r in table if r]
    has_times = sum(1 for c in first_col if re.search(r"\d{1,2}:\d{2}", c)) >= 3
    if has_times:
        return _parse_day_columns(table)
    return []


def _parse_cell(cell: str, time_start: str, time_end: str) -> list[dict]:
    """Парсит содержимое одной ячейки расписания."""
    if not cell or cell in {"-", "–", "—", "."}:
        return []

    week_type = "both"
    # ищем признаки чётности (числитель/знаменатель)
    week_m = re.search(r"\b(числ[а-я]*|знам[а-я]*|н/|з/|н\b|з\b)\b", cell, re.I)
    if week_m:
        week_type = normalize_week_type(week_m.group(1))
        cell = cell[:week_m.start()] + cell[week_m.end():]

    lesson_type = normalize_lesson_type(cell)

    # ищем аудиторию: А-101, ауд.205, 3-17
    room_m = re.search(r"(?:ауд\.?\s*)?([\wА-Яа-я]-?\d{2,4})", cell, re.I)
    room = room_m.group(1) if room_m else None

    # убираем из текста аудиторию и тип занятия
    clean = cell
    if room_m:
        clean = clean[:room_m.start()] + clean[room_m.end():]
    for key in ["лек", "лекция", "практ", "практика", "лаб", "семинар", "пр."]:
        clean = re.sub(rf"\b{key}\b\.?", "", clean, flags=re.I)
    clean = clean.strip(" ,;\n")

    lesson = lesson_obj(None, time_start, time_end, clean, lesson_type, None, room)
    lesson["_week"] = week_type
    return [lesson]


def _find_col(header: list[str], keywords: list[str]) -> int | None:
    for i, h in enumerate(header):
        if any(k in h for k in keywords):
            return i
    return None


def _get(row: list, col: int | None) -> str | None:
    if col is None or col >= len(row):
        return None
    v = row[col]
    return str(v).strip() if v is not None else None


def _compute_confidence(groups: list[dict]) -> float:
    if not groups:
        return 0.0
    total_lessons = sum(
        sum(len(day_lessons) for day_lessons in g["schedule"]["odd_week"].values()) +
        sum(len(day_lessons) for day_lessons in g["schedule"]["even_week"].values())
        for g in groups
    )
    if total_lessons == 0:
        return 0.1
    confidence = min(1.0, total_lessons / 30)
    return round(confidence, 2)
