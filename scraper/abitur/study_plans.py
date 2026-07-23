"""Учебные планы (перечни дисциплин) МПГУ по направлениям.

Источник — публичная таблица «Сведения об образовательной организации» →
Образование (mpgu.su/sveden/education): у каждого направления+профиля столбец
«Дисциплины» ведёт на ZIP с PDF (перечень дисциплин по годам приёма). Карта
{направление → ссылка} собрана в study_plans_2026.json.

ВАЖНО: это перечень дисциплин, БЕЗ разбивки по семестрам (её в публичных
файлах нет). Матчинг программы каталога на строку плана — тот же безопасный
принцип, что для мест: код+форма и пересечение слов профиля с именем программы,
предпочитая базовое высшее образование (актуальный стандарт 2026) и специфичный
профиль.
"""
import io
import json
import re
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

_PATH = Path(__file__).with_name("study_plans_2026.json")
_PLANS: Optional[List[dict]] = None
_STOP = {"направленность", "образование", "профиль", "выбору", "программа"}


def _words(s: str) -> set:
    return {w for w in re.findall(r"[а-яёa-z]{4,}", (s or "").lower()) if w not in _STOP}


def load_plans() -> List[dict]:
    global _PLANS
    if _PLANS is None:
        try:
            _PLANS = json.loads(_PATH.read_text(encoding="utf-8")).get("plans", [])
        except Exception:
            _PLANS = []
    return _PLANS


def _level_rank(level: str) -> int:
    """Приоритет уровня: базовое высшее (2026) выше старого бакалавриата."""
    lv = (level or "").lower()
    if "базовое высшее" in lv:
        return 2
    if "бакалавр" in lv or "специалитет" in lv:
        return 1
    return 0


def match_plan(code: str, form: str, name: str) -> Optional[dict]:
    """Строка учебного плана для программы каталога или None при неоднозначности.

    Профиль плана обычно совпадает с «хвостом» имени программы. Берём кандидата,
    чьи слова профиля — подмножество слов имени (или наоборот) и максимально
    специфичны; при равенстве — базовое высшее образование.
    """
    nm = _words(name)
    cands = [p for p in load_plans() if p["code"] == code and p.get("form") == form]
    scored = []
    for p in cands:
        pw = _words(p["profile"])
        if not pw:
            continue
        overlap = len(pw & nm)
        if overlap and (pw <= nm or nm <= pw):
            # ключ: пересечение, специфичность (меньше лишних слов), свежий уровень
            scored.append((overlap, -len(pw ^ nm), _level_rank(p["level"]), p))
    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    if len(scored) > 1 and scored[0][:2] == scored[1][:2] and \
            scored[0][2] == scored[1][2]:
        return None                      # честно неоднозначно — не угадываем
    return scored[0][3]


def _share_id(url: str) -> str:
    m = re.search(r"/s/([A-Za-z0-9]+)", url or "")
    return m.group(1) if m else ""


def by_share_id(sid: str) -> Optional[dict]:
    for p in load_plans():
        if _share_id(p.get("disc", "")) == sid:
            return p
    return None


def share_id(plan: dict) -> str:
    return _share_id(plan.get("disc", ""))


def find_by_text(query: str, limit: int = 6) -> List[dict]:
    """Кандидаты планов по свободному тексту (направление/профиль/код).

    Ранжируем по пересечению слов запроса со словами «направление + профиль»;
    при равенстве — базовое высшее образование и очная форма выше. Для показа
    кнопками, поэтому возвращаем несколько."""
    qw = _words(query)
    m = re.search(r"\d\d\.\d\d\.\d\d", query or "")
    code = m.group(0) if m else None
    scored = []
    for p in load_plans():
        if code and p["code"] != code:
            continue
        hay = _words(f"{p['napr']} {p['profile']}")
        overlap = len(qw & hay)
        if not overlap and not (code and not qw):
            continue
        form_rank = {"очная": 2, "очно-заочная": 1}.get(p.get("form"), 0)
        scored.append((overlap, _level_rank(p["level"]), form_rank, p))
    scored.sort(key=lambda t: t[:3], reverse=True)
    # убираем дубли по (код, профиль, форма), оставляя лучший уровень
    seen, out = set(), []
    for _o, _l, _f, p in scored:
        k = (p["code"], p["profile"], p["form"])
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
        if len(out) >= limit:
            break
    return out


def fetch_plan_pdf(plan: dict, timeout: int = 60) -> Optional[Tuple[bytes, str]]:
    """(байты PDF, имя файла) самого свежего года приёма или None."""
    import requests
    from scraper.fetchers.history_fetcher import _UA
    url = plan.get("disc", "").rstrip("/") + "/download"
    try:
        r = requests.get(url, headers=_UA, timeout=timeout)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
    except Exception:
        return None
    pdfs = [n for n in z.namelist() if n.lower().endswith(".pdf")]
    if not pdfs:
        return None

    def _year(n: str) -> str:
        m = re.search(r"(20\d\d)", n)
        return m.group(1) if m else "0"

    best = max(pdfs, key=_year)
    name = best.split("/")[-1] or "Учебный_план.pdf"
    try:
        return z.read(best), name
    except Exception:
        return None
