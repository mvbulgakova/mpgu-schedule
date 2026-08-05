"""Обход конкурсных списков epk25: уровень → подразделение → направление → view.

Извлечение ссылок — чистые функции (тестируемы без сети). Сетевой обход — тонкий
слой на requests (honors HTTPS_PROXY), с вежливой паузой и ретраями.
"""
import re
import time
from html import unescape
from typing import Dict, List

BASE = "https://epk25.mpgu.su"
LEVELS = ["basic_higher_education", "specialist", "specialized_higher_education",
          "magistracy", "secondary_vocational_education"]

_UA = {"User-Agent": "MPGU-Abitur-Bot/1.0 (+https://mpgu.su)"}


def structural_url(level: str) -> str:
    return f"{BASE}/competitive-list/structural?educationLevel={level}"


def extract_direction_links(html: str) -> List[str]:
    hrefs = re.findall(r'href="(/competitive-list/direction\?[^"]*)"', html or "")
    return [BASE + unescape(h) for h in hrefs]


def extract_view_codes(html: str) -> List[str]:
    codes = re.findall(r'/competitive-list/view\?code=([0-9]+)', html or "")
    seen, out = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


def extract_view_links(html: str) -> List[tuple]:
    """[(code, title)] — код списка и текст ссылки (название направления)."""
    pairs = re.findall(
        r'<a[^>]*href="[^"]*/competitive-list/view\?code=([0-9]+)"[^>]*>(.*?)</a>',
        html or "", re.S | re.I)
    seen, out = set(), []
    for code, raw in pairs:
        if code in seen:
            continue
        seen.add(code)
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", unescape(raw))).strip()
        out.append((code, title))
    return out


def extract_view_entries(html: str) -> List[dict]:
    """[{code, direction, form, kind}] из карточек direction-страницы epk25.

    Структура: article.landing-competitive-direction__card → __head (направление),
    строки таблицы (форма обучения), ссылки-pills (Бюджет / Платные места).
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "lxml")
    out, seen = [], set()
    for card in soup.select("article.landing-competitive-direction__card"):
        head = card.select_one(".landing-competitive-direction__head")
        direction = re.sub(r"\s+", " ", head.get_text(" ", strip=True)) if head else ""
        for tr in card.select("tbody tr"):
            form_td = tr.select_one(".landing-competitive-direction__form")
            form_txt = (form_td.get_text(" ", strip=True) if form_td else "").lower()
            if "очно-заочная" in form_txt:
                form = "очно-заочная"
            elif "заочная" in form_txt:
                form = "заочная"
            else:
                form = "очная"
            for a in tr.select("a[href*='view?code=']"):
                m = re.search(r"code=([0-9]+)", a.get("href") or "")
                if not m or m.group(1) in seen:
                    continue
                seen.add(m.group(1))
                kind = "бюджет" if "бюджет" in a.get_text().lower() else "платное"
                out.append({"code": m.group(1), "direction": direction,
                            "form": form, "kind": kind})
    return out


def _get(url: str, retries: int = 3) -> str:
    import requests
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=_UA, timeout=30)
            if r.status_code == 200:
                return r.text
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


# Осознанно скромно. 2026-08-05: с раннеров GitHub Actions пул на 50
# соединений ронял ВСЕ 667 view-страниц (views_failed=667, прогон падал
# 9 часов подряд), хотя из локальной среды те же 50 давали 666/667.
# Дешевле ходить в несколько потоков и всегда получать данные, чем быстро
# и не получать ничего: пустой индекс в день дедлайна — худший исход.
DEFAULT_VIEW_WORKERS = 8
# Пауза перед последовательным повтором упавших страниц.
RETRY_DELAY = 60.0


def discover(levels: List[str] = None, pause: float = 0.3):
    """(entries, stats) — какие списки вообще существуют, без снятия страниц.

    entries: {код списка: {direction, level, form, kind}}. Страниц немного
    (уровни + направления), берём последовательно с вежливой паузой.
    Вынесено отдельно, чтобы обход списков можно было разложить по нескольким
    раннерам: состав списков находит один шаг, а страницы снимают несколько.
    """
    levels = levels or LEVELS
    stats = {"levels_failed": [], "directions_total": 0, "directions_failed": 0,
             "views_total": 0, "views_failed": 0}
    entries: Dict[str, dict] = {}
    for lvl in levels:
        try:
            struct = _get(structural_url(lvl))
        except Exception:
            stats["levels_failed"].append(lvl)  # весь уровень не прочитан — критично
            continue
        for dir_url in extract_direction_links(struct):
            stats["directions_total"] += 1
            time.sleep(pause)
            try:
                dhtml = _get(dir_url)
            except Exception:
                stats["directions_failed"] += 1
                continue
            for entry in extract_view_entries(dhtml):
                code = entry["code"]
                if code in entries:
                    continue
                entries[code] = {"direction": entry["direction"], "level": lvl,
                                 "form": entry["form"], "kind": entry["kind"]}
    return entries, stats


def shard_of(codes, index: int, of: int) -> List[str]:
    """Доля index из of, детерминированно и без пересечений.

    Нарезка по остатку от деления на отсортированном списке: каждый раннер
    получает свою часть, объединение долей = весь набор при любом of.
    """
    if of < 1 or not 0 <= index < of:
        raise ValueError(f"некорректная доля: {index} из {of}")
    return [c for i, c in enumerate(sorted(codes)) if i % of == index]


def crawl(levels: List[str] = None, pause: float = 0.3,
          max_workers: int = DEFAULT_VIEW_WORKERS,
          retry_delay: float = RETRY_DELAY):
    """Возвращает (pages, meta, stats).

    pages: {code -> html}; meta: {code -> {direction, level, form, kind}};
    stats: сведения о полноте обхода для защиты от публикации неполного индекса
    (пропущенный из-за сетевого сбоя уровень/направление = молчаливая потеря данных).

    Два прохода: сначала уровни/направления — их немного, собираем последовательно
    с вежливой паузой, чтобы получить полный список кодов списков. Затем сами
    списки (view?code=...) — их сотни, и время между первым и последним снятым
    списком напрямую портит консистентность снимка (согласия успевают сдвинуться),
    поэтому их бьём пулом потоков, а не по одному.

    max_workers по умолчанию — 50, НЕ «все разом»: проверено на реальном
    epk25 2026-08-05 — при concurrency ~667 (весь набор целиком) сервер
    рвёт ~92% соединений (ConnectionResetError), при 50 обходится 666/667
    за ~27с. «Все сразу» физически не работает против их инфраструктуры;
    ограниченный пул — рабочий компромисс между скоростью и надёжностью.

    Сеть; в тестах не вызывается напрямую (см. monkeypatch _get в тестах).
    """
    entries, stats = discover(levels, pause)
    pages, meta, fetch_stats = fetch_views(entries, workers=max_workers,
                                           pause=pause, retry_delay=retry_delay)
    stats.update(fetch_stats)
    return pages, meta, stats


def fetch_views(entries: Dict[str, dict], workers: int = DEFAULT_VIEW_WORKERS,
                pause: float = 0.3, retry_delay: float = RETRY_DELAY):
    """(pages, meta, stats) — снять страницы перечисленных списков.

    Отдельно от discover, чтобы один и тот же код работал и для целого обхода,
    и для доли на отдельном раннере (см. scraper/crawl_shard.py).
    """
    import concurrent.futures
    pages: Dict[str, str] = {}
    meta: Dict[str, dict] = {}
    stats = {"views_total": len(entries), "views_failed": 0}
    if not entries:
        return pages, meta, stats

    workers = max(1, workers or DEFAULT_VIEW_WORKERS)

    def fetch_view(code: str) -> str:
        return _get(f"{BASE}/competitive-list/view?code={code}")

    # Прогресс печатаем обязательно: 2026-08-05 прогон в CI шёл 49 минут и был
    # убит таймаутом, а в логе не оказалось НИ ОДНОЙ строки — все print стоят
    # в конце. Понять, где именно ушло время, было нельзя.
    t0 = time.time()
    done = 0
    step = max(50, len(entries) // 10)
    failed: List[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_view, code): code for code in entries}
        print(f"Списков к обходу: {len(entries)}, потоков: {workers}", flush=True)
        for fut in concurrent.futures.as_completed(futures):
            code = futures[fut]
            try:
                pages[code] = fut.result()
                meta[code] = entries[code]
            except Exception:
                failed.append(code)
            done += 1
            if done % step == 0 or done == len(entries):
                print(f"  {done}/{len(entries)} за {time.time() - t0:.0f}с "
                      f"(упало пока: {len(failed)})", flush=True)
    print(f"Пул завершён за {time.time() - t0:.0f}с, на повтор: {len(failed)}",
          flush=True)

    # Второй проход — последовательно, с вежливой паузой. Пул может упереться
    # не в саму страницу, а в лимит одновременных соединений: 2026-08-05 с
    # раннеров GitHub Actions пул ронял ВСЕ 667 запросов (views_failed=667),
    # тогда как последовательные страницы направлений с того же раннера в том
    # же прогоне проходили без единой ошибки. Без этого прохода такой отказ =
    # пустой индекс и сутки без обновлений у пользователей.
    if failed and retry_delay:
        # Ждём ОДИН раз перед всем проходом, а не между страницами: лимит
        # epk25 висит на адресе минутами, и повтор внутри того же окна
        # гарантированно упрётся снова (2026-08-05: три страницы не дались
        # ни разу за пять минут повторов сразу после отказа пула).
        print(f"Жду {retry_delay:.0f}с перед повтором — похоже на лимит epk25",
              flush=True)
        time.sleep(retry_delay)
    t1 = time.time()
    for n, code in enumerate(failed, 1):
        time.sleep(pause)
        try:
            pages[code] = _get(f"{BASE}/competitive-list/view?code={code}")
            meta[code] = entries[code]
        except Exception:
            stats["views_failed"] += 1
        if n % 50 == 0:
            print(f"  повтор {n}/{len(failed)} за {time.time() - t1:.0f}с",
                  flush=True)

    stats["views_retried"] = len(failed)
    stats["seconds"] = round(time.time() - t0)
    print(f"Обход занял {stats['seconds']}с, страниц получено: {len(pages)}",
          flush=True)
    return pages, meta, stats
