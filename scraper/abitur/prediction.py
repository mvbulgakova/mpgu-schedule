"""Примерный проходной-2026: честный диапазон из истории + живой картины.

Три реальных сигнала (без «чёрного ящика»), см. спек 2026-07-21:
  hist — проходные последних лет (осевшее число, лучший предиктор);
  sim  — минимум среди зачисленных в симуляции по согласиям (нижняя граница
         сегодня, растёт к 5 августа);
  cap  — G-й сверху балл среди подавших (верхний сценарий «если сильнейшие
         останутся»). В диапазон НЕ берём: завышает — часть уходит в другие
         вузы. Показываем справочно.

Диапазон [min(hist) … max(hist, sim)]. Нет истории → диапазон не даём,
показываем только живые сигналы. Нет ни истории, ни живых → ничего.
"""
from typing import Optional, Tuple


def _recent(hist: Optional[dict]) -> list:
    """Последние до 3 лет (2021+) как [(год, балл)], по возрастанию года."""
    if not hist:
        return []
    ys = sorted((y for y in hist if int(y) >= 2021), key=int)[-3:]
    return [(y, hist[y]) for y in ys]


def predict_range(hist: Optional[dict], sim: Optional[int]) -> Optional[Tuple[int, int]]:
    """(lo, hi) ориентира проходного или None, если нет свежей истории.

    lo — минимум проходных последних лет (проходной редко падает ниже).
    hi — максимум из тех же лет и текущего живого пола sim (если год идёт
    горячее прошлых, sim поднимет верх диапазона)."""
    recent = _recent(hist)
    if not recent:
        return None
    vals = [s for _, s in recent]
    lo = min(vals)
    hi = max(vals + ([sim] if sim else []))
    return (lo, hi)


def format_prediction(hist: Optional[dict], sim: Optional[int] = None,
                      cap: Optional[int] = None,
                      seats: Optional[int] = None) -> Optional[str]:
    """Единый блок «проходной» для абитуриента (plain text, годится и в HTML).

    Свежая история (2021+) есть → диапазон-ориентир + годы + живые сигналы.
    Только допандемийная история → показываем её приглушённо (без диапазона).
    Истории нет, но есть живые данные → только они. Ничего → None.
    """
    recent = _recent(hist)
    rng = predict_range(hist, sim)
    lines = []
    if rng:
        lo, hi = rng
        head = f"~{lo}" if lo == hi else f"~{lo}–{hi}"
        lines.append(f"📊 Примерный проходной-2026: ориентир {head}")
        lines.append("   • в прошлые годы: "
                     + ", ".join(f"{y}: {s}" for y, s in recent))
    elif hist:                                    # только старые годы (до 2021)
        old = sorted(hist, key=int)[-2:]
        lines.append("📊 Проходной (данные до 2021, сейчас конкурс выше): "
                     + ", ".join(f"{y}: {hist[y]}" for y in old))
    elif sim or cap:
        lines.append("📊 Проходной-2026 (истории нет, только живые данные):")
    else:
        return None
    if sim:
        lines.append(f"   • сейчас по согласиям проходят от ~{sim} "
                     "(↑ вырастет к 5 августа)")
    if cap and seats:
        lines.append(f"   • топ-{seats} баллов среди подавших — от ~{cap} "
                     "(если сильнейшие останутся; часть уйдёт в другие вузы)")
    lines.append("   ⚠️ Прогноз, не гарантия. Точный проходной — после зачисления.")
    return "\n".join(lines)
