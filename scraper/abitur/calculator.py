"""Чистый детерминированный расчёт доп. баллов. LLM здесь не участвует."""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from scraper.abitur import achievements as A


@dataclass
class CalcInput:
    level: str                       # "base" | "spec"
    pedagogical: bool                # направление 44.xx
    target_quota: bool               # поступление на целевую квоту
    sport: Optional[str]             # ключ A.SPORT или None (один вид)
    edu_honors: bool
    abilimpiks: bool
    svo: bool
    do_profile: bool
    olympiad: Optional[str]          # "winner" | "prizer" | None
    mpgu_contest: Optional[str] = None   # ключ A.MPGU_CONTEST или None
    volunteer_hours: int = 0         # 0 = нет
    publications: Optional[str] = None   # spec: "one" | "multi" | None
    patents: bool = False                # spec
    fieb: Optional[str] = None           # spec: "gold" | "silver" | None
    premia: Optional[str] = None         # spec: "federal" | "regional" | None
    target_points: int = 0               # целевые ИД (профориентация), сырые


@dataclass
class CalcResult:
    breakdown: List[Tuple[str, int]] = field(default_factory=list)
    general_raw: int = 0
    general_capped: int = 0
    target_capped: int = 0
    total: int = 0
    capped: bool = False


def calculate(inp: CalcInput) -> CalcResult:
    items: List[Tuple[str, int]] = []

    if inp.sport and inp.sport in A.SPORT:
        label, pts = A.SPORT[inp.sport]
        items.append((label, pts))

    if inp.edu_honors:
        items.append((A.FLAT_10["edu_honors"], 10))
    if inp.abilimpiks:
        items.append((A.FLAT_10["abilimpiks"], 10))
    if inp.svo:
        items.append((A.FLAT_10["svo"], 10))
    if inp.do_profile:
        items.append((A.FLAT_10["do_profile"], 10))

    if inp.olympiad in A.OLYMPIAD:
        label, pts = A.OLYMPIAD[inp.olympiad]
        items.append((label, pts))

    if inp.mpgu_contest in A.MPGU_CONTEST:
        label, pts = A.MPGU_CONTEST[inp.mpgu_contest]
        items.append((label, pts))

    vp = A.volunteer_points(inp.level, inp.pedagogical, inp.volunteer_hours)
    if vp:
        items.append((f"Волонтёрство ({inp.volunteer_hours} ч)", vp))

    if inp.level == "spec":
        if inp.publications in A.PUBLICATIONS:
            label, pts = A.PUBLICATIONS[inp.publications]
            items.append((label, pts))
        if inp.patents:
            items.append((A.PATENTS_LABEL, A.PATENTS_POINTS))
        if inp.fieb in A.FIEB:
            label, pts = A.FIEB[inp.fieb]
            items.append((label, pts))
        if inp.premia in A.PREMIA:
            label, pts = A.PREMIA[inp.premia]
            items.append((label, pts))

    general_raw = sum(p for _, p in items)
    general_capped = min(general_raw, A.GENERAL_CAP)
    target_capped = min(inp.target_points, A.TARGET_CAP) if inp.target_quota else 0

    return CalcResult(
        breakdown=items,
        general_raw=general_raw,
        general_capped=general_capped,
        target_capped=target_capped,
        total=general_capped + target_capped,
        capped=general_raw > A.GENERAL_CAP,
    )
