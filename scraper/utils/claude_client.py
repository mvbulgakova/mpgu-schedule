import base64
import json
import os
import re
from pathlib import Path

import anthropic
from PIL import Image
from pdf2image import convert_from_path
from tenacity import retry, stop_after_attempt, wait_exponential

# Расписания МПГУ бывают огромного формата (A1/A2) — снимаем защиту PIL от
# "decompression bomb", иначе рендер больших страниц падает. Размер ограничиваем
# даунскейлом вручную (см. _image_to_base64).
Image.MAX_IMAGE_PIXELS = None
_MAX_SIDE = 2200  # Claude всё равно работает с ~1568px; больше не нужно

# Регулярка для поиска JSON-объекта верхнего уровня в ответе
_JSON_BLOCK_RE = re.compile(r'\{[\s\S]*\}', re.DOTALL)

SYSTEM_PROMPT = """Ты — парсер расписания занятий российского университета.
Тебе дают изображения страниц расписания МПГУ (Московский педагогический государственный университет).

ВАЖНО про структуру таблицы:
- Каждая вертикальная колонка со своим заголовком-кодом группы (например
  ВОС34-ДОШ2501, БОМ35-ПИМ2308) или номером ("105 группа") — ОТДЕЛЬНАЯ группа.
- На одной странице обычно несколько групп-колонок — извлекай ВСЕ до единой.
- Левый узкий столбец — день недели (часто написан вертикально, по буквам) +
  номер пары + время; он общий для всех групп-колонок.
- name = код группы ровно как на странице (кириллицей, без латинских подмен).

Верни JSON строго по следующей схеме:
{
  "groups": [
    {
      "name": "код группы как на странице",
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

# Модель vision можно переопределить через ANTHROPIC_VISION_MODEL.
# Sonnet надёжно разбирает плотные многоколоночные сетки МПГУ (Haiku их схлопывает).
_VISION_MODEL = os.environ.get("ANTHROPIC_VISION_MODEL", "claude-sonnet-4-6")


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

    def parse_pdf_pages(self, pdf_path: str, batch_size: int = 2,
                        max_pages: int = 60) -> dict:
        """Распознаёт расписание со сканов PDF постранично.

        Плотные многогрупповые страницы МПГУ дают объёмный JSON: при отправке
        6 страниц за раз ответ упирался в max_tokens и обрывался → невалидный
        JSON → парс падал целиком. Поэтому обрабатываем небольшими батчами,
        а группы с одинаковым именем (продолжение на следующей странице)
        склеиваем.
        """
        images = convert_from_path(pdf_path, dpi=200, fmt="jpeg")[:max_pages]
        merged: dict[str, dict] = {}
        order: list[str] = []

        for start in range(0, len(images), batch_size):
            batch = images[start:start + batch_size]
            try:
                groups = self._parse_batch(batch)
            except Exception:
                continue  # пропускаем нечитаемый батч, не теряя остальные
            for g in groups:
                name = (g.get("name") or "").strip()
                if not name:
                    continue
                if name in merged:
                    _merge_group_schedule(merged[name], g)
                else:
                    merged[name] = g
                    order.append(name)

        return {"groups": [merged[n] for n in order]}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=30))
    def _parse_batch(self, images: list) -> list[dict]:
        content = []
        for img in images:
            buf = _image_to_base64(img)
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": buf},
            })
        content.append({"type": "text", "text": "Распарси расписание с этих страниц."})

        response = self.client.messages.create(
            model=_VISION_MODEL,
            max_tokens=20000,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": content}],
        )
        text = response.content[0].text.strip()
        return _extract_json(text).get("groups", [])


def _image_to_base64(pil_image) -> str:
    import io
    w, h = pil_image.size
    if max(w, h) > _MAX_SIDE:
        scale = _MAX_SIDE / max(w, h)
        pil_image = pil_image.resize((max(1, int(w * scale)), max(1, int(h * scale))))
    buf = io.BytesIO()
    pil_image.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _merge_group_schedule(into: dict, other: dict) -> None:
    """Сливает расписание `other` в `into` (одна группа на нескольких страницах)."""
    si = into.setdefault("schedule", {})
    so = other.get("schedule", {}) or {}
    for week in ("odd_week", "even_week"):
        wi = si.setdefault(week, {})
        wo = so.get(week, {}) or {}
        for day in _DAYS:
            lessons = wo.get(day)
            if lessons:
                wi.setdefault(day, []).extend(lessons)


def _extract_json(text: str) -> dict:
    """Достаёт JSON-объект из ответа модели; терпим к markdown-обёртке и обрыву."""
    text = text.strip()
    if "```" in text:
        for part in text.split("```")[1::2]:
            candidate = part.lstrip("json").strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_BLOCK_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    # последняя попытка: ответ оборван — отрезаем до последней целой группы
    cut = text.rfind("}, {")
    if cut > 0:
        salvaged = text[:cut] + "}]}"
        # докручиваем закрытие до groups-массива
        for tail in ("}]}", "]}", "}"):
            try:
                return json.loads(text[:cut] + tail)
            except json.JSONDecodeError:
                continue
    return {"groups": []}
