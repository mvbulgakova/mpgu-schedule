"""Сборка индекса конкурсных списков epk25 и запись в data-ветку.

Хранение шардированное (монолитный файл ~9 МБ не проходит через CDN):
  admissions/lists_meta.json      — метаданные списков + totals (для /shansy)
  admissions/by_code/<XX>.json    — позиции абитуриентов, шард по первым 2 цифрам кода

build_index — чистая (given HTML → (meta_doc, shards)).
"""
import datetime as dt
import os
from pathlib import Path
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
# Появляются на странице epk25 после того, как вуз обработал приказ о
# зачислении по этому списку. «Мест для зачисления» = КЦП минус уже
# зачисленные (открытые места), «Зачислено» — сколько уже зачислено именно
# по этому списку. «Дата и время обновления» — момент, когда САМА страница
# в последний раз пересчитывалась (не момент обхода нашим краулером) —
# нужно, чтобы понять, догнал ли epk25 конкретный подписанный приказ.
_SEATS_OPEN_RE = re.compile(r"Мест для зачисления:\s*(\d+)")
_ENROLLED_RE = re.compile(r"Зачислено:\s*(\d+)")
_UPDATED_RE = re.compile(
    r"Дата и время обновления:\s*(\d{2})\.(\d{2})\.(\d{4})\.\s*(\d{2}):(\d{2})")


def _flat(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "")


def _parse_kcp(html: str):
    m = _KCP_RE.search(_flat(html))
    return int(m.group(1)) if m else None


def _parse_field(html: str, rx) -> Optional[str]:
    m = rx.search(_flat(html))
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def _parse_int_field(html: str, rx) -> Optional[int]:
    m = rx.search(_flat(html))
    return int(m.group(1)) if m else None


def _parse_updated_at(html: str) -> Optional[str]:
    m = _UPDATED_RE.search(_flat(html))
    if not m:
        return None
    day, month, year, hour, minute = (int(x) for x in m.groups())
    try:
        return dt.datetime(year, month, day, hour, minute,
                           tzinfo=dt.timezone(dt.timedelta(hours=3))
                           ).isoformat(timespec="seconds")
    except ValueError:
        # epk25 иногда отдаёт незаполненную дату-плейсхолдер (00.00.0000. 00:00) —
        # деградируем в «неизвестно», как и для любого другого опционального поля,
        # а не роняем build_index на всей выгрузке из-за одной плохой страницы.
        return None


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


def parse_pages(pages: Dict[str, str],
                meta: Dict[str, dict]) -> Dict[str, dict]:
    """{код списка: {"rows": [...], "meta": {...}}} — разбор HTML без сборки.

    Отделено от build_index, чтобы обход можно было разложить по нескольким
    раннерам: epk25 режет число одновременных соединений с одного IP (см.
    .github/workflows/fetch-lists.yml), поэтому каждый раннер снимает свою
    часть списков и отдаёт уже разобранные строки, а сборка индекса —
    отдельным шагом над объединённым результатом. HTML между шагами не
    таскаем: он на порядок тяжелее разобранных строк.
    """
    out: Dict[str, dict] = {}
    for code_list, html in pages.items():
        rows = sorted(parse_view(html), key=lambda r: r["position"])
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
        seats_open = _parse_int_field(html, _SEATS_OPEN_RE)
        if seats_open is not None:
            m["seats_open"] = seats_open
        enrolled = _parse_int_field(html, _ENROLLED_RE)
        if enrolled is not None:
            m["enrolled"] = enrolled
        page_updated_at = _parse_updated_at(html)
        if page_updated_at is not None:
            m["page_updated_at"] = page_updated_at
        out[code_list] = {"rows": rows, "meta": m}
    return out


def build_index(pages: Dict[str, str], meta: Dict[str, dict],
                updated_at: str, places_fn=None,
                enrolled_elsewhere: Optional[set] = None) -> Tuple[dict, Dict[str, dict]]:
    """Возвращает (meta_doc, shards): метаданные списков и шарды кодов.

    places_fn(meta_записи) -> бюджетные места программы (для тестов подменяемо;
    по умолчанию — матчинг из scraper.abitur.lists).

    enrolled_elsewhere — коды абитуриентов, уже зачисленных официальным
    приказом (квота/БВИ) НЕ в общем конкурсе (см.
    scraper.fetchers.enrollment_order_fetcher). Конкурсные списки epk25 не
    убирают таких людей из общего списка сами — без этого исключения
    симуляция продолжает считать их живыми конкурентами общего конкурса и
    занижает шансы тех, кто реально идёт следом (см. 2026-08-05: код
    1319710 зачислен по квоте 03.08, но остаётся в списке 602 с consent=true
    и без него отъедал бы место у кандидата на позиции 551 в симуляции).
    """
    return build_index_from_parsed(parse_pages(pages, meta), updated_at,
                                   places_fn, enrolled_elsewhere)


def build_index_from_parsed(parsed: Dict[str, dict], updated_at: str,
                            places_fn=None,
                            enrolled_elsewhere: Optional[set] = None
                            ) -> Tuple[dict, Dict[str, dict]]:
    """То же, что build_index, но поверх уже разобранных страниц (parse_pages).

    Нужна, когда обход разложен по нескольким раннерам: каждый отдаёт свою
    часть parse_pages, а индекс собирается один раз над объединённым словарём.
    Симуляция глобальная — считать её по частям нельзя, только над всем сразу.
    """
    enrolled_elsewhere = enrolled_elsewhere or set()
    if places_fn is None:
        from scraper.abitur.lists import _places_for as places_fn

    lists = {lc: p["meta"] for lc, p in parsed.items()}
    rows_by_list = {lc: p["rows"] for lc, p in parsed.items()}

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
    # Ёмкость для симуляции — «Мест для зачисления» (seats_open) со страницы
    # epk25, а не полный КЦП: seats_open — это КЦП МИНУС уже зачисленные
    # приказом, т.е. буквально сколько мест разыгрывается прямо сейчас.
    # Проверено 2026-08-05 на живых данных: на бакалавриате число официальных
    # отметок ВПП совпадает с seats_open на 97 списках из 99, а с полным КЦП —
    # только на 70. Раздавая полный КЦП, симуляция зачисляла лишних людей на
    # верхние приоритеты, те переставали конкурировать ниже, и ошибка
    # каскадом расходилась по всем спискам (см. 000000690: КЦП 22, реально
    # разыгрывается 19, зачислено приказом 3).
    sim_places = {lc: (m["seats_open"] if m.get("seats_open") is not None
                       else m["places"])
                  for lc, m in lists.items()
                  if m.get("general") and m.get("places")}
    # Живая отметка ВПП важнее приказа: приказ говорит, что человека зачислили
    # по квоте/БВИ, но он мог от этого зачисления отказаться и вернуться в
    # общий конкурс. Тогда epk25 снова ставит ему ВПП — а это уже факт «сейчас»,
    # а не намерение на дату приказа. Исключаем по приказу только тех, у кого
    # действующей отметки ВПП нет (2026-08-05: таких «вернувшихся» двое —
    # 1153448 и 1680192, и каждый был корнем цепочки ошибок на своём списке).
    # Считаем ТОЛЬКО общие бюджетные списки: отметки ВПП есть и на платных
    # (1558 штук на 2026-08-05), но платное место — не возвращение в бюджетный
    # общий конкурс, и по ним «возвращенцами» ошибочно становятся 27 человек
    # вместо двух, что само по себе портит симуляцию сильнее исходной ошибки.
    still_competing = {r["unique_code"] for lc in places
                       for r in rows_by_list[lc] if r.get("vpp")}
    excluded = enrolled_elsewhere - still_competing
    candidates: Dict[str, list] = {}
    for lc in places:
        for r in rows_by_list[lc]:
            if r.get("consent") and r["unique_code"] not in excluded:
                candidates.setdefault(r["unique_code"], []).append(
                    (r.get("priority_pz") or 99, lc, r["position"]))
    admitted = simulate_admission(candidates, sim_places)

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
        vpp_cum = 0
        for r in rows:
            entry = {
                "list": code_list,
                "position": r["position"],
                "score_total": r["score_total"],
                "consent": r["consent"],
                "priority_pz": r["priority_pz"],
                "bvi": r["bvi"],
                "status": r["status"],
                "vpp": r.get("vpp", False),
            }
            if code_list in places:
                entry["cons_above"] = cons_cum
                # vpp_above — сколько людей ВЫШЕ уже официально подтверждены
                # epk25 как проходящие (ВПП). В отличие от sim_above (наша
                # собственная симуляция каскада приоритетов) это авторитетная
                # цифра вуза — используем её как более точную, когда есть
                # (см. 2026-08-04: sim_above бывает заметно пессимистичнее
                # даже на свежих данных).
                entry["vpp_above"] = vpp_cum
                if adm_positions is not None:
                    import bisect
                    entry["sim_above"] = bisect.bisect_left(adm_positions, r["position"])
            if r.get("consent"):
                cons_cum += 1
            if r.get("vpp"):
                vpp_cum += 1
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


# Список считаем недостроенным, если он потерял больше половины строк. Меньше
# _COLLAPSE_MIN строк — не мерим: у крошечных списков доля скачет и без сбоев.
_COLLAPSE_MIN = 20
_COLLAPSE_RATIO = 0.5


def carry_forward_missing(parsed: Dict[str, dict], prev: Optional[dict],
                          data_root) -> List[str]:
    """Достроить parsed прежними данными по спискам, которые не удалось снять.

    Возвращает коды перенесённых списков (изменяет parsed на месте).

    Непрочитанная страница молча выкидывала весь список из индекса, и его
    абитуриенты пропадали из бота, оставаясь в списках на epk25 (2026-08-05:
    доля не отдала 3 страницы из 111, опубликовалось 664 списка вместо 667).
    Порог защиты такую потерю не видит — 664 из 667 это 99,5%. Показать
    вчерашнюю позицию честнее, чем сделать вид, что человека нет: метаданные
    переносим прежние целиком, включая page_updated_at, поэтому «свежесть»
    по такому списку не врёт.

    Сюда же — НЕДОСТРОЕННЫЕ страницы. epk25 во время пересчёта отдаёт список
    не целиком: 2026-08-06 в 03:14 у списка 000000644 вместо 2729 строк
    оказалось 585, а 36 страниц вернули заглушку «Списки обновляются» и
    разобрались в ноль строк. Формально страница снята, поэтому потерю никто
    не замечал — а для человека ниже обрыва это выглядит как «вас больше нет
    в этом списке».

    Переносим ОДИН раз: помечаем список carried_forward, и если на следующем
    обходе он снова короткий — принимаем новое значение. Иначе настоящая
    убыль (приказы о зачислении убирают людей из списков) заморозила бы
    список навсегда.
    """
    import json
    if not prev:
        return []
    prev_lists = prev.get("lists") or {}
    missing = []
    for lc, pm in prev_lists.items():
        cur = parsed.get(lc)
        if cur is None:
            missing.append(lc)
            continue
        if pm.get("carried_forward"):
            continue        # прошлый раз уже переносили — верим свежим данным
        was = pm.get("count") or 0
        now = len(cur.get("rows") or [])
        # Порог грубый нарочно: обычная убыль за 15 минут — единицы строк,
        # а недостроенная страница теряет разом половину и больше.
        if was >= _COLLAPSE_MIN and now < was * _COLLAPSE_RATIO:
            print(f"Список {lc} отдан недостроенным: {now} строк вместо {was} "
                  f"— переношу прежние")
            missing.append(lc)
    if not missing:
        return []
    rows_by_list: Dict[str, list] = {lc: [] for lc in missing}
    shard_dir = Path(data_root) / "admissions" / "by_code"
    for path in sorted(shard_dir.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for code, entries in (doc.get("codes") or {}).items():
            for e in entries:
                if e.get("list") in rows_by_list:
                    row = {k: v for k, v in e.items()
                           if k not in ("list", "cons_above", "vpp_above", "sim_above")}
                    row["unique_code"] = code
                    rows_by_list[e["list"]].append(row)
    for lc in missing:
        m = dict(prev_lists[lc])
        # Метка живёт ровно один обход: следующий раз этот список переносить
        # уже нельзя, иначе настоящая убыль заморозит его навсегда.
        m["carried_forward"] = True
        parsed[lc] = {"rows": sorted(rows_by_list[lc], key=lambda r: r["position"]),
                      "meta": m}
    return missing


def load_shards(directory: str) -> Tuple[Dict[str, dict], dict]:
    """Объединить доли, снятые разными раннерами (scraper/crawl_shard.py).

    Долей может не хватать (упавший раннер), поэтому сверяем число собранных
    списков с тем, сколько их нашёл discover: молча собрать индекс из половины
    списков — ровно та потеря данных, от которой защищает _guard_incomplete.
    """
    import json
    parsed: Dict[str, dict] = {}
    stats = {"levels_failed": [], "directions_total": 0, "directions_failed": 0,
             "views_total": 0, "views_failed": 0, "shards": 0}
    discovered = 0
    for path in sorted(Path(directory).glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        parsed.update(doc["parsed"])
        stats["views_failed"] += doc["stats"].get("views_failed", 0)
        stats["shards"] += 1
        discovered = max(discovered, doc.get("discovered", 0))
    stats["views_total"] = discovered or len(parsed)
    stats["discovered"] = discovered
    return parsed, stats


def main() -> int:
    import json
    from scraper.fetchers import lists_fetcher as LF
    from scraper.fetchers import enrollment_order_fetcher as EOF
    from scraper.storage.git_storage import GitStorage

    shards_dir = os.environ.get("SHARDS_DIR")
    if shards_dir:
        parsed, stats = load_shards(shards_dir)
        print(f"Долей собрано: {stats['shards']}, списков: {len(parsed)} "
              f"из найденных {stats['discovered']}")
        pages, meta = None, None
    else:
        # Пакетность включается переменными окружения: длинный обход одним
        # раннером упирается в лимит epk25 на адрес, и его надо резать паузами
        # (см. scraper/crawl_loop.py). Для шардированного обхода не нужна.
        pages, meta, stats = LF.crawl(
            batch=int(os.environ.get("CRAWL_BATCH", "0") or 0),
            batch_pause=float(os.environ.get("CRAWL_BATCH_PAUSE", "0") or 0))
        parsed = None
    storage_root = Path(os.environ.get("DATA_PATH", "data"))
    cache_path = storage_root / "admissions" / "enrolled_codes.json"
    try:
        enrolled_elsewhere = EOF.collect_enrolled_codes()
    except Exception as e:  # noqa: BLE001
        print(f"Ошибка при сборе кодов зачисленных приказом: {e}")
        enrolled_elsewhere = set()
    # Пустой результат почти всегда означает сетевой сбой, а не отсутствие
    # приказов: collect_enrolled_codes глушит исключения и возвращает пустое
    # множество. Молча продолжить нельзя — без исключений 543 уже зачисленных
    # человека снова становятся конкурентами, и позиции у всех едут вниз
    # (2026-08-05: именно так прошёл прогон 06:30 UTC). Берём последний
    # удачный список с data-ветки.
    if not enrolled_elsewhere and cache_path.exists():
        try:
            cached = set(json.loads(cache_path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            cached = set()
        if cached:
            print(f"Приказы не скачались — беру последний сохранённый список "
                  f"({len(cached)} кодов).")
            enrolled_elsewhere = cached
    elif enrolled_elsewhere:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(sorted(enrolled_elsewhere), ensure_ascii=False, indent=1),
            encoding="utf-8")
    print(f"Зачислено приказом (квоты/БВИ), исключено из общего конкурса: "
          f"{len(enrolled_elsewhere)}")
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec="seconds")
    if parsed is None:
        parsed = parse_pages(pages, meta)

    storage = GitStorage(os.environ.get("DATA_PATH", "data"))
    prev_path = storage.root / "admissions" / "lists_meta.json"
    prev = None
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
        except Exception:
            prev = None

    carried = carry_forward_missing(parsed, prev, storage.root)
    if carried:
        print(f"Не снято списков: {len(carried)} — переношу прежние данные "
              f"({', '.join(carried[:10])}{'...' if len(carried) > 10 else ''})")

    meta_doc, shards = build_index_from_parsed(
        parsed, updated_at=now, enrolled_elsewhere=enrolled_elsewhere)

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
