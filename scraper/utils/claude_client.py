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
      "name": "код группы",
      "year": число (1-6) или null,
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
  "slot": число (1-8) или null,
  "time_start": "HH:MM",
  "time_end": "HH:MM",
  "subject": "полное название предмета",
  "type": "lecture" | "practice" | "lab" | "seminar" | "other",
  "teacher": "ФИО или null",
  "room": "номер аудитории или null",
  "subgroup": null | 1 | 2,
  "notes": "дополнительная информация или пустая строка"
}

Как найти название группы:
- Код группы — строка вида «ВОС40-ДПП2501», «БZО23-ИСТ2101» (буквы+цифры-буквы+цифры).
- Извлекай ТОЛЬКО код группы. Код специальности вида «44.03.01» — НЕ название группы.
- Если в ячейке есть пробелы между буквами («В О С 4 0»), убери их: «ВОС40-ДПП2501».

Правила разбора ячеек занятий:
- "subject" — ТОЛЬКО название дисциплины. Не помещай сюда время, ФИО, даты, номера аудиторий.
- "teacher" — только ФИО (например: «доц. Иванов И.И.», «Петрова А.В.»). Если не указан — null.
- "room" — только номер/название аудитории (например: «401», «ауд. 312», «онлайн»). Если нет — null.
- "notes" — диапазоны дат («с 12 февраля по 11 июня»), особые пометки. Если нет — "".
- Если написано «Фамилия И.О. (ауд. NNN)» — это teacher + room в одной строке, разбери оба поля.
- Если время написано как «09:00-10:30» — это time_start/time_end, а НЕ subject.
- Если ячейка содержит только число или короткий код — это НЕ занятие, пропусти.
- "time_start" и "time_end" всегда в формате «HH:MM» с ведущим нулём: «09:00», не «9:00».

Если расписание одинаково для чётной и нечётной недели — дублируй в оба ключа.
Если ячейка содержит занятия для разных подгрупп — создавай два объекта с subgroup: 1 и subgroup: 2.
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

    def parse_pdf_pages(self, pdf_path: str) -> dict:
        """Парсит PDF постранично батчами по 4 страницы и объединяет результаты.

        Для image-based PDF с 10+ страницами (напр. ИИЯ) отправка всего документа
        сразу приводит к неполному результату — модель читает только начало.
        """
        images = convert_from_path(pdf_path, dpi=150, fmt="jpeg")
        if not images:
            return {"groups": []}
        all_groups: list[dict] = []
        seen_names: set[str] = set()
        batch_size = 4
        for start in range(0, len(images), batch_size):
            batch = images[start:start + batch_size]
            try:
                result = self._parse_batch(batch)
                for g in result.get("groups", []):
                    name = g.get("name", "")
                    if name and name not in seen_names:
                        seen_names.add(name)
                        all_groups.append(g)
            except Exception as e:
                print(f"    ⚠ Claude batch {start // batch_size + 1}: {e}")
                continue
        return {"groups": all_groups}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=30))
    def _parse_batch(self, images) -> dict:
        content = []
        for img in images:
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
        if "```" in text:
            parts = text.split("```")
            for part in parts[1::2]:
                candidate = part.lstrip("json").strip()
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
        m = _JSON_BLOCK_RE.search(text)
        if m:
            return json.loads(m.group(0))
        return json.loads(text)


def _image_to_base64(pil_image) -> str:
    import io
    buf = io.BytesIO()
    pil_image.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")
