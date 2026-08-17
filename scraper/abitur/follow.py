"""Подписка «следи за моим кодом»: хранение подписок и дифф позиций в списках.

Хранение — локальный JSON-файл (в проде переживает рестарты через actions/cache,
НЕ в публичной data-ветке: связка chat_id ↔ код заявления не должна быть публичной).
Формат: {chat_id: {"code": str, "last": {list_code: position}, "updated_at": str}}
"""
import json
from pathlib import Path
from typing import Dict, List, Optional


def load(path) -> Dict[str, dict]:
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save(path, subs: Dict[str, dict]):
    Path(path).write_text(json.dumps(subs, ensure_ascii=False), encoding="utf-8")


def positions_of(entries: List[dict]) -> Dict[str, int]:
    return {e["list"]: e["position"] for e in entries}


def diff_text(code: str, old: Dict[str, int], new_entries: List[dict],
              meta: Optional[dict]) -> Optional[str]:
    """Текст уведомления об изменениях позиций; None, если изменений нет.

    Упоминаются только изменившиеся/новые/исчезнувшие списки.

    Списки, по которым зачисление уже проведено, молчат. Место в них
    продолжает шевелиться, но ничего не значит: 2026-08-07 epk25 переписал
    страницы в 08:00, и в списке 000000538 сдвинулись 60 человек из 2753 —
    при том, что состав не изменился ни на одного человека, баллы не
    изменились ни у кого, согласия тоже, а состав групп с равными баллами
    совпал полностью. То есть вуз просто иначе разложил людей ВНУТРИ равных
    баллов. Абитуриент получал «место 1371 → 1372 ⬇️» и пугался, хотя мест
    уже нет и конкурса нет.
    """
    from scraper.abitur import lists as L
    lists_meta = (meta or {}).get("lists") or {}

    def is_live(lc: str) -> bool:
        # Незнакомый список считаем живым: молча проглотить изменение хуже,
        # чем лишний раз сказать.
        return lc not in lists_meta or not L.enrollment_done(lists_meta[lc])

    new = {lc: p for lc, p in positions_of(new_entries).items() if is_live(lc)}
    old = {lc: p for lc, p in (old or {}).items() if is_live(lc)}
    if new == old:
        return None
    lines = [f"🔔 Списки обновились — код <b>{code}</b>:"]
    for lc, pos in new.items():
        label = L._list_label(meta, lc)
        if lc not in old:
            lines.append(f"• {label}: вы появились в списке — место {pos}")
        elif old[lc] != pos:
            arrow = "⬆️" if pos < old[lc] else "⬇️"
            lines.append(f"• {label}: место {old[lc]} → <b>{pos}</b> {arrow}")
    for lc, pos in old.items():
        if lc not in new:
            label = L._list_label(meta, lc)
            lines.append(f"• {label}: вас больше нет в этом списке")
    if len(lines) == 1:  # разница была только в составе ключей с теми же позициями
        return None
    # Когда списки пересчитал ВУЗ — а не когда мы сходили проверить. Наш обход
    # идёт каждые несколько минут и сам по себе ничего не значит; человеку важно,
    # к какому моменту относится его новое место. И считаем по ЕГО спискам:
    # epk25 переписывает их волнами, глобальный максимум показал бы отметку
    # чужого списка (см. lists.source_updated_for).
    src = L.source_updated_for(meta, set(new) | set(old))
    if src:
        lines.append(f"Списки на epk25 обновлены: {L._hhmm_dd_mm(src)}")
    lines.append(f"Подробнее: /spisok {code}")
    return "\n".join(lines)
