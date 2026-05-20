import base64
import json
import os
import re
from pathlib import Path

import anthropic
from pdf2image import convert_from_path
from tenacity import retry, stop_after_attempt, wait_exponential

# Регулярка для поиска JSON-объекта верхнего уровня в ответе
_JSON_BLOCK_RE = re.compile(r'\{[\s\S]*\}', re.DOTALL)

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


_SESSION_TOKEN_FILE = "/home/claude/.claude/remote/.session_ingress_token"


def _get_anthropic_client() -> anthropic.Anthropic:
    """Создаёт клиент Anthropic, пробуя несколько источников авторизации."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return anthropic.Anthropic(api_key=api_key)
    # Fallback: session ingress token (Claude Code remote environment)
    token_file = os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE", _SESSION_TOKEN_FILE)
    if os.path.exists(token_file):
        token = Path(token_file).read_text().strip()
        if token:
            return anthropic.Anthropic(auth_token=token)
    raise ValueError(
        "Не найден ключ API: задайте ANTHROPIC_API_KEY или убедитесь, "
        "что файл session ingress token доступен"
    )


class ClaudeClient:
    def __init__(self):
        self.client = _get_anthropic_client()

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
        if "```" in text:
            # извлекаем содержимое между ```...```
            parts = text.split("```")
            for part in parts[1::2]:  # нечётные части — между ```
                candidate = part.lstrip("json").strip()
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
        # пробуем найти JSON-объект напрямую (может быть лишний текст вокруг)
        m = _JSON_BLOCK_RE.search(text)
        if m:
            return json.loads(m.group(0))
        return json.loads(text)


def _image_to_base64(pil_image) -> str:
    import io
    buf = io.BytesIO()
    pil_image.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")
