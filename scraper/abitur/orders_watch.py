"""Вахта приказов о зачислении: заметить новый и разослать подписчикам.

Приказ — единственный официальный ответ на вопрос «зачислен ли я», и ждут его
буквально всю ночь. 2026-08-07 около часа ночи людям пришли уведомления с
Госуслуг о включении в приказ, а на mpgu.su приказа ещё не было — то есть
разрыв между «решение принято» и «документ опубликован» реальный и в часы.

Логика здесь чистая (без сети и без Telegram), чтобы её можно было проверить
тестами: что считать новым приказом, как не разослать одно и то же дважды и
что написать людям.
"""
import re
from typing import Dict, List, Optional, Set

# Страница со ссылками на приказы конкретных дат.
INDEX_PAGE = "https://mpgu.su/postuplenie/svedenija-zachislenii-2026/"

_DATE_RE = re.compile(r"zachislenie-(\d{2})-(\d{2})-(\d{4})")

# Приказы, о которых рассылать НЕ надо: они опубликованы до появления вахты и
# уже разобраны (приоритетный этап — квоты и БВИ, 3 августа). Без этого списка
# первый же запуск разослал бы всем «опубликован приказ» о недельной новости.
ALREADY_PUBLISHED = {
    "https://mpgu.su/postuplenie/svedenija-zachislenii-2026/"
    "zachislenie-03-08-2026-budget/",
}


def order_date(url: str) -> Optional[str]:
    """'…/zachislenie-03-08-2026-budget/' → '03.08.2026'."""
    m = _DATE_RE.search(url or "")
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else None


def new_orders(pages: List[str], seen: Set[str]) -> List[str]:
    """Подстраницы приказов, которых ещё не рассылали, в порядке появления."""
    return [u for u in pages if u and u not in seen]


def _kind(pdf_url: str) -> str:
    """Что за приказ по имени файла — чтобы человек понял, его ли это."""
    name = (pdf_url or "").lower()
    if "bvi" in name:
        return "без вступительных испытаний (БВИ)"
    if "kvot" in name:
        return "по квотам"
    if "platn" in name or "dogovor" in name:
        return "на платные места"
    if "budget" in name or "byudzhet" in name or "osnov" in name:
        return "на бюджет, основные места"
    return ""


def format_notice(page_url: str, pdf_urls: List[str]) -> str:
    """Текст рассылки о новом приказе."""
    date = order_date(page_url)
    head = (f"📄 <b>Опубликован приказ о зачислении</b>"
            + (f" от {date}" if date else "") + ".")
    lines = [head, ""]
    kinds = [k for k in (_kind(u) for u in pdf_urls) if k]
    if kinds:
        lines.append("В приказе: " + ", ".join(dict.fromkeys(kinds)) + ".")
    lines.append("Файлы прикреплены ниже — ищите в них свой уникальный код.")
    lines.append("")
    lines.append(f"Страница приказа: {page_url}")
    lines.append("Приказ — официальный документ; конкурсные списки на epk25 "
                 "зачисленных не помечают.")
    return "\n".join(lines)


def pdf_filename(url: str, date: Optional[str] = None) -> str:
    """Имя файла для Telegram: понятное человеку, а не хеш из адреса."""
    tail = (url or "").rstrip("/").split("/")[-1] or "prikaz.pdf"
    if not tail.lower().endswith(".pdf"):
        tail += ".pdf"
    return tail


def recipients(subs: Dict[str, dict]) -> List[str]:
    """Кому слать: всем подписчикам.

    Приказ касается каждого, кто следит за поступлением, независимо от того,
    подписан человек на свой код или только на обновление списков.
    """
    return list(subs)
