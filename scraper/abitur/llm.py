"""AI-ответ на свободный вопрос абитуриента. Заземление на базу знаний, Haiku 4.5.

Авторизация: ANTHROPIC_API_KEY или session-токен Claude Code remote. Клиент создаётся
локально и БЕЗ импорта scraper.utils.claude_client — тот тянет PIL/pdf2image на верхнем
уровне, которых нет в окружении бота (ставится только anthropic), и весь LLM-путь
падал бы в фолбэк. Цифры расчёта баллов сюда не попадают — для них /bally.
"""
import os
from pathlib import Path
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
    "Если вопрос про точный расчёт индивидуальных баллов — посоветуй команду /bally.\n"
    "ТОЧНОСТЬ: если в базе указан ДИАПАЗОН (например, цены 290–375 тыс.) — называй весь "
    "диапазон и от чего он зависит; НИКОГДА не выбирай из диапазона одно число как ответ "
    "про конкретную программу. Ссылки копируй из базы ПОСИМВОЛЬНО (не «исправляй» "
    "написание URL). Названия отделов и служб называй только те, что есть в базе. Если "
    "база не отвечает на вопрос напрямую (например, есть ли целевые места на конкретной "
    "форме/программе) — не утверждай, а скажи, где это проверить.\n"
    "ФОРМАТ: сообщение уходит в Telegram. НИКАКОГО markdown (#, **, `, [](), таблицы "
    "запрещены). Пиши обычным текстом; выделить можно только тегами <b>жирный</b> и "
    "<i>курсив</i>; списки — строками, начинающимися с «• ». Не используй другие "
    "HTML-теги и символы < > вне этих тегов.\n\n"
    "=== БАЗА ЗНАНИЙ ===\n"
)


_SESSION_TOKEN_FILE = "/home/claude/.claude/remote/.session_ingress_token"


def _default_factory():
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return anthropic.Anthropic(api_key=api_key)
    token_file = os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE", _SESSION_TOKEN_FILE)
    if os.path.exists(token_file):
        token = Path(token_file).read_text().strip()
        if token:
            return anthropic.Anthropic(auth_token=token)
    raise ValueError("Нет авторизации: задайте ANTHROPIC_API_KEY")


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
