"""Конечный автомат диалога калькулятора доп. баллов (детерминированный)."""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from scraper.abitur import achievements as A
from scraper.abitur.calculator import CalcInput, CalcResult, calculate

STEP_LEVEL = "level"
STEP_PED = "pedagogical"
STEP_TARGET = "target"
STEP_ACHIEVE = "achieve"
STEP_DONE = "done"

# Тумблеры-достижения, доступные на шаге достижений (id -> подпись кнопки).
TOGGLES_BASE = {
    "edu_honors": "Аттестат/диплом с отличием",
    "abilimpiks": "Абилимпикс",
    "svo": "СВО / добровольч. формирования",
    "do_profile": "ДО искусства/спорта по профилю",
}
TOGGLES_SPEC_EXTRA = {"patents": "Патент"}


@dataclass
class CalcSession:
    step: str = STEP_LEVEL
    level: Optional[str] = None
    pedagogical: bool = False
    target_quota: bool = False
    sport: Optional[str] = None
    edu_honors: bool = False
    abilimpiks: bool = False
    svo: bool = False
    do_profile: bool = False
    olympiad: Optional[str] = None
    volunteer_hours: int = 0
    publications: Optional[str] = None
    patents: bool = False
    fieb: Optional[str] = None
    premia: Optional[str] = None
    target_points: int = 0


@dataclass
class View:
    text: str
    keyboard: List[List[Tuple[str, str]]] = field(default_factory=list)


def start() -> CalcSession:
    return CalcSession()


def _to_input(s: CalcSession) -> CalcInput:
    return CalcInput(
        level=s.level or "base", pedagogical=s.pedagogical,
        target_quota=s.target_quota, sport=s.sport, edu_honors=s.edu_honors,
        abilimpiks=s.abilimpiks, svo=s.svo, do_profile=s.do_profile,
        olympiad=s.olympiad, volunteer_hours=s.volunteer_hours,
        publications=s.publications, patents=s.patents, fieb=s.fieb,
        premia=s.premia, target_points=s.target_points)


def compute(s: CalcSession) -> CalcResult:
    return calculate(_to_input(s))


def set_volunteer_hours(s: CalcSession, hours: int) -> CalcSession:
    s.volunteer_hours = max(0, int(hours))
    return s


def handle(s: CalcSession, data: str) -> Tuple[CalcSession, bool]:
    """Обрабатывает callback. Возвращает (session, done)."""
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "c":
        return s, False
    _, field_, value = parts

    if field_ == "level":
        s.level = value if value in A.LEVELS else "base"
        s.step = STEP_PED
    elif field_ == "pedagogical":
        s.pedagogical = (value == "1")
        s.step = STEP_TARGET
    elif field_ == "target":
        s.target_quota = (value == "1")
        s.step = STEP_ACHIEVE
    elif field_ == "toggle":
        if hasattr(s, value) and isinstance(getattr(s, value), bool):
            setattr(s, value, not getattr(s, value))
    elif field_ == "done":
        s.step = STEP_DONE
        return s, True
    return s, False


def render(s: CalcSession) -> View:
    if s.step == STEP_LEVEL:
        return View("Шаг 1/4. Выберите уровень обучения:", [
            [("БВО / бакалавриат / специалитет", "c:level:base")],
            [("СПВО / магистратура", "c:level:spec")]])
    if s.step == STEP_PED:
        return View("Шаг 2/4. Направление педагогическое (шифр 44.xx)?", [
            [("Да", "c:pedagogical:1"), ("Нет", "c:pedagogical:0")]])
    if s.step == STEP_TARGET:
        return View("Шаг 3/4. Поступаете на целевую квоту?", [
            [("Да", "c:target:1"), ("Нет", "c:target:0")]])
    if s.step == STEP_ACHIEVE:
        toggles = dict(TOGGLES_BASE)
        if s.level == "spec":
            toggles.update(TOGGLES_SPEC_EXTRA)
        rows = []
        for tid, label in toggles.items():
            mark = "✅ " if getattr(s, tid, False) else "▫️ "
            rows.append([(mark + label, f"c:toggle:{tid}")])
        rows.append([("✔️ Посчитать", "c:done:1")])
        return View(
            "Шаг 4/4. Отметьте достижения (волонтёрство — пришлите число часов сообщением), "
            "затем «Посчитать».\n\nℹ️ Победа/призёрство в ЗАКЛЮЧИТЕЛЬНОМ этапе ВсОШ — это "
            "право БВИ (поступление без экзаменов), а не баллы; здесь отмечайте региональный "
            "этап и перечневые олимпиады.", rows)
    return View("Готово.", [])


def result_text(r: CalcResult) -> str:
    lines = ["<b>Предварительный расчёт доп. баллов</b>", ""]
    for label, pts in r.breakdown:
        lines.append(f"• {label}: +{pts}")
    if not r.breakdown:
        lines.append("• достижения не отмечены")
    lines.append("")
    if r.capped:
        lines.append(f"Сумма {r.general_raw} превышает потолок — учтено {r.general_capped}.")
    if r.target_capped:
        lines.append(f"Целевые ИД: +{r.target_capped}")
    lines.append(f"<b>Итого: {r.total} балл(ов)</b>")
    lines.append("")
    lines.append("⚠️ Расчёт предварительный. Точный учёт — приёмной комиссией по "
                 "подтверждающим документам (волонтёрство — только верифицированные часы "
                 "в книжке волонтёра/dobro.ru). Перечень и документы — Приложения 2, 3, 7: "
                 "https://mpgu.su/postuplenie/normativno-pravovoe-obespechenie-priema/")
    return "\n".join(lines)
