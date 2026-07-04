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


def main() -> int:
    from scraper.fetchers import lists_fetcher as LF
    from scraper.storage.git_storage import GitStorage

    pages, meta = LF.crawl()
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec="seconds")
    meta_doc, shards = build_index(pages, meta, updated_at=now)

    storage = GitStorage(os.environ.get("DATA_PATH", "data"))
    storage.write_lists_data(meta_doc, shards)
    storage.commit_and_push(f"lists: обновление индекса конкурсных списков ({now})")
    print(f"Списков: {len(meta_doc['lists'])}, кодов: {meta_doc['codes_total']}, "
          f"шардов: {len(shards)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
