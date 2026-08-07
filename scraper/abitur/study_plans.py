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
from typing import Dict, List, Optional, Tuple

_PATH = Path(__file__).with_name("study_plans_2026.json")
_SEM_PATH = Path(__file__).with_name("study_plan_semesters_2026.json")
_PLANS: Optional[List[dict]] = None
_SEMS: Optional[dict] = None
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


def semesters_for(sid: str) -> List[dict]:
    """Предпарсенная разбивка [{index,name,semesters}] для плана по share_id."""
    global _SEMS
    if _SEMS is None:
        try:
            _SEMS = json.loads(_SEM_PATH.read_text(encoding="utf-8")).get("plans", {})
        except Exception:
            _SEMS = {}
    return _SEMS.get(sid, [])


def format_semesters(sid: str) -> Optional[str]:
    """Текст «дисциплины по семестрам» для плана или None, если данных нет."""
    rows = semesters_for(sid)
    if not rows:
        return None
    from collections import defaultdict
    bs: dict = defaultdict(list)
    for r in rows:
        for s in r["semesters"]:
            bs[s].append(r["name"])
    lines = ["📅 <b>Дисциплины по семестрам</b>", ""]
    for s in sorted(bs):
        lines.append(f"<b>Семестр {s}:</b>")
        lines += [f"  • {n}" for n in bs[s]]
        lines.append("")
    lines.append("Форма контроля и часы — в самом файле плана (📄).")
    return "\n".join(lines)


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
            # ключ: пересечение, специфичность (меньше лишних слов), свежий
            # уровень, свежий год приёма
            scored.append((overlap, -len(pw ^ nm), _level_rank(p["level"]),
                           p.get("year") or "", p))
    if not scored:
        return None
    scored.sort(key=lambda t: t[:4], reverse=True)
    if len(scored) > 1 and scored[0][:4] == scored[1][:4]:
        return None                      # честно неоднозначно — не угадываем
    return scored[0][4]


def _plan_url(plan: dict) -> str:
    """Ссылка на учебный план (самый свежий год приёма)."""
    return (plan.get("plan") or plan.get("disc") or "").strip()


def _share_id(url: str) -> str:
    m = re.search(r"/s/([A-Za-z0-9]+)", url or "")
    return m.group(1) if m else ""


def by_share_id(sid: str) -> Optional[dict]:
    for p in load_plans():
        if _share_id(_plan_url(p)) == sid:
            return p
    return None


def share_id(plan: dict) -> str:
    return _share_id(_plan_url(plan))


def share_url(plan: dict) -> str:
    return _plan_url(plan)


def _prof_key(profile: str) -> str:
    return re.sub(r"\s+", " ", (profile or "").lower()).strip()


def _family(plan: dict) -> str:
    """Ступень образования по коду ФГОС: 44.03.01 → «03».

    Средний сегмент кода задан официально: 02 — СПО, 03 — бакалавриат/базовое
    высшее, 04 — магистратура, 05 — специалитет, 06 — аспирантура. Сравнивать
    планы имеет смысл только внутри одной ступени: «Юриспруденция» существует
    и как 40.02.04 (СПО), и как 40.03.01 (высшее) — это разные программы, а не
    старая и новая версии одной.
    """
    parts = (plan.get("code") or "").split(".")
    return parts[1] if len(parts) > 1 else ""


def current_plans() -> List[dict]:
    """Планы без устаревших: по каждому профилю оставляем самый свежий год.

    МПГУ перенумеровал двухпрофильные программы — то, что в 2023 году было
    44.03.05 «высшее образование - бакалавриат», с 2026 идёт как 44.03.01
    «базовое высшее образование». Старые планы остались в каталоге, и
    дедупликация по (код, профиль, форма) их не убирала: код-то разный.
    Абитуриент видел в выборе две одинаковые с виду строки «Математика и
    Экономика (очная)» и мог открыть план 2023 года по программе, набора на
    которую больше нет. Так задваивались 24 профиля.
    """
    plans = load_plans()
    newest: Dict[tuple, str] = {}
    for p in plans:
        key = (_prof_key(p.get("profile") or ""), p.get("form"), _family(p))
        year = p.get("year") or ""
        if year > newest.get(key, ""):
            newest[key] = year
    out = []
    for p in plans:
        key = (_prof_key(p.get("profile") or ""), p.get("form"), _family(p))
        if (p.get("year") or "") >= newest[key]:
            out.append(p)
    return out


def latest_year() -> str:
    """Самый свежий год приёма в каталоге планов."""
    return max((p.get("year") or "" for p in load_plans()), default="")


def find_by_text(query: str, limit: int = 6) -> List[dict]:
    """Кандидаты планов по свободному тексту (направление/профиль/код).

    Ранжируем по пересечению слов запроса со словами «направление + профиль»;
    при равенстве — базовое высшее образование и очная форма выше. Для показа
    кнопками, поэтому возвращаем несколько."""
    qw = _words(query)
    m = re.search(r"\d\d\.\d\d\.\d\d", query or "")
    code = m.group(0) if m else None
    scored = []
    for p in current_plans():
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
    """(байты PDF, имя файла) самого свежего года приёма или None.

    Только stdlib (urllib): в окружении бота нет requests."""
    import urllib.request
    url = _plan_url(plan).rstrip("/") + "/download"   # _plan_url уже .strip()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MPGU-Abitur-Bot"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            content = r.read()
        z = zipfile.ZipFile(io.BytesIO(content))
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
