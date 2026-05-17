import collections
import json
import os
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

# Fixed-interval rate limiter: at most 1 generate_content call every 5 seconds (≈12 RPM).
# Prevents burst: even if many threads upload files in parallel, they queue here
# before firing generate_content.
_slot_lock = threading.Lock()
_next_call_at: float = 0.0
_CALL_INTERVAL = 5.0  # seconds; 60/5 = 12 RPM < 15 RPM free-tier limit


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

    def parse_pdf(self, pdf_path: str) -> dict:
        # Upload first (no RPM cost; can happen in parallel with other threads)
        uploaded = self.client.files.upload(
            file=pdf_path,
            config=types.UploadFileConfig(mime_type="application/pdf"),
        )
        try:
            for _ in range(15):
                if uploaded.state.name != "PROCESSING":
                    break
                time.sleep(2)
                uploaded = self.client.files.get(name=uploaded.name)

            if uploaded.state.name != "ACTIVE":
                raise RuntimeError(f"File upload failed: {uploaded.state.name}")

            # Rate-limit here, right before the costly generate_content call
            return self._generate(uploaded)
        finally:
            try:
                self.client.files.delete(name=uploaded.name)
            except Exception:
                pass

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=10, max=60))
    def _generate(self, uploaded) -> dict:
        _acquire_gemini_slot()
        response = self.client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                SYSTEM_PROMPT,
                "\n\nРаспарси расписание из этого PDF.",
                uploaded,
            ],
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
