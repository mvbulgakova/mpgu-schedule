import collections
import json
import os
import pathlib
import threading
import time

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

SYSTEM_PROMPT = """Ты — парсер расписания занятий российского университета.
Тебе дают PDF расписания МПГУ (Московский педагогический государственный университет).

Верни JSON строго по следующей схеме:
{
  "groups": [
    {
      "name": "название группы или курс",
      "year": число (1-6),
      "form": "full_time" | "part_time" | "correspondence",
      "degree": "bachelor" | "specialist" | "master",
      "schedule": {
        "odd_week": {
          "monday": [...занятия...],
          "tuesday": [...],
          "wednesday": [...],
          "thursday": [...],
          "friday": [...],
          "saturday": []
        },
        "even_week": { ...аналогично... }
      }
    }
  ]
}

Каждое занятие:
{
  "slot": число (1-8),
  "time_start": "HH:MM",
  "time_end": "HH:MM",
  "subject": "полное название предмета",
  "type": "lecture" | "practice" | "lab" | "seminar" | "other",
  "teacher": "ФИО или null",
  "room": "аудитория или null",
  "subgroup": null | 1 | 2,
  "notes": ""
}

Если расписание одинаково для чётной и нечётной недели — дублируй в оба ключа.
Если ячейка содержит занятия для разных подгрупп — создавай два объекта с subgroup: 1 и subgroup: 2.
Верни ТОЛЬКО валидный JSON без пояснений."""

def _extract_json(text: str) -> dict:
    """Извлекает JSON из ответа модели — из markdown-блока или напрямую."""
    text = text.strip()
    # Убираем markdown-обёртку ```json ... ```
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except (json.JSONDecodeError, ValueError):
                continue
    # Ищем первый { ... } блок
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])
    return json.loads(text)


# Fixed-interval rate limiter: 1 generate_content call every 5 s ≈ 12 RPM
_slot_lock = threading.Lock()
_next_call_at: float = 0.0
_CALL_INTERVAL = 5.0


def _acquire_gemini_slot() -> None:
    global _next_call_at
    while True:
        with _slot_lock:
            now = time.monotonic()
            if now >= _next_call_at:
                _next_call_at = now + _CALL_INTERVAL
                return
            wait_for = _next_call_at - now
        time.sleep(wait_for)


# Models tried in order; first one that succeeds wins
_CANDIDATE_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
]


class GeminiClient:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY не задан")
        self.client = genai.Client(api_key=api_key)

    def parse_pdf(self, pdf_path: str) -> dict:
        pdf_bytes = pathlib.Path(pdf_path).read_bytes()
        last_err = None
        for model in _CANDIDATE_MODELS:
            try:
                result = self._call(model, pdf_bytes)
                return result
            except Exception as e:
                last_err = e
                continue  # always try next model
        raise RuntimeError(f"Все Gemini-модели недоступны: {last_err}") from last_err

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=2, min=10, max=30))
    def _call(self, model: str, pdf_bytes: bytes) -> dict:
        _acquire_gemini_slot()
        response = self.client.models.generate_content(
            model=model,
            contents=[
                types.Blob(mime_type="application/pdf", data=pdf_bytes),
                SYSTEM_PROMPT + "\n\nРаспарси расписание из этого PDF.",
            ],
        )
        return _extract_json(response.text)
