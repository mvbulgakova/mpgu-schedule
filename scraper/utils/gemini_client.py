import base64
import collections
import io
import json
import os
import pathlib
import threading
import time

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

_PAGE_PROMPT = """Ты — парсер одной страницы расписания МПГУ.
На изображении — одна страница расписания учебных занятий."""

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
  "room": "номер аудитории или null",
  "subgroup": null | 1 | 2,
  "notes": "дополнительная информация (диапазоны дат и т.п.) или пустая строка"
}

Форматы расписания:
- ВЕРТИКАЛЬНЫЙ: группы идут по строкам, дни — столбцы. Каждая строка = одна группа.
- ГОРИЗОНТАЛЬНЫЙ: группы идут по СТОЛБЦАМ, дни/пары — строки. Каждый столбец = одна группа.
  При горизонтальном формате обязательно извлеки ВСЕ столбцы как отдельные группы.

Как найти название группы:
- Код группы — это строка вида «ВОС40-ДПП2501», «БZО23-ИСТ2101», «ЗОС40-ОАД2502» (буквы+цифры-буквы+цифры).
- Он может находиться в сложной ячейке-заголовке вместе с кодом специальности (44.03.01) и названием направления.
- Извлекай ТОЛЬКО код группы (например «ВОС40-ДПП2501»), без кода специальности и текста направления.
- Код специальности вида «44.03.01», «53.03.03» — это НЕ название группы, игнорируй его.
- Если в ячейке есть пробелы между буквами («В О С 4 0»), убери лишние пробелы: «ВОС40-ДПП2501».

Правила разбора ячеек занятий:
- "subject" — ТОЛЬКО название дисциплины. Не помещай сюда время, ФИО преподавателей, даты.
- "teacher" — только ФИО преподавателя (например: «доц. Иванов И.И.», «Петрова А.В.»). Если не указан — null.
- "room" — только номер/название аудитории (например: «401», «ауд. 312», «онлайн»). Если не указана — null.
- "notes" — диапазоны дат («с 12 февраля по 11 июня»), особые пометки. Если ничего — "".
- Если написано «Фамилия И.О. (ауд. NNN)» — это teacher + room в одной строке, разбери оба поля.
- Если время написано как «09:00-10:30» — это time_start/time_end, а не subject.

Если расписание одинаково для чётной и нечётной недели — дублируй в оба ключа.
Если ячейка содержит занятия для разных подгрупп — создавай два объекта с subgroup: 1 и subgroup: 2.
Верни ТОЛЬКО валидный JSON без пояснений."""

def _merge_group_schedule(target: dict, source: dict) -> None:
    """Добавляет занятия из source в target для дней, где target пустой."""
    for week in ("odd_week", "even_week"):
        tw = target.get("schedule", {}).get(week, {})
        sw = source.get("schedule", {}).get(week, {})
        for day, lessons in sw.items():
            if lessons and not tw.get(day):
                tw[day] = lessons


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
                continue
        raise RuntimeError(f"Все Gemini-модели недоступны: {last_err}") from last_err

    def parse_pdf_by_pages(self, pdf_path: str) -> dict:
        """Конвертирует PDF в изображения и обрабатывает каждую страницу отдельно.

        Нужно для image-based PDF с большим числом страниц (напр. ИИЯ, ~15 стр),
        где отправка целого файла Gemini даёт только 1-2 группы вместо 10-15.
        """
        from pdf2image import convert_from_path
        images = convert_from_path(pdf_path, dpi=150, fmt="jpeg")
        all_groups: list[dict] = []
        seen_names: set[str] = set()
        for idx, img in enumerate(images):
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            jpeg_bytes = buf.getvalue()
            b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
            try:
                result = self._call_image(jpeg_bytes)
                for g in result.get("groups", []):
                    name = g.get("name", "")
                    if name and name not in seen_names:
                        seen_names.add(name)
                        all_groups.append(g)
                    elif name in seen_names:
                        # Merge schedule if same group appears again (odd vs even page split)
                        existing = next((x for x in all_groups if x.get("name") == name), None)
                        if existing:
                            _merge_group_schedule(existing, g)
            except Exception as e:
                print(f"    ⚠ Страница {idx+1}/{len(images)}: {e}")
                continue
        return {"groups": all_groups}

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

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=2, min=10, max=30))
    def _call_image(self, jpeg_bytes: bytes) -> dict:
        _acquire_gemini_slot()
        last_err = None
        for model in _CANDIDATE_MODELS:
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=[
                        types.Part(
                            inline_data=types.Blob(
                                mime_type="image/jpeg",
                                data=jpeg_bytes,
                            )
                        ),
                        SYSTEM_PROMPT + "\n\nРаспарси расписание с этого изображения страницы.",
                    ],
                )
                return _extract_json(response.text)
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"Все Gemini-модели недоступны для изображения: {last_err}")
