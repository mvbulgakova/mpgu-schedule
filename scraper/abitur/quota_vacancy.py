"""Незанятые квотные места программы и предварительная оценка позиции.

Считаем только по данным, которые epk25 уже отдал явно (`kcp_epk`,
`enrolled` на квотных списках) — при неполных данных группы честно
пропускаем, а не занижаем/завышаем (тот же принцип, что и в
build_lists_index.quota_by_key — см. спек 2026-08-03).
"""
from typing import Dict, List, Optional, Tuple

Key = Tuple[Optional[str], Optional[str], Optional[str]]


def _key(m: dict) -> Key:
    return (m.get("direction"), m.get("form"), m.get("unit"))


def compute_group_vacancies(lists: Dict[str, dict]) -> Dict[Key, dict]:
    """{(direction, form, unit): {"vacant": int, "breakdown": [(vid_mest, kcp_epk, enrolled), ...]}}

    Только для групп квотных списков, где у ВСЕХ известны и kcp_epk, и
    enrolled, и суммарный vacant > 0.
    """
    groups: Dict[Key, list] = {}
    for m in lists.values():
        if not m.get("quota"):
            continue
        groups.setdefault(_key(m), []).append(m)

    result: Dict[Key, dict] = {}
    for key, members in groups.items():
        if any(m.get("kcp_epk") is None or m.get("enrolled") is None
               for m in members):
            continue
        vacant = sum(max(m["kcp_epk"] - m["enrolled"], 0) for m in members)
        if vacant <= 0:
            continue
        result[key] = {
            "vacant": vacant,
            "breakdown": [(m.get("vid_mest"), m["kcp_epk"], m["enrolled"])
                          for m in members],
        }
    return result


def general_list_for_key(lists: Dict[str, dict], key: Key) -> Optional[str]:
    """Код общего списка (main_kcp=True) для той же (direction, form, unit)."""
    for lc, m in lists.items():
        if m.get("main_kcp") and _key(m) == key:
            return lc
    return None
