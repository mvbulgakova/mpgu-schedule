"""Парсер PDF «Сведения о зачислении» МПГУ → проходной балл по программам.

Проходной = минимальная сумма конкурсных баллов среди зачисленных на ОСНОВНЫЕ
(общие конкурсные) бюджетные места в основную волну. Квоты (особая/целевая/
отдельная) и платное не считаем — там свой конкурс.

Форматы за разные годы отличаются заголовком программы и раскладкой суммы:
  A (2022): «Образовательная программа: X»; сумма — последнее «крупное» число
     записи. Страница озаглавлена «основные конкурсные места» = общий конкурс.
  C (2023): «Направленность (профиль): X»; сумма — так же, последнее число.
  B (2025): «Направленность: X», «Особенности приема: Общие места»,
     «Основание поступления: Бюджетная основа»; таблица со столбцом «Сумма
     конкурсных баллов» — сумма идёт первым числом после уникального кода.

Формат B опознаём по «Особенности приема»/«конкурсных баллов» и отсекаем в нём
квотные секции; A и C — по последнему крупному числу записи.
Возвращает {(code, form, program_name): passing}.
"""
import re
from typing import Dict, Tuple

_CODE = re.compile(r"(\d\d\.\d\d\.\d\d)\s*[-–]?\s*(.+)")
_REC_A = re.compile(r"\n\d+\.\s*\n[\d-]{9,}")
_REC_B = re.compile(r"\n\s*\d+\.\s*\n\s*\d{5,}\s*\n\s*(\d{2,3})\s")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" .,;")


def _form(raw: str) -> str:
    r = raw.lower()
    if "очно-заоч" in r:
        return "очно-заочная"
    if "заоч" in r:
        return "заочная"
    return "очная"


def parse_text(txt: str) -> Dict[Tuple[str, str, str], int]:
    """Текст одного PDF → {(код, форма, программа): проходной(min суммы)}."""
    res: Dict[Tuple[str, str, str], list] = {}
    blocks = re.split(r"Направление подготовки:\s*", txt)
    for b in blocks[1:]:
        cm = _CODE.match(b)
        if not cm:
            continue
        code = cm.group(1)
        nm = (re.search(r"Образовательная программа:\s*(.+)", b)
              or re.search(r"Специальность:\s*(.+)", b)               # формат D (2024)
              or re.search(r"Направленность\s*\(профиль\):\s*(.+)", b)
              or re.search(r"Направленность:\s*(.+)", b))
        prog = _norm(nm.group(1)) if nm else None
        if not prog:
            continue
        fm = re.search(r"Форма обучения:\s*(.+)", b)
        form = _form(fm.group(1)) if fm else "очная"
        # Формат B: структурированная таблица «Сумма конкурсных баллов» +
        # секции по «Особенности приема»/«Основание поступления».
        is_b = "конкурсных" in b[:400] or "Особенности приема" in b[:400]
        if is_b:
            osob = re.search(r"Особенности приема:\s*(.+)", b)
            osnov = re.search(r"Основание поступления:\s*(.+)", b)
            if osob and "Общие" not in osob.group(1):
                continue                          # квотная секция — пропускаем
            if osnov and "юджет" not in osnov.group(1):
                continue                          # не бюджет — пропускаем
            sums = [int(s) for s in _REC_B.findall(b)]
        else:                                     # формат A/C: последнее крупное число
            sums = []
            for r in _REC_A.split(b)[1:]:
                r = r.split("Направление подготовки")[0]
                big = [int(x) for x in re.findall(r"\b(\d{2,3})\b", r)
                       if 100 <= int(x) <= 310]
                if big:
                    sums.append(big[-1])
        if sums:
            res.setdefault((code, form, prog), []).append(min(sums))
    return {k: min(v) for k, v in res.items()}
