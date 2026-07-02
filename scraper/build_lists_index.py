"""Сборка индекса конкурсных списков epk25 и запись в data-ветку.

build_index — чистая (given HTML → index). Точка входа main() выполняет обход и коммит.
"""
import datetime as dt
import os
from typing import Dict

from scraper.parsers.competitive_list_parser import parse_view


def build_index(pages: Dict[str, str], meta: Dict[str, dict], updated_at: str) -> dict:
    lists: Dict[str, dict] = {}
    codes: Dict[str, list] = {}
    for code_list, html in pages.items():
        rows = parse_view(html)
        m = dict(meta.get(code_list, {}))
        m["count"] = len(rows)
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
    return {"updated_at": updated_at, "campaign": "2026", "lists": lists, "codes": codes}


def main() -> int:
    from scraper.fetchers import lists_fetcher as LF
    from scraper.storage.git_storage import GitStorage

    # meta собираем параллельно обходу: код -> контекст направления.
    # Здесь простая версия — контекст берётся из view-страницы отдельно не парсится,
    # поэтому meta минимальна (url). Расширяемо: прокинуть контекст из crawl().
    pages = LF.crawl()
    meta = {code: {} for code in pages}
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec="seconds")
    index = build_index(pages, meta, updated_at=now)

    data_path = os.environ.get("DATA_PATH", "data")
    storage = GitStorage(data_path)
    storage.write_lists_index(index)
    storage.commit_and_push(f"lists: обновление индекса конкурсных списков ({now})")
    print(f"Списков: {len(index['lists'])}, кодов: {len(index['codes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
