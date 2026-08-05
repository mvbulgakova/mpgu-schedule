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
    """
    from scraper.abitur import lists as L
    new = positions_of(new_entries)
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
    # к какому моменту относится его новое место.
    src = L.source_updated_at(meta)
    if src:
        lines.append(f"Списки на epk25 обновлены: {L._hhmm_dd_mm(src)}")
    lines.append(f"Подробнее: /spisok {code}")
    return "\n".join(lines)
