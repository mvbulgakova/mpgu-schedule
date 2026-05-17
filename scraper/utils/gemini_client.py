import json
import os
import time

import google.generativeai as genai
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


class GeminiClient:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY не задан")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-2.0-flash")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=10, max=90))
    def parse_pdf(self, pdf_path: str) -> dict:
        # Upload via Files API for reliable PDF handling
        uploaded = genai.upload_file(pdf_path, mime_type="application/pdf")
        try:
            # Wait until file is active (usually instant, but can take a few seconds)
            for _ in range(15):
                if uploaded.state.name != "PROCESSING":
                    break
                time.sleep(2)
                uploaded = genai.get_file(uploaded.name)

            if uploaded.state.name != "ACTIVE":
                raise RuntimeError(f"File upload failed: {uploaded.state.name}")

            response = self.model.generate_content([
                SYSTEM_PROMPT,
                "\n\nРаспарси расписание из этого PDF.",
                uploaded,
            ])
        finally:
            try:
                genai.delete_file(uploaded.name)
            except Exception:
                pass

        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
