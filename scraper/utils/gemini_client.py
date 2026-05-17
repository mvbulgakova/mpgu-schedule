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


class GeminiClient:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY не задан")
        self.client = genai.Client(api_key=api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=10, max=60))
    def parse_pdf(self, pdf_path: str) -> dict:
        _acquire_gemini_slot()

        pdf_bytes = pathlib.Path(pdf_path).read_bytes()
        response = self.client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                types.Blob(mime_type="application/pdf", data=pdf_bytes),
                SYSTEM_PROMPT + "\n\nРаспарси расписание из этого PDF.",
            ],
        )

        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
