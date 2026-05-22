"""
Parser for MPGU exam/credit session schedules.

Format: PDF or Excel with a transposed table layout:
  - Rows = date+time slots (with vertical cell text)
  - Columns = groups (from header row)
  - Cells = subject + type + teacher + room (may overflow into sub-tables)

Also handles scanned PDFs via Tesseract fallback.
"""
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

DAYS_RU = {
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
}

RU_MONTHS = {
    "января": "01", "февраля": "02", "марта": "03",
    "апреля": "04", "мая": "05", "июня": "06",
    "июля": "07", "августа": "08", "сентября": "09",
    "октября": "10", "ноября": "11", "декабря": "12",
}


@dataclass
class ExamEntry:
    date: str                       # "YYYY-MM-DD"
    time_start: str                 # "HH:MM"
    time_end: str | None            # "HH:MM" or None
    subject: str
    type: str                       # "exam" | "credit" | "unknown"
    teacher: str | None
    room: str | None
    groups: list[str] = field(default_factory=list)


# ─── Vertical cell decoder ────────────────────────────────────────────────────

def _decode_vertical(cell: str) -> tuple[str, str]:
    """
    Decode a cell with vertical (rotated) text.
    pdfplumber returns each character on its own line.
    Returns (kind, value) where kind in {'day','date','time','raw'}.
    """
    parts = [c.strip() for c in cell.split("\n") if c.strip()]
    fwd = "".join(parts)
    rev = "".join(reversed(parts))

    # Day of week
    for t in (fwd, rev):
        if t.lower() in DAYS_RU:
            return "day", t.lower()

    # Date: DD.MM.YYYY or DD/MM/YYYY
    for t in (fwd, rev):
        m = re.search(r"(\d{2})[./](\d{2})[./](\d{4})", t)
        if m:
            return "date", f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

    # Time: HH:MM–HH:MM or HH.MM-HH.MM
    for t in (fwd, rev):
        m = re.search(r"(\d{2})[.:](\d{2})\s*[-—]\s*(\d{2})[.:](\d{2})", t)
        if m:
            return "time", f"{m.group(1)}:{m.group(2)}-{m.group(3)}:{m.group(4)}"

    return "raw", fwd or rev


def _parse_date_text(text: str) -> str | None:
    """Parse a date from natural language text, e.g. '15 января 2026'."""
    m = re.search(r"(\d{1,2})\s+(" + "|".join(RU_MONTHS) + r")\s+(\d{4})", text, re.I)
    if m:
        d = m.group(1).zfill(2)
        mo = RU_MONTHS[m.group(2).lower()]
        y = m.group(3)
        return f"{y}-{mo}-{d}"
    m2 = re.search(r"(\d{2})[./](\d{2})[./](\d{4})", text)
    if m2:
        return f"{m2.group(3)}-{m2.group(2)}-{m2.group(1)}"
    return None


# ─── Cell content parser ─────────────────────────────────────────────────────

def _parse_cell_content(lines: list[str]) -> dict | None:
    """Extract subject, type, teacher, room from a list of text lines."""
    lines = [ln.strip() for ln in lines if ln.strip()]
    if not lines:
        return None

    subject_parts: list[str] = []
    type_: str = "unknown"
    teacher: str | None = None
    room: str | None = None

    for line in lines:
        up = line.upper()
        if "ЭКЗАМЕН" in up:
            type_ = "exam"
        elif "ЗАЧЁТ" in up or "ЗАЧЕТ" in up:
            type_ = "credit"
        elif re.search(r"ауд\.?\s*[\d\w/\\-]+", line, re.I):
            m = re.search(r"ауд\.?\s*([\d\w/\\-]+)", line, re.I)
            if m:
                room = m.group(1)
        elif re.search(r"\b(проф|доц|ст\.?\s*пр|асс|преп)[.\s]", line, re.I):
            teacher = line
        elif re.search(r"[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.[А-ЯЁ]\.", line):
            teacher = line
        elif not re.search(r"^\(|ауд\.|зачет|экзамен", line, re.I):
            subject_parts.append(line)

    subject = " ".join(subject_parts).strip()
    if not subject:
        return None

    return {
        "subject": subject,
        "type": type_,
        "teacher": teacher,
        "room": room,
    }


# ─── PDF parser ──────────────────────────────────────────────────────────────

def _parse_pdf(path: str) -> list[ExamEntry]:
    try:
        import pdfplumber
    except ImportError:
        log.warning("pdfplumber not available")
        return []

    entries: list[ExamEntry] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_entries = _extract_page(page)
            entries.extend(page_entries)

    # If text extraction failed (scanned PDF), try Tesseract
    if not entries:
        entries = _parse_pdf_ocr(path)

    return entries


def _extract_page(page) -> list[ExamEntry]:
    ts = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
    try:
        finders = list(page.find_tables(ts))
    except Exception:
        return []
    if not finders:
        return []

    tables = [(f.bbox, f.extract()) for f in finders]

    # ── Step 1: find main schedule table (has group headers) ──
    main_idx: int | None = None
    header_row_idx: int = 0
    group_col_map: list[tuple[int, str]] = []  # [(col_idx, group_name)]

    for ti, (bbox, table) in enumerate(tables):
        for ri, row in enumerate(table):
            cells = [str(c or "").strip() for c in row]
            grps = [
                (ci, c) for ci, c in enumerate(cells)
                if re.search(r"[А-ЯЁ]{2,}\d{2}", c) and len(c) < 60
            ]
            if len(grps) >= 1:
                main_idx = ti
                header_row_idx = ri
                group_col_map = grps
                break
        if main_idx is not None:
            break

    if main_idx is None or not group_col_map:
        return []

    main_bbox, main_table = tables[main_idx]

    # ── Step 2: extract date/time from main table rows ──
    # row_meta[ri] = {'date': ..., 'time_start': ..., 'time_end': ...}
    row_meta: dict[int, dict] = {}
    cur_date: str | None = None
    cur_time: str | None = None

    for ri, row in enumerate(main_table):
        if ri <= header_row_idx:
            continue
        for cell in row:
            if not cell:
                continue
            s = str(cell).strip()
            if "\n" in s and len(s) < 100:
                kind, val = _decode_vertical(s)
                if kind == "date":
                    cur_date = val
                elif kind == "time":
                    cur_time = val
        if cur_date or cur_time:
            row_meta[ri] = {
                "date": cur_date,
                "time": cur_time,
            }

    # ── Step 3: extract exam content from main table cells ──
    entries_from_main = _entries_from_main_table(
        main_table, header_row_idx, group_col_map, row_meta
    )

    # ── Step 4: extract exam content from overflow sub-tables ──
    # Sub-tables are positioned within the grid; match by Y-overlap to row_meta
    entries_from_sub = _entries_from_sub_tables(
        tables, main_idx, main_bbox, main_table, header_row_idx,
        group_col_map, row_meta, page
    )

    # Merge, prefer sub-table entries (they have full content)
    return entries_from_sub if entries_from_sub else entries_from_main


def _entries_from_main_table(
    table: list[list],
    header_row_idx: int,
    group_col_map: list[tuple[int, str]],
    row_meta: dict[int, dict],
) -> list[ExamEntry]:
    entries = []
    # Carry forward date across rows
    cur_date = None

    for ri, row in enumerate(table):
        if ri <= header_row_idx:
            continue
        meta = row_meta.get(ri, {})
        if meta.get("date"):
            cur_date = meta["date"]
        date = cur_date
        time_str = meta.get("time")
        time_start, time_end = _split_time(time_str)

        if not date:
            continue

        cells = [str(c or "").strip() for c in row]
        for col_idx, group_name in group_col_map:
            if col_idx >= len(cells):
                continue
            cell = cells[col_idx]
            if not cell or len(cell) < 3:
                continue
            content = _parse_cell_content(cell.split("\n"))
            if content:
                entries.append(ExamEntry(
                    date=date,
                    time_start=time_start or "",
                    time_end=time_end,
                    subject=content["subject"],
                    type=content["type"],
                    teacher=content["teacher"],
                    room=content["room"],
                    groups=[_clean_group_name(group_name)],
                ))
    return entries


def _entries_from_sub_tables(
    tables: list[tuple],
    main_idx: int,
    main_bbox: tuple,
    main_table: list[list],
    header_row_idx: int,
    group_col_map: list[tuple[int, str]],
    row_meta: dict[int, dict],
    page,
) -> list[ExamEntry]:
    """
    Match sub-tables to (group, date, time) by spatial position.
    """
    # Get group column x-ranges from page words
    group_x_ranges = _get_group_x_ranges(page, group_col_map, main_bbox)
    if not group_x_ranges:
        return []

    # Get row y-ranges from main table structure
    row_y_ranges = _get_row_y_ranges(page, main_table, header_row_idx, main_bbox, row_meta)

    entries: list[ExamEntry] = []
    cur_date = None

    for ri_ordered, (y0, y1, date, time_str) in enumerate(row_y_ranges):
        if date:
            cur_date = date
        effective_date = cur_date

        for sub_idx, (sub_bbox, sub_table) in enumerate(tables):
            if sub_idx == main_idx:
                continue
            sx0, sy0, sx1, sy1 = sub_bbox
            # Y-overlap check
            if sy1 < y0 or sy0 > y1:
                continue
            # Find matching group by X-overlap
            sub_cx = (sx0 + sx1) / 2
            group_name = _find_group_for_x(sub_cx, group_x_ranges)
            if not group_name:
                continue

            # Extract content from sub-table
            lines = []
            for row in sub_table:
                for cell in row:
                    if cell:
                        lines.extend(str(cell).split("\n"))

            content = _parse_cell_content(lines)
            if not content or not effective_date:
                continue

            time_start, time_end = _split_time(time_str)
            entries.append(ExamEntry(
                date=effective_date,
                time_start=time_start or "",
                time_end=time_end,
                subject=content["subject"],
                type=content["type"],
                teacher=content["teacher"],
                room=content["room"],
                groups=[_clean_group_name(group_name)],
            ))

    return entries


def _get_group_x_ranges(page, group_col_map, main_bbox) -> list[tuple[float, float, str]]:
    """
    Get (x_left, x_right, group_name) for each group column.

    Strategy: find group-code words in the header area, sort both group_col_map
    (by col_idx) and found words (by x) and zip them in order.  This handles
    duplicate codes like two "ВОИ34-ИОВ2503" groups (п/г 1 and п/г 2).
    """
    words = page.extract_words()
    main_x0, main_y0, main_x1, main_y1 = main_bbox
    header_y_max = main_y0 + 100

    group_code_re = re.compile(r"[А-ЯЁA-Z]{2,}\d{2}")
    # Collect all group-code words in the header area, sorted by x
    header_group_words = sorted(
        [w for w in words if group_code_re.search(w["text"]) and w["top"] <= header_y_max],
        key=lambda w: w["x0"],
    )

    # Sort groups by column index (left-to-right order)
    sorted_groups = sorted(group_col_map, key=lambda x: x[0])

    if not header_group_words:
        return []

    # Match in order: i-th group (sorted by col) → i-th header word (sorted by x)
    result = []
    for i, (col_idx, group_name) in enumerate(sorted_groups):
        if i >= len(header_group_words):
            break
        w = header_group_words[i]
        x_center = (w["x0"] + w["x1"]) / 2
        # Estimate column width as distance to next group word / 2
        if i + 1 < len(header_group_words):
            next_cx = (header_group_words[i + 1]["x0"] + header_group_words[i + 1]["x1"]) / 2
            half_width = (next_cx - x_center) / 2
        else:
            half_width = (main_x1 - x_center) / 2
        result.append((x_center - half_width, x_center + half_width, group_name))

    return result


def _get_row_y_ranges(
    page, main_table, header_row_idx, main_bbox, row_meta
) -> list[tuple[float, float, str | None, str | None]]:
    """
    Approximate y-ranges for data rows using equal distribution within table height.
    Returns [(y0, y1, date, time)] for each data row.
    """
    x0, y0, x1, y1 = main_bbox
    data_rows = [ri for ri in range(len(main_table)) if ri > header_row_idx]
    if not data_rows:
        return []

    row_height = (y1 - y0) / len(main_table)
    ranges = []
    for ri in data_rows:
        ry0 = y0 + ri * row_height
        ry1 = ry0 + row_height
        meta = row_meta.get(ri, {})
        ranges.append((ry0, ry1, meta.get("date"), meta.get("time")))
    return ranges


def _find_group_for_x(cx: float, group_x_ranges) -> str | None:
    best_overlap = 0
    best_group = None
    for x0, x1, group_name in group_x_ranges:
        overlap = min(cx, x1) - max(cx, x0)
        if cx >= x0 and cx <= x1:
            return group_name
        dist = abs(cx - (x0 + x1) / 2)
        if best_group is None or dist < best_overlap:
            best_overlap = dist
            best_group = group_name
    return best_group


def _split_time(time_str: str | None) -> tuple[str | None, str | None]:
    if not time_str:
        return None, None
    m = re.match(r"(\d{2}:\d{2})-(\d{2}:\d{2})", time_str)
    if m:
        return m.group(1), m.group(2)
    return time_str, None


def _clean_group_name(name: str) -> str:
    # Remove room number suffix like "(101)"
    return re.sub(r"\s*\(\d{3}\)\s*$", "", name).strip()


# ─── OCR fallback for scanned PDFs ───────────────────────────────────────────

def _parse_pdf_ocr(path: str) -> list[ExamEntry]:
    """Fallback: Tesseract OCR for image-based exam schedule PDFs."""
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError:
        return []

    log.info("Falling back to OCR for exam schedule: %s", path)
    entries: list[ExamEntry] = []
    images = convert_from_path(path, dpi=200)

    for img in images:
        text = pytesseract.image_to_string(img, lang="rus+eng", config="--psm 6")
        page_entries = _parse_ocr_text(text)
        entries.extend(page_entries)

    return entries


def _parse_ocr_text(text: str) -> list[ExamEntry]:
    """
    Parse exam entries from raw OCR text.
    Looks for date patterns followed by subject / type / teacher / room.
    """
    entries: list[ExamEntry] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    cur_date = None

    i = 0
    while i < len(lines):
        line = lines[i]
        date = _parse_date_text(line)
        if date:
            cur_date = date

        # Detect exam/credit lines
        if cur_date and re.search(r"ЗАЧЁТ|ЗАЧЕТ|ЭКЗАМЕН", line.upper()):
            entry_lines = lines[max(0, i - 2): i + 4]
            content = _parse_cell_content(entry_lines)
            if content:
                time_match = re.search(r"(\d{2}[.:]\d{2})", " ".join(entry_lines))
                time_start = time_match.group(1).replace(".", ":") if time_match else ""
                entries.append(ExamEntry(
                    date=cur_date,
                    time_start=time_start,
                    time_end=None,
                    subject=content["subject"],
                    type=content["type"],
                    teacher=content["teacher"],
                    room=content["room"],
                    groups=[],
                ))
        i += 1

    return entries


# ─── Excel parser ─────────────────────────────────────────────────────────────

def _parse_excel(path: str) -> list[ExamEntry]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        return []

    wb = load_workbook(path, data_only=True)
    entries: list[ExamEntry] = []
    for ws in wb.worksheets:
        entries.extend(_parse_excel_sheet(ws))
    return entries


def _parse_excel_sheet(ws) -> list[ExamEntry]:
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # Find header row with group names
    header_row_idx = None
    group_col_map: list[tuple[int, str]] = []

    for ri, row in enumerate(rows):
        cells = [str(c or "").strip() for c in row]
        grps = [
            (ci, c) for ci, c in enumerate(cells)
            if re.search(r"[А-ЯЁ]{2,}\d{2}", c) and len(c) < 60
        ]
        if grps:
            header_row_idx = ri
            group_col_map = grps
            break

    if header_row_idx is None:
        return []

    entries = []
    cur_date = None
    cur_time = None

    for row in rows[header_row_idx + 1:]:
        cells = [str(c or "").strip() for c in row]
        # Scan for date/time in non-group columns
        for ci, cell in enumerate(cells):
            if not cell:
                continue
            date = _parse_date_text(cell)
            if date:
                cur_date = date
            m = re.search(r"(\d{2})[.:](\d{2})\s*[-—]\s*(\d{2})[.:](\d{2})", cell)
            if m:
                cur_time = f"{m.group(1)}:{m.group(2)}-{m.group(3)}:{m.group(4)}"

        if not cur_date:
            continue

        time_start, time_end = _split_time(cur_time)
        for col_idx, group_name in group_col_map:
            if col_idx >= len(cells):
                continue
            cell = cells[col_idx]
            content = _parse_cell_content(cell.split("\n") if "\n" in cell else [cell])
            if content:
                entries.append(ExamEntry(
                    date=cur_date,
                    time_start=time_start or "",
                    time_end=time_end,
                    subject=content["subject"],
                    type=content["type"],
                    teacher=content["teacher"],
                    room=content["room"],
                    groups=[_clean_group_name(group_name)],
                ))
    return entries


# ─── Public API ──────────────────────────────────────────────────────────────

def parse_exam_file(path: str) -> list[ExamEntry]:
    """Parse exam/credit schedule from a PDF or Excel file."""
    ext = Path(path).suffix.lower()
    if ext in {".xlsx", ".xls"}:
        return _parse_excel(path)
    else:
        return _parse_pdf(path)


def entries_to_dicts(entries: list[ExamEntry]) -> list[dict]:
    return [
        {
            "date": e.date,
            "time_start": e.time_start,
            "time_end": e.time_end,
            "subject": e.subject,
            "type": e.type,
            "teacher": e.teacher,
            "room": e.room,
            "groups": e.groups,
        }
        for e in sorted(entries, key=lambda x: (x.date, x.time_start))
    ]
