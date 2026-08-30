"""Парсер официальных PDF «Сведения о зачислении» МПГУ (приказы о зачислении).

Два документа на каждую дату приказа:
  - «квоты»: особая/целевая/отдельная квота (плюс необнаруженные комбинации
    пропускаются, см. ниже);
  - «бви»: без вступительных испытаний (олимпиадники и т.п.) — единая
    категория на весь документ.

Каждый документ — последовательность блоков (один на направление+форма+
категория приёма), начинающихся с «Учебное структурное подразделение:».
Функция принимает уже извлечённый (fitz/pymupdf `page.get_text()`,
склеенный по страницам) текст ОДНОГО такого PDF и возвращает список записей
{"unit", "direction", "form", "quota_kind", "count"}.
"""
import re
from typing import List

# \s+ между словами (не литеральный пробел): PDF иногда переносит сам
# заголовок блока по словам построчно ("Учебное \nструктурное \n
# подразделение: \nИнститут физики..." — реальный случай 2026-08-04,
# приказ от 03.08). С литеральными пробелами сплит по этому месту не
# срабатывал, и весь блок (другое направление/квота) молча склеивался
# ХВОСТОМ предыдущего блока — из готового результата пропадал целиком,
# без welcome, а не просто с неверным подсчётом строк.
_HEADER_RE = r"Учебное\s+структурное\s+подразделение\s*:"
_BLOCK_SPLIT_RE = re.compile(rf"(?={_HEADER_RE})")

_UNIT_RE = re.compile(rf"{_HEADER_RE}\s*(.+?)\nНаправление подготовки:", re.S)
_CODE_NAME_RE = re.compile(r"Направление подготовки:\s*(.+?)\nНаправленность:", re.S)
_PROFILE_RE = re.compile(r"Направленность:\s*(.+?)\nФорма обучения:", re.S)
_FORM_RE = re.compile(r"Форма обучения:\s*(.+?)\nОсобенности приема:", re.S)
_OSOBENNOSTI_RE = re.compile(r"Особенности приема:\s*(.+?)\nОснование поступления:", re.S)
_OSNOVANIE_RE = re.compile(r"Основание поступления:\s*(.+?)\nОсобое право:", re.S)
_OSOBOE_PRAVO_RE = re.compile(r"Особое право:\s*(.+?)\n")

# [ \t]* (не \s*) вокруг переводов строк: кандидаты, зачисленные по квоте
# без конкурсного балла, оставляют клетки баллов пустыми — несколько
# пустых строк подряд. Жадный \s* прежде матчил переводы строк ТОЖЕ и
# проглатывал вплоть до "\n" перед следующим "№.", съедая именно ту
# строку целиком (см. 2026-08-04: пропали строки сразу после
# безбалльных строк — 2 из 9 в одном блоке, воспроизведено на реальном
# приказе). [ \t]* матчит только горизонтальные пробелы, так что каждый
# "\n" в шаблоне соответствует РОВНО одному переводу строки.
_ROW_RE = re.compile(r"\n[ \t]*(\d+)\.[ \t]*\n[ \t]*(\d{5,8})[ \t]*\n")


def _norm(s: str) -> str:
    """Схлопнуть все пробельные символы (включая переводы строк) в один
    пробел и убрать концевые точки/пробелы."""
    return re.sub(r"\s+", " ", s).strip(" .")


def _extract(pattern: re.Pattern, block: str) -> str | None:
    m = pattern.search(block)
    if not m:
        return None
    return _norm(m.group(1))


def _quota_kind(source: str, osobennosti: str, osnovanie: str, osoboe_pravo: str) -> str | None:
    """Порядок проверок (Отдельная квота -> Целевой прием -> Особое право:Да
    -> пропуск) эмпирически проверен на реальных документах приказа от
    03.08.2026: во всех блоках обоих файлов сработало ровно одно правило,
    неоднозначных случаев не встретилось. Категории по построению взаимно
    исключающие — каждый блок относится к одному разделу основания приёма
    ровно одного исходного документа."""
    if source == "бви":
        return "бви"
    if "Отдельная квота" in osobennosti:
        return "отдельная"
    if "Целевой прием" in osnovanie:
        return "целевая"
    if osoboe_pravo == "Да":
        return "особая"
    return None


def parse_order_pdf_text(text: str, source: str) -> List[dict]:
    """source: "квоты" или "бви". Возвращает список записей:
    {"unit": str, "direction": str, "form": str, "quota_kind": str, "count": int}
    """
    records: List[dict] = []
    parts = _BLOCK_SPLIT_RE.split(text)
    for block in parts[1:]:
        unit = _extract(_UNIT_RE, block)
        code_and_name = _extract(_CODE_NAME_RE, block)
        profile = _extract(_PROFILE_RE, block)
        form_raw = _extract(_FORM_RE, block)
        osobennosti = _extract(_OSOBENNOSTI_RE, block)
        osnovanie = _extract(_OSNOVANIE_RE, block)
        osoboe_pravo = _extract(_OSOBOE_PRAVO_RE, block)

        if None in (unit, code_and_name, profile, form_raw, osobennosti, osnovanie, osoboe_pravo):
            continue

        quota_kind = _quota_kind(source, osobennosti, osnovanie, osoboe_pravo)
        if quota_kind is None:
            continue

        count = len(_ROW_RE.findall(block))
        if count == 0:
            continue

        direction = f"{code_and_name}. {profile}"
        form = form_raw.lower()

        records.append({
            "unit": unit,
            "direction": direction,
            "form": form,
            "quota_kind": quota_kind,
            "count": count,
        })

    return records


def parse_order_pdf_codes(text: str) -> List[str]:
    """Уникальные коды абитуриентов, упомянутых где-либо в приказе.

    В отличие от parse_order_pdf_text, не завязано на блочную классификацию
    (quota_kind) — нужны все зачисленные коды целиком, а не только те, что
    попали в распознанные типы квот. Кто зачислен приказом (квота или БВИ),
    больше не претендует на место в общем конкурсе — эти коды исключаются
    из симуляции общего конкурса (см. scraper.build_lists_index), которая
    иначе продолжает считать их живыми конкурентами и завышает число мест,
    занятых в общем конкурсе.
    """
    return sorted({code for _, code in _ROW_RE.findall(text)})
