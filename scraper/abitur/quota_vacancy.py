"""Незанятые квотные места программы и предварительная оценка позиции.

Считаем только по данным, которые epk25 уже отдал явно (`kcp_epk`,
`enrolled` на квотных списках) — при неполных данных группы честно
пропускаем, а не занижаем/завышаем (тот же принцип, что и при расчёте
квот в build_lists_index.build_index() (переменная quota_by_key) —
см. спек 2026-08-03).
"""
import re
from typing import Dict, List, Optional, Tuple

Key = Tuple[Optional[str], Optional[str], Optional[str]]

_SLASH_WS_RE = re.compile(r"\s*/\s*")


def _norm_direction(direction: Optional[str]) -> Optional[str]:
    """Схлопнуть пробелы вокруг "/" в направленности для сопоставления.

    И epk25, и приказ переносят длинную направленность по словам
    построчно, и место переноса относительно "/" не стабильно между
    двумя списками одного и того же направления (или между epk25 и
    приказом) — иногда после склейки остаётся "…код/ Название", иногда
    "…код/Название". Только для СОПОСТАВЛЕНИЯ группировки, само поле
    direction в записи не трогаем.
    """
    if direction is None:
        return None
    return _SLASH_WS_RE.sub("/", direction)


def _key(m: dict) -> Key:
    return (_norm_direction(m.get("direction")), m.get("form"), m.get("unit"))


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


def vacancy_for_list(lists: Dict[str, dict], list_code: str) -> Optional[dict]:
    """Вакансии группы, к которой принадлежит ОБЩИЙ список list_code.

    Пересчитывает группировку заново (не кэш) — вызывающий (notify-скрипт)
    должен видеть самые свежие данные на момент отправки, а не отчётный снимок.
    """
    m = lists.get(list_code)
    if not m:
        return None
    return compute_group_vacancies(lists).get(_key(m))


def format_report(lists: Dict[str, dict]) -> str:
    """Текстовая таблица направлений с незанятыми квотными местами."""
    groups = compute_group_vacancies(lists)
    if not groups:
        return "Незанятых квотных мест не найдено."
    lines = []
    for key, info in sorted(groups.items(), key=lambda kv: -kv[1]["vacant"]):
        direction, form, unit = key
        general_code = general_list_for_key(lists, key)
        gm = lists.get(general_code, {}) if general_code else {}
        kcp = gm.get("kcp_epk")
        kcp_str = kcp if kcp is not None else "?"
        lines.append(f"{direction} | {form} | {unit or '-'} | "
                     f"список {general_code or '?'} | КЦП {kcp_str} | "
                     f"вакантно квот: {info['vacant']}")
        for vid, kcp_q, enrolled in info["breakdown"]:
            lines.append(f"    {vid}: {enrolled}/{kcp_q}")
    return "\n".join(lines)


def format_notification(pos: int, kcp: int, vacant: int, direction: str,
                        form: str, code: str) -> str:
    """Текст разового предупреждения подписчику общего списка.

    Явно помечен как прикидка (не гарантия) — те же формулировки, что и в
    prediction.format_prediction, чтобы не создавать ложной точности.
    """
    return (
        f"Предварительно: сейчас вы примерно {pos}-е из {kcp} (бюджет, "
        f"«{direction}», {form}). По квотам этого направления пока есть "
        f"незанятые места (~{vacant}) — по правилам они должны перейти в "
        f"общий конкурс, но ещё не добавлены. Если добавят, ориентировочно "
        f"вы будете ~{pos}-е из ~{kcp + vacant}.\n\n"
        f"Это предварительная прикидка по открытым данным, а не "
        f"официальная информация — точная позиция обновится в живом "
        f"списке. Следите: /spisok {code}"
    )


def seats_increased(baseline: Dict[str, dict],
                    current: Dict[str, dict]) -> Dict[str, dict]:
    """Общие списки, у которых КЦП вырос по сравнению с baseline.

    {list_code: {"direction":..., "form":..., "old": int, "new": int,
    "enrolled": int | None}} — только для списков с main_kcp=True, где
    kcp_epk известен в ОБОИХ снимках и вырос. Рост КЦП общего списка после
    начала обработки приказа о зачислении означает возврат невостребованных
    квотных мест (БВИ поступают напрямую в тот же КЦП, а не в отдельную
    квоту, и на рост не влияют) — но мы не гадаем о причине, просто честно
    фиксируем факт: было/стало. enrolled (Зачислено, текущий снимок) — уже
    занятые из НОВОГО кцп, если поле известно, иначе None.
    """
    result: Dict[str, dict] = {}
    for code, cur in current.items():
        if not cur.get("main_kcp"):
            continue
        base = baseline.get(code)
        if not base:
            continue
        old = base.get("kcp_epk")
        new = cur.get("kcp_epk")
        if old is None or new is None or new <= old:
            continue
        result[code] = {
            "direction": cur.get("direction"),
            "form": cur.get("form"),
            "old": old,
            "new": new,
            "enrolled": cur.get("enrolled"),
        }
    return result


_QUOTA_KINDS = ("особая", "целевая", "отдельная")


def seats_increased_from_order(baseline: Dict[str, dict],
                               order_records: List[dict]) -> Dict[str, dict]:
    """То же, что seats_increased(), но источник — официальный приказ
    (order_records из enrollment_order.parse_order_pdf_text, объединённые
    из файлов особая/целевая/отдельная квота + БВИ), а не поле enrolled у
    epk25. Доступно для ЛЮБОГО направления, упомянутого в приказе — не
    только тех, что epk25 уже пересчитал.
    """
    # Группируем order_records по ключу (direction, form, unit).
    by_key: Dict[Key, Dict[str, int]] = {}
    for rec in order_records:
        key = _key(rec)
        counts = by_key.setdefault(key, {})
        kind = rec.get("quota_kind")
        counts[kind] = counts.get(kind, 0) + rec.get("count", 0)

    # Группируем квотные списки baseline по тому же ключу.
    quota_groups: Dict[Key, list] = {}
    for m in baseline.values():
        if not m.get("quota"):
            continue
        quota_groups.setdefault(_key(m), []).append(m)

    result: Dict[str, dict] = {}
    for code, m in baseline.items():
        if not m.get("main_kcp"):
            continue
        old = m.get("kcp_epk")
        if old is None:
            continue
        key = _key(m)
        if key not in by_key:
            # Приказ вообще ни разу не упомянул этот ключ — это НЕИЗВЕСТНО,
            # а не ноль (см. unmatched_order_keys() для диагностики того,
            # сколько таких ключей реально накапливается из-за расхождений
            # в написании direction/unit между epk25 и приказом).
            continue

        quota_members = quota_groups.get(key, [])
        if any(qm.get("kcp_epk") is None for qm in quota_members):
            # Квотные списки для ключа ЕСТЬ, но хотя бы у одного kcp_epk не
            # распарсился — это другой случай: не "квот нет", а "квоты есть,
            # но данные неполные", поэтому пропускаем группу целиком, а не
            # угадываем.
            continue
        # Пустой quota_members (после фильтра выше) — законный ноль: для
        # этого ключа в baseline вообще нет квотных списков (направление
        # без отдельной/особой/целевой квоты), а не "неизвестно".
        quota_kcp_sum = sum(qm["kcp_epk"] for qm in quota_members)

        counts = by_key[key]
        quota_enrolled = sum(counts.get(kind, 0) for kind in _QUOTA_KINDS)

        vacant = quota_kcp_sum - quota_enrolled
        if vacant <= 0:
            continue
        new = old + vacant
        # Намеренно не None (в отличие от enrolled в seats_increased()):
        # раз ключ уже найден в приказе, отсутствие записей БВИ для него —
        # подтверждённый ноль из документа, а не неизвестность. Это именно
        # "занято по БВИ на сейчас", а не итоговая занятость общего конкурса
        # — приём по общему конкурсу оформляется отдельным, более поздним
        # приказом и в этой цифре не учитывается.
        enrolled = counts.get("бви", 0)

        result[code] = {
            "direction": m.get("direction"),
            "form": m.get("form"),
            "old": old,
            "new": new,
            "enrolled": enrolled,
        }
    return result


def unmatched_order_keys(baseline: Dict[str, dict],
                         order_records: List[dict]) -> List[tuple]:
    """Ключи (direction, form, unit) из order_records, которых нет НИ СРЕДИ
    main_kcp, НИ СРЕДИ quota списков baseline — то есть приказ упомянул
    направление, а epk25-снимок его вообще не узнал (например, из-за
    сокращённого названия на epk25 — см. list_aliases_2026.json). Чисто
    диагностика, для ручного просмотра перед отправкой — не используется
    в самой рассылке.
    """
    baseline_keys = {_key(m) for m in baseline.values()}
    order_keys = {_key(rec) for rec in order_records}
    return sorted(order_keys - baseline_keys)


def format_seats_increased(old: int, new: int, direction: str, form: str,
                           code: str, enrolled: Optional[int] = None) -> str:
    """Текст факта: на направлении стало больше бюджетных мест.

    В отличие от format_notification, это НЕ прикидка — сообщение
    отправляется только после того, как рост kcp_epk уже подтверждён
    в живых данных epk25 (см. seats_increased). enrolled (Зачислено) —
    добавляется строкой про занятость, только если значение известно;
    при None ничего не выдумываем и строку не показываем.
    """
    occupancy = ""
    if enrolled is not None:
        occupancy = f"Уже зачислено: {enrolled} из {new}, свободно: {new - enrolled}.\n\n"
    return (
        f"📈 На вашем направлении стало больше бюджетных мест: было {old}, "
        f"теперь {new} (+{new - old}) — вернулись невостребованные места "
        f"по квотам. «{direction}», {form}.\n\n"
        f"{occupancy}"
        f"Актуальную позицию смотрите: /spisok {code}"
    )
