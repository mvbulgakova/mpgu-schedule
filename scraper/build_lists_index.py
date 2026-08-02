"""Сборка индекса конкурсных списков epk25 и запись в data-ветку.

Хранение шардированное (монолитный файл ~9 МБ не проходит через CDN):
  admissions/lists_meta.json      — метаданные списков + totals (для /shansy)
  admissions/by_code/<XX>.json    — позиции абитуриентов, шард по первым 2 цифрам кода

build_index — чистая (given HTML → (meta_doc, shards)).
"""
import datetime as dt
import os
from typing import Dict, List, Optional, Tuple

import re

from scraper.parsers.competitive_list_parser import parse_view

# epk25 публикует КЦП конкретного списка прямо на странице — это самое надёжное
# число мест (у списка «основные места в рамках КЦП» оно уже за вычетом квот,
# т.к. квоты — отдельные списки). Совпадает с тем, что видит абитуриент.
_KCP_RE = re.compile(r"Контрольные цифры при[её]ма:\s*(\d+)")
# «Вид мест» отличает общий конкурс от квотных списков, а «Учебное структурное
# подразделение» — головной кампус от филиалов (у филиала свой КЦП и свой
# конкурс, но одинаковое с кампусом название направления).
_VID_RE = re.compile(r"Вид мест:\s*([^\r\n]{0,80})")
_UNIT_RE = re.compile(r"Учебное структурное подразделение:\s*([^\r\n]{0,80})")


def _flat(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "")


def _parse_kcp(html: str):
    m = _KCP_RE.search(_flat(html))
    return int(m.group(1)) if m else None


def _parse_field(html: str, rx) -> Optional[str]:
    m = rx.search(_flat(html))
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def _is_main_kcp(vid: Optional[str]) -> bool:
    """«основные места в рамках КЦП» = общий конкурс (квоты — отдельные виды)."""
    return bool(vid) and "основные места" in vid.lower()


def _is_quota(vid: Optional[str]) -> bool:
    """Особая / отдельная / целевая квота — это тоже БЮДЖЕТНЫЕ места."""
    return bool(vid) and "квота" in vid.lower()


def _kind_from_vid(vid: Optional[str]) -> Optional[str]:
    """Вид мест со страницы → бюджет/платное.

    Ссылки на карточке направления не различают квотные списки, и они
    приезжали как «платное»: льготник видел свою квотную позицию помеченной
    платной. «Вид мест» снимает эту неоднозначность.
    """
    if not vid:
        return None
    v = vid.lower()
    if "платн" in v or "договор" in v:
        return "платное"
    if _is_quota(v) or "основные места" in v or "бюджет" in v:
        return "бюджет"
    return None


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
        kcp = _parse_kcp(html)
        if kcp is not None:
            m["kcp_epk"] = kcp
        vid = _parse_field(html, _VID_RE)
        if vid:
            m["vid_mest"] = vid
            m["main_kcp"] = _is_main_kcp(vid)
            m["quota"] = _is_quota(vid)
            kind = _kind_from_vid(vid)
            if kind:
                m["kind"] = kind          # вид мест точнее ссылки на карточке
        unit = _parse_field(html, _UNIT_RE)
        if unit:
            m["unit"] = unit
        lists[code_list] = m

    # Общий конкурс определяем ФАКТОМ со страницы: «Вид мест: основные места в
    # рамках КЦП». Прежняя эвристика «крупнейший список направления+формы»
    # ошибалась на филиалах: у Покровского/Дербентского/Ставропольского то же
    # название направления, но свой КЦП и свой конкурс — и они помечались
    # «квотными», из-за чего их абитуриенты не видели ни места, ни позиции.
    # Фолбэк (если epk25 не отдал «Вид мест») — прежняя эвристика + привязки.
    try:
        from scraper.abitur.lists import alias_list_codes
        aliased = alias_list_codes()
    except Exception:
        aliased = set()
    # Сумма квотных мест программы (особая + отдельная + целевая) по соседним
    # спискам epk25 — того же направления, формы и подразделения. Если вуз не
    # заполнил КЦП хотя бы у ОДНОГО квотного списка группы, сумма ненадёжна
    # (может занизить реальные квоты) — не считаем её вовсе для всей группы,
    # а не молча используем частичную (иначе «85 − известные 23» может выйти
    # 0 или отрицательным числом мест, хотя реальных данных просто не хватает).
    quota_by_key: Dict[tuple, int] = {}
    incomplete_keys = set()
    for m in lists.values():
        if not m.get("quota"):
            continue
        key = (m.get("direction"), m.get("form"), m.get("unit"))
        if m.get("kcp_epk") is None:
            incomplete_keys.add(key)
            continue
        quota_by_key[key] = quota_by_key.get(key, 0) + m["kcp_epk"]
    for key in incomplete_keys:
        quota_by_key.pop(key, None)

    for lc, m in lists.items():
        if m.get("kind") != "бюджет":
            continue
        qs = quota_by_key.get((m.get("direction"), m.get("form"), m.get("unit")))
        if qs is not None:
            m["quota_seats"] = qs
        if "main_kcp" in m:
            m["general"] = bool(m["main_kcp"])
        else:
            same = [x for x in lists.values()
                    if x.get("kind") == "бюджет"
                    and x.get("direction") == m.get("direction")
                    and x.get("form") == m.get("form")]
            m["general"] = (lc in aliased
                            or (m["count"] or 0) >= max((x.get("count") or 0)
                                                        for x in same))
        if m["general"]:
            # КЦП со страницы epk25 — авторитетнее каталога (у списка «основные
            # места» это уже общий конкурс).
            if m.get("kcp_epk") is not None:
                m["places"] = m["kcp_epk"]
                m["kcp_from_epk"] = True
            else:
                # Вуз не заполнил КЦП на странице — считаем по каталогу:
                # общий конкурс = КЦП − ВСЕ квоты (особая + отдельная + целевая).
                # Квоты берём из соседних квотных списков epk25: в каталоге
                # целевой нет, и без неё общий конкурс завышался (85−18=67
                # вместо 85−23=62).
                full = places_fn(m)
                if full and m.get("quota_seats") is not None:
                    m["places"] = max(full - m["quota_seats"], 0)
                    m["places_from_catalog"] = True
                else:
                    m["places"] = full

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

    # Сигналы для прогноза проходного-2026 (см. scraper.abitur.prediction):
    #   sim_cutoff — минимальный балл среди зачисленных в симуляции (живой пол);
    #   general_seats — места общего конкурса (КЦП − квоты);
    #   cap — G-й сверху балл среди всех подавших (верхний сценарий).
    try:
        from scraper.abitur.lists import _quota_for
    except Exception:  # noqa: BLE001
        _quota_for = lambda m: None            # noqa: E731
    for lc, cap_places in places.items():
        m = lists[lc]
        adm = admitted.get(lc) or set()
        adm_scores = [r["score_total"] for r in rows_by_list[lc]
                      if r["unique_code"] in adm and r.get("score_total")]
        m["sim_cutoff"] = min(adm_scores) if adm_scores else None
        if m.get("kcp_from_epk"):
            seats = cap_places            # КЦП epk25 — уже общий конкурс
        else:
            quota = _quota_for(m) or 0
            seats = max(cap_places - quota, 0) or cap_places
        m["general_seats"] = seats
        totals = m.get("totals") or []
        if totals and seats:
            m["cap"] = totals[seats - 1] if len(totals) >= seats else totals[-1]

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

    Блокируем при ПРИЗНАКАХ неполного обхода (сетевые сбои), а не при честном
    сокращении числа списков (квотные списки на epk25 открываются и закрываются
    по ходу кампании — падение количества само по себе нормально).
    """
    if stats.get("levels_failed"):
        return f"не прочитаны целые уровни: {stats['levels_failed']}"
    dt_total = stats.get("directions_total", 0)
    df = stats.get("directions_failed", 0)
    if dt_total and df > 0.10 * dt_total:
        return f"не прочитано направлений: {df}/{dt_total}"
    # Живой инцидент 29.07: epk25 под нагрузкой отдавал HTTP 200 с ПОЛНОСТЬЮ
    # валидной, но урезанной таблицей (сервер сам вернул часть строк) —
    # сетевой уровень ошибки не видит (views_failed=0), но codes_total
    # обрушился 27470→2097 и разошёлся с Госуслугами: абитуриенты, реально
    # состоящие в списках, увидели «вас больше нет». Число СПИСКОВ (667) при
    # этом не изменилось — прежняя проверка (по len(lists)) слепа к этому
    # классу порчи. Сравниваем сами КОДЫ безусловно, без привязки к stats.
    new_codes = meta_doc.get("codes_total", 0)
    old_codes = (prev or {}).get("codes_total")
    if old_codes and new_codes < RETAIN * old_codes:
        return (f"кодов {new_codes} < {int(RETAIN * 100)}% от прежних {old_codes} "
                f"— похоже на урезанные страницы (сайт под нагрузкой отдал "
                f"валидный, но неполный HTML), а не честное сокращение")
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
