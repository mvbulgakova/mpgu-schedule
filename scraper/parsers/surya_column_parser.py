"""Парсер сканированных многоколоночных расписаний МПГУ.

Идея (по мотивам document-AI пайплайнов «layout → cell OCR»):
1. Surya TableRecPredictor находит геометрию таблицы на скане без текстового
   слоя — колонки и их bbox.
2. Левые узкие колонки = служебная зона (день недели + время), общая для всех.
3. Каждая широкая колонка = одна группа. Склеиваем «служебную зону + одну
   колонку группы» в узкое изображение и отдаём VLM ПО ОДНОЙ группе —
   так модель не сливает колонки и не галлюцинирует коды.
4. Одну и ту же группу с разных страниц (продолжение по дням) склеиваем по коду.

Требует: surya-ocr (TableRecPredictor) + ClaudeClient (vision).
"""
import io
import re
import base64
import json

from PIL import Image
from pdf2image import convert_from_path

from scraper.utils.claude_client import _get_anthropic_client, _VISION_MODEL
from scraper.normalizer.schedule_normalizer import sanitize_groups, fix_homoglyphs

FULL_CODE_RE = re.compile(r'[А-Я]{2,3}\d{2}-[А-Я]{2,4}\s?\d{4}')
# Терпимый шаблон: в числовых позициях допускаем гомоглифы-буквы (З/О/Ч),
# которые VLM иногда выдаёт вместо цифр 3/0/4. Пробел перед годом
# (напр. «ММК 2501») допускается и затем убирается.
_CODE_TOLERANT_RE = re.compile(
    r'([А-Я]{2,3})([\dЗОЧ]{2})-([А-Я]{2,4})\s?([\dЗОЧ]{4})')
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

_COLUMN_PROMPT = (
    "На изображении ОДНА учебная группа МПГУ: слева узкая зона дня недели и "
    "времени пар, справа — одна колонка с заголовком-кодом группы (например "
    "ВОП40-ПФК2501) и её занятиями. Извлеки строго JSON: "
    '{"name":"код группы как на картинке кириллицей","schedule":{"odd_week":'
    '{"monday":[{"time_start":"HH:MM","time_end":"HH:MM","subject":"...",'
    '"type":"lecture|practice|lab|seminar|other","teacher":"... или null",'
    '"room":"... или null"}],"tuesday":[],...},"even_week":{...}}}. '
    "Если чёт/нечёт не разделены — дублируй занятия в обе недели. Только JSON."
)


class SuryaColumnParser:
    def __init__(self, render_dpi: int = 220, col_render_scale: float = 1.6):
        self.render_dpi = render_dpi
        self.col_render_scale = col_render_scale
        self._table_rec = None
        self._client = None

    def _lazy(self):
        if self._table_rec is None:
            from surya.table_rec import TableRecPredictor
            self._table_rec = TableRecPredictor()
        if self._client is None:
            self._client = _get_anthropic_client()

    def parse(self, pdf_path: str) -> list[dict]:
        self._lazy()
        pages = convert_from_path(pdf_path, dpi=self.render_dpi)
        # колонка #i — одна и та же группа на всех страницах; собираем её чтения,
        # код берём мажоритарным голосом (устойчиво к редким мисридам VLM)
        slots: dict[int, list[dict]] = {}
        for img in pages:
            for idx, grp in self._parse_page(img.convert("RGB")):
                slots.setdefault(idx, []).append(grp)
        groups: list[dict] = []
        for idx in sorted(slots):
            reads = slots[idx]
            code = self._vote_code(reads)
            if not code:
                continue
            acc = {"name": code, "schedule": {}}
            for g in reads:
                _merge(acc, g)
            groups.append(acc)
        sanitize_groups(groups)
        return [g for g in groups if _count(g) > 0]

    def _vote_code(self, reads: list[dict]) -> str | None:
        from collections import Counter
        codes = [c for c in (self._code(g.get("name")) for g in reads) if c]
        if not codes:
            return None
        return Counter(codes).most_common(1)[0][0]

    def _parse_page(self, img: Image.Image) -> list[tuple[int, dict]]:
        W, H = img.size
        tr = self._table_rec([img])[0]
        cols = sorted(tr.cols, key=lambda c: c.bbox[0])
        if not cols:
            return []
        serv_x1 = max((c.bbox[2] for c in cols if c.bbox[2] < 0.2 * W), default=0.10 * W)
        time_zone = img.crop((0, 0, int(serv_x1), H))
        out = []
        idx = 0
        for c in cols:
            x0, _, x1, _ = c.bbox
            if x0 < serv_x1 - 5 or (x1 - x0) < 0.08 * W:
                continue  # служебная или слишком узкая колонка
            strip = img.crop((int(x0), 0, int(x1), H))
            comp = self._compose(time_zone, strip)
            grp = self._read_column(comp)
            if grp:
                out.append((idx, grp))
            idx += 1
        return out

    def _compose(self, time_zone: Image.Image, strip: Image.Image) -> Image.Image:
        h = max(time_zone.height, strip.height)
        comp = Image.new("RGB", (time_zone.width + strip.width, h), "white")
        comp.paste(time_zone, (0, 0))
        comp.paste(strip, (time_zone.width, 0))
        if self.col_render_scale != 1.0:
            comp = comp.resize((int(comp.width * self.col_render_scale),
                                int(comp.height * self.col_render_scale)))
        return comp

    def _read_column(self, img: Image.Image) -> dict | None:
        content = [
            {"type": "image", "source": {"type": "base64",
             "media_type": "image/jpeg", "data": _b64(img)}},
            {"type": "text", "text": _COLUMN_PROMPT},
        ]
        try:
            r = self._client.messages.create(
                model=_VISION_MODEL, max_tokens=8000,
                messages=[{"role": "user", "content": content}])
            text = r.content[0].text
            m = re.search(r'\{[\s\S]*\}', text)
            return json.loads(m.group(0)) if m else None
        except Exception:
            return None

    @staticmethod
    def _code(name: str | None) -> str | None:
        s = fix_homoglyphs((name or "").strip())
        m = FULL_CODE_RE.search(s)
        if m:
            return m.group(0).replace(" ", "")
        # VLM иногда читает цифру как похожую кириллическую букву (3→З, 0→О,
        # 4→Ч) внутри числовых частей кода. Матчим терпимым шаблоном и нормализуем
        # обратно в цифры ТОЛЬКО числовые позиции (буквенный префикс не трогаем).
        m = _CODE_TOLERANT_RE.search(s)
        if not m:
            return None
        pre, num1, mid, num2 = m.groups()
        tr = str.maketrans("ЗОЧ", "304")
        return f"{pre}{num1.translate(tr)}-{mid}{num2.translate(tr)}"


def _merge(into: dict, other: dict) -> None:
    si = into.setdefault("schedule", {})
    so = other.get("schedule", {}) or {}
    for wk in ("odd_week", "even_week"):
        wi = si.setdefault(wk, {})
        for d in DAYS:
            ls = (so.get(wk, {}) or {}).get(d)
            if ls:
                wi.setdefault(d, []).extend(ls)


def _count(g: dict) -> int:
    return sum(len(v) for wk in g.get("schedule", {}).values()
               for v in (wk or {}).values())


def _b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("utf-8")
