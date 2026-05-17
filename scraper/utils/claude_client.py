import base64
import json
import os
from pathlib import Path

import anthropic
from pdf2image import convert_from_path
from tenacity import retry, stop_after_attempt, wait_exponential

SYSTEM_PROMPT = """Ты — парсер расписания занятий российского университета.
Тебе дают изображения страниц расписания МПГУ (Московский педагогический государственный университет).

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
          "saturday": [...]
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
Если ячейка содержит занятия для разных подгрупп — создавай два объекта занятия с subgroup: 1 и subgroup: 2.
Верни ТОЛЬКО валидный JSON без пояснений."""


class ClaudeClient:
    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY не задан")
        self.client = anthropic.Anthropic(api_key=api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=30))
    def parse_pdf_pages(self, pdf_path: str) -> dict:
        images = convert_from_path(pdf_path, dpi=150, fmt="jpeg")

        content = []
        for img in images[:6]:  # не более 6 страниц за раз
            buf = _image_to_base64(img)
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": buf},
            })
        content.append({"type": "text", "text": "Распарси расписание с этих страниц."})

        response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8192,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": content}],
        )

        text = response.content[0].text.strip()
        # убираем markdown-обёртку если есть
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)


def _image_to_base64(pil_image) -> str:
    import io
    buf = io.BytesIO()
    pil_image.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")
