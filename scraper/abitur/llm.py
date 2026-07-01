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
