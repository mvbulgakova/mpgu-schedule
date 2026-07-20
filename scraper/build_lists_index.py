"""Сборка индекса конкурсных списков epk25 и запись в data-ветку.

Хранение шардированное (монолитный файл ~9 МБ не проходит через CDN):
  admissions/lists_meta.json      — метаданные списков + totals (для /shansy)
  admissions/by_code/<XX>.json    — позиции абитуриентов, шард по первым 2 цифрам кода

build_index — чистая (given HTML → (meta_doc, shards)).
"""
import datetime as dt
import os
from typing import Dict, List, Tuple

from scraper.parsers.competitive_list_parser import parse_view


def _shard_key(unique_code: str) -> str:
    c = "".join(ch for ch in unique_code if ch.isdigit()) or "0"
    return (c[:2] if len(c) >= 2 else c.zfill(2))


def simulate_admission(candidates: Dict[str, list],
                       places: Dict[str, int]) -> Dict[str, set]:
    """Отложенное зачисление (deferred acceptance) — как реальный алгоритм приёма.

    candidates: {person: [(priority, list_code, position), ...]} — только подавшие
    согласие, только общие бюджетные списки. places: {list_code: мест}.
    Каждый человек занимает место лишь в СВОЁМ ВЫСШЕМ проходном приоритете; кого
    вытеснили — пробует следующий. Возвращает {list_code: множество зачисленных}.
    """
    import heapq
    prefs = {p: sorted(cs) for p, cs in candidates.items() if cs}
    ptr = {p: 0 for p in prefs}
    held: Dict[str, list] = {lc: [] for lc in places}
    free = list(prefs)
    while free:
        p = free.pop()
        while ptr[p] < len(prefs[p]):
            _, lc, pos = prefs[p][ptr[p]]
            ptr[p] += 1
            cap = places.get(lc) or 0
            if cap <= 0:
                continue
            heapq.heappush(held[lc], (-pos, p))   # худший (наибольшая позиция) сверху
            if len(held[lc]) <= cap:
                break                              # закрепился здесь
            _, bumped = heapq.heappop(held[lc])
            if bumped != p:
                free.append(bumped)                # вытеснили другого — тот ищет дальше
                break
            # вытеснили нас самих — пробуем следующий приоритет
    return {lc: {person for _, person in h} for lc, h in held.items()}


def build_index(pages: Dict[str, str], meta: Dict[str, dict],
                updated_at: str, places_fn=None) -> Tuple[dict, Dict[str, dict]]:
    """Возвращает (meta_doc, shards): метаданные списков и шарды кодов.

    places_fn(meta_записи) -> бюджетные места программы (для тестов подменяемо;
    по умолчанию — матчинг из scraper.abitur.lists).
    """
    if places_fn is None:
        from scraper.abitur.lists import _places_for as places_fn

    lists: Dict[str, dict] = {}
    rows_by_list: Dict[str, list] = {}
    for code_list, html in pages.items():
        rows = sorted(parse_view(html), key=lambda r: r["position"])
        rows_by_list[code_list] = rows
        m = dict(meta.get(code_list, {}))
        m["count"] = len(rows)
        m["consented"] = sum(1 for r in rows if r.get("consent"))
        m["totals"] = sorted((r["score_total"] for r in rows
                              if r.get("score_total")), reverse=True)
        m.setdefault("url",
                     f"https://epk25.mpgu.su/competitive-list/view?code={code_list}")
        lists[code_list] = m

    # Общий конкурс = крупнейший бюджетный список направления+формы; ему ищем
    # места. Исключение — ручная привязка по коду списка (кампус-дубли вроде
    # Покровского филиала): такой список — свой отдельный общий конкурс.
    try:
        from scraper.abitur.lists import alias_list_codes
        aliased = alias_list_codes()
    except Exception:
        aliased = set()
    for lc, m in lists.items():
        if m.get("kind") != "бюджет":
            continue
        same = [x for x in lists.values()
                if x.get("kind") == "бюджет" and x.get("direction") == m.get("direction")
                and x.get("form") == m.get("form")]
        m["general"] = (lc in aliased
                        or (m["count"] or 0) >= max((x.get("count") or 0) for x in same))
        if m["general"]:
            m["places"] = places_fn(m)

    # Покрытие сопоставления: сколько общих бюджетных списков получили места из
    # каталога. Резкое падение = нечёткий матчинг сломался на новых данных
    # (тихий промах становится видимым — см. main() и вотчдог).
    gen_budget = [m for m in lists.values() if m.get("general")]
    matched = [m for m in gen_budget if m.get("places")]
    coverage = {"general_budget_lists": len(gen_budget),
                "with_places": len(matched),
                "match_rate": round(len(matched) / len(gen_budget), 3)
                if gen_budget else None}

    # Симуляция: только согласившиеся в общих бюджетных списках с известными местами.
    places = {lc: m["places"] for lc, m in lists.items()
              if m.get("general") and m.get("places")}
    candidates: Dict[str, list] = {}
    for lc in places:
        for r in rows_by_list[lc]:
            if r.get("consent"):
                candidates.setdefault(r["unique_code"], []).append(
                    (r.get("priority_pz") or 99, lc, r["position"]))
    admitted = simulate_admission(candidates, places)

    codes: Dict[str, list] = {}
    for code_list, rows in rows_by_list.items():
        adm = admitted.get(code_list)
        adm_positions = (sorted(r["position"] for r in rows
                                if r["unique_code"] in adm) if adm is not None else None)
        cons_cum = 0
        for r in rows:
            entry = {
                "list": code_list,
                "position": r["position"],
                "score_total": r["score_total"],
                "consent": r["consent"],
                "priority_pz": r["priority_pz"],
                "bvi": r["bvi"],
                "status": r["status"],
            }
            if code_list in places:
                entry["cons_above"] = cons_cum
                if adm_positions is not None:
                    import bisect
                    entry["sim_above"] = bisect.bisect_left(adm_positions, r["position"])
            if r.get("consent"):
                cons_cum += 1
            codes.setdefault(r["unique_code"], []).append(entry)

    meta_doc = {"updated_at": updated_at, "campaign": "2026",
                "lists": lists, "codes_total": len(codes), "coverage": coverage}
    shards: Dict[str, dict] = {}
    for ucode, entries in codes.items():
        sk = _shard_key(ucode)
        shards.setdefault(sk, {"updated_at": updated_at, "codes": {}})
        shards[sk]["codes"][ucode] = entries
    return meta_doc, shards


RETAIN = 0.85  # публиковать нельзя, если списков стало < 85% от прежних (неполный обход)


def _guard_incomplete(meta_doc: dict, stats: dict, prev):
    """Причина отказа в публикации, либо None если публиковать можно.

    Блокируем только при ПРИЗНАКАХ неполного обхода (сетевые сбои), а не при
    честном сокращении числа списков (квотные списки на epk25 открываются и
    закрываются по ходу кампании — падение количества само по себе нормально).
    """
    if stats.get("levels_failed"):
        return f"не прочитаны целые уровни: {stats['levels_failed']}"
    dt_total = stats.get("directions_total", 0)
    df = stats.get("directions_failed", 0)
    if dt_total and df > 0.10 * dt_total:
        return f"не прочитано направлений: {df}/{dt_total}"
    # Крупное падение числа списков засчитываем только вместе с сетевыми сбоями.
    new_n = len(meta_doc["lists"])
    if prev and (df or stats.get("views_failed")):
        old_n = len(prev.get("lists", {}))
        if old_n and new_n < RETAIN * old_n:
            return (f"списков {new_n} < {int(RETAIN * 100)}% от прежних {old_n} "
                    f"при сетевых сбоях")
    return None


def main() -> int:
    import json
    from scraper.fetchers import lists_fetcher as LF
    from scraper.storage.git_storage import GitStorage

    pages, meta, stats = LF.crawl()
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec="seconds")
    meta_doc, shards = build_index(pages, meta, updated_at=now)

    storage = GitStorage(os.environ.get("DATA_PATH", "data"))
    prev_path = storage.root / "admissions" / "lists_meta.json"
    prev = None
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
        except Exception:
            prev = None

    reason = _guard_incomplete(meta_doc, stats, prev)
    if reason and not os.environ.get("FORCE_PUBLISH"):
        print(f"ОТМЕНА публикации (защита от потери данных): {reason}. "
              f"Прежний индекс не тронут. stats={stats}. "
              f"Опубликовать принудительно: FORCE_PUBLISH=1.")
        return 1

    cov = meta_doc["coverage"]
    if cov["match_rate"] is not None and cov["match_rate"] < 0.6:
        print(f"⚠️ НИЗКОЕ ПОКРЫТИЕ мест: сопоставлено {cov['with_places']}/"
              f"{cov['general_budget_lists']} общих бюджетных списков "
              f"({int(cov['match_rate'] * 100)}%). Возможно, сломался матчинг "
              f"программ (новые названия/КЦП) — проверьте programs_2026.json.")

    storage.write_lists_data(meta_doc, shards)
    storage.commit_and_push(f"lists: обновление индекса конкурсных списков ({now})")
    print(f"Списков: {len(meta_doc['lists'])}, кодов: {meta_doc['codes_total']}, "
          f"шардов: {len(shards)}, покрытие мест: {cov['with_places']}/"
          f"{cov['general_budget_lists']} ({cov['match_rate']}), stats={stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
