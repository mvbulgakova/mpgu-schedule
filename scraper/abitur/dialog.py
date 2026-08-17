"""Конечный автомат диалога калькулятора доп. баллов (детерминированный)."""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from scraper.abitur import achievements as A
from scraper.abitur.calculator import CalcInput, CalcResult, calculate

STEP_LEVEL = "level"
STEP_PED = "pedagogical"
STEP_TARGET = "target"
STEP_ACHIEVE = "achieve"
STEP_SPORT = "sport"
STEP_DONE = "done"

# Порядок цикла для кнопки «Олимпиада»: нет → победитель → призёр → нет.
_OLYMP_CYCLE = {None: "winner", "winner": "prizer", "prizer": None}
# Цикл для конкурсов МПГУ (Прил. 3): нет → победитель → призёр II → призёр III → участник → нет.
_MPGU_CYCLE = {None: "winner", "winner": "prizer2", "prizer2": "prizer3",
               "prizer3": "participant", "participant": None}

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
    mpgu_contest: Optional[str] = None
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
        target_quota=s.target_quota, sport=s.sport, mpgu_contest=s.mpgu_contest,
        edu_honors=s.edu_honors,
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
    elif field_ == "olympcycle":
        s.olympiad = _OLYMP_CYCLE.get(s.olympiad, "winner")
    elif field_ == "mpgucycle":
        s.mpgu_contest = _MPGU_CYCLE.get(s.mpgu_contest, "winner")
    elif field_ == "sportmenu":
        s.step = STEP_SPORT
    elif field_ == "sport":
        s.sport = None if value == "none" else (value if value in A.SPORT else s.sport)
        s.step = STEP_ACHIEVE
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
    if s.step == STEP_SPORT:
        rows = [[(label, f"c:sport:{key}")] for key, (label, _) in A.SPORT.items()]
        rows.append([("✖️ Без спортивного достижения", "c:sport:none")])
        return View("🏅 Выберите ОДНО спортивное достижение (учитывается максимальное):", rows)
    if s.step == STEP_ACHIEVE:
        toggles = dict(TOGGLES_BASE)
        if s.level == "spec":
            toggles.update(TOGGLES_SPEC_EXTRA)
        rows = []
        for tid, label in toggles.items():
            mark = "✅ " if getattr(s, tid, False) else "▫️ "
            rows.append([(mark + label, f"c:toggle:{tid}")])
        olymp_label = {None: "не указана", "winner": "победитель (+10)",
                       "prizer": "призёр (+5)"}[s.olympiad]
        rows.append([(f"🏆 Олимпиада 10/5 (рег. ВсОШ и др.): {olymp_label}", "c:olympcycle:1")])
        mpgu_label = {None: "не указан", "winner": "победитель (+10)",
                      "prizer2": "призёр II (+8)", "prizer3": "призёр III (+6)",
                      "participant": "участник (+4)"}[s.mpgu_contest]
        rows.append([(f"🎓 Конкурс/олимпиада МПГУ: {mpgu_label}", "c:mpgucycle:1")])
        sport_label = A.SPORT[s.sport][0] if s.sport else "не указан"
        rows.append([(f"🏅 Спорт: {sport_label}", "c:sportmenu:1")])
        rows.append([("✔️ Посчитать", "c:done:1")])
        return View(
            "<b>Шаг 4/4.</b> Отметьте достижения и нажмите «Посчитать».\n"
            "Волонтёрство — просто пришлите число часов сообщением.\n\n"
            "ℹ️ <b>Подсказки:</b>\n"
            "• заключительный этап ВсОШ — это БВИ (без экзаменов), не баллы\n"
            "• перечневая олимпиада может дать БВИ или 100 баллов (при ЕГЭ ≥75) — "
            "тогда баллы ИД за неё не начисляются; отмечайте её здесь, только если "
            "особое право не используете\n"
            "• «Конкурс МПГУ» — олимпиады и конкурсы самого университета и "
            "педагогические конкурсы", rows)
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
