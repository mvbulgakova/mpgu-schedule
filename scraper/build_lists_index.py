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


def build_index(pages: Dict[str, str], meta: Dict[str, dict],
                updated_at: str) -> Tuple[dict, Dict[str, dict]]:
    """Возвращает (meta_doc, shards): метаданные списков и шарды кодов."""
    lists: Dict[str, dict] = {}
    codes: Dict[str, list] = {}
    for code_list, html in pages.items():
        rows = parse_view(html)
        m = dict(meta.get(code_list, {}))
        m["count"] = len(rows)
        m["totals"] = sorted((r["score_total"] for r in rows
                              if r.get("score_total")), reverse=True)
        m.setdefault("url",
                     f"https://epk25.mpgu.su/competitive-list/view?code={code_list}")
        lists[code_list] = m
        for r in rows:
            codes.setdefault(r["unique_code"], []).append({
                "list": code_list,
                "position": r["position"],
                "score_total": r["score_total"],
                "consent": r["consent"],
                "priority_pz": r["priority_pz"],
                "bvi": r["bvi"],
                "status": r["status"],
            })

    meta_doc = {"updated_at": updated_at, "campaign": "2026",
                "lists": lists, "codes_total": len(codes)}
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

    storage.write_lists_data(meta_doc, shards)
    storage.commit_and_push(f"lists: обновление индекса конкурсных списков ({now})")
    print(f"Списков: {len(meta_doc['lists'])}, кодов: {meta_doc['codes_total']}, "
          f"шардов: {len(shards)}, stats={stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
