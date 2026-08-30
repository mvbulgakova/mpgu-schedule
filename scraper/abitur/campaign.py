"""Единый маркер приёмной кампании — чтобы данные не «протухли» молча.

Все зависящие от года факты (сроки, цены, КЦП, квоты, олимпиады) относятся к
кампании CAMPAIGN. После STALE_AFTER они считаются устаревшими: бот пишет
предупреждение в лог при запуске, чтобы никто не обнаружил это через абитуриентов.
Обновление на новую кампанию — по docs/next-campaign-checklist.md.
"""
import datetime as dt
from typing import Optional

CAMPAIGN = "2026/27"
# Приём-2026 полностью завершается к осени (доп. приём иностранцев — до 30.11,
# п. 6.8). С 1 января 2027 данные этой кампании заведомо неактуальны.
STALE_AFTER = dt.date(2026, 12, 31)


def is_stale(today: Optional[dt.date] = None) -> bool:
    return (today or dt.date.today()) > STALE_AFTER


def staleness_warning(today: Optional[dt.date] = None) -> str:
    """Текст предупреждения, если данные устарели; иначе пустая строка."""
    if is_stale(today):
        return (f"⚠️ ВНИМАНИЕ: бот настроен на приёмную кампанию {CAMPAIGN}, "
                f"а сегодня уже после {STALE_AFTER.isoformat()}. Сроки, цены, КЦП и "
                f"квоты устарели — обновите данные по docs/next-campaign-checklist.md")
    return ""
