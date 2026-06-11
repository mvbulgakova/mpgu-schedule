"""Исторические проходные баллы МПГУ + статистический прогноз на текущий год.

Алгоритм:
  1. Скачиваем HTML-таблицы с mpgu.su (2014–2024)
  2. Извлекаем проходной балл по коду направления
  3. Строим линейную регрессию по годам (OLS, без numpy)
  4. Возвращаем прогноз с доверительным интервалом (±1σ)

Запуск автономно:
  python -m scraper.score_predictor
"""
import json
import logging
import math
import os
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment,misc]

log = logging.getLogger("score_predictor")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MPGU-Bot/1.0)"}
_TIMEOUT = 20
_BASE = "https://mpgu.su"

# Диапазон исторических данных
_HISTORY_YEARS = list(range(2014, date.today().year))  # 2014 … прошлый год
_TARGET_YEAR = date.today().year

_DATA_PATH = Path(os.environ.get("DATA_PATH", "./data"))


# ---------------------------------------------------------------------------
# Базовая статистика (без numpy)
# ---------------------------------------------------------------------------

class PredictionResult(NamedTuple):
    predicted: int            # округлённый прогноз
    ci_half: int              # полуширина доверительного интервала (±)
    slope: float              # баллов в год
    r2: float                 # коэффициент детерминации
    years_used: list[int]
    confidence: str           # "high" / "medium" / "low"
    label: str                # человекочитаемый тег для бота


def _ols(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Возвращает (slope, intercept, r2). Требует len >= 2."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, my, 0.0
    slope = sxy / sxx
    intercept = my - slope * mx
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return slope, intercept, r2


def _se_prediction(xs: list[float], ys: list[float],
                   slope: float, intercept: float, x_new: float) -> float:
    """Стандартная ошибка предсказания для одной новой точки."""
    n = len(xs)
    if n < 3:
        return float("inf")
    mx = sum(xs) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    residuals = [y - (slope * x + intercept) for x, y in zip(xs, ys)]
    mse = sum(r ** 2 for r in residuals) / (n - 2)
    leverage = 1 / n + (x_new - mx) ** 2 / (sxx if sxx > 0 else 1)
    return math.sqrt(mse * (1 + leverage))


def predict_score(history: dict[int, int], target_year: int = _TARGET_YEAR) -> PredictionResult:
    """
    Прогнозирует проходной балл по истории {год: балл}.
    Возвращает PredictionResult.
    """
    pairs = sorted((yr, sc) for yr, sc in history.items() if sc > 0)

    if not pairs:
        return PredictionResult(0, 0, 0.0, 0.0, [], "low", "нет данных")

    # Только последние 7 лет для устойчивости тренда
    pairs = pairs[-7:]
    xs = [float(yr) for yr, _ in pairs]
    ys = [float(sc) for _, sc in pairs]
    years_used = [yr for yr, _ in pairs]

    if len(pairs) == 1:
        sc = int(ys[0])
        return PredictionResult(sc, 15, 0.0, 0.0, years_used, "low",
                                f"данные только за {years_used[0]}: {sc}")

    slope, intercept, r2 = _ols(xs, ys)
    predicted_raw = slope * target_year + intercept
    predicted = max(0, round(predicted_raw))

    se = _se_prediction(xs, ys, slope, intercept, float(target_year))
    # t≈2 для малых выборок → приблизительный 95% ИД; inf при n<3 → 20
    ci_half = 20 if not math.isfinite(se) else min(30, max(3, round(2 * se)))

    n = len(pairs)
    if n >= 5 and r2 >= 0.7:
        confidence = "high"
    elif n >= 3 and r2 >= 0.4:
        confidence = "medium"
    else:
        confidence = "low"

    yr_range = f"{years_used[0]}–{years_used[-1]}"
    label = f"по тренду {yr_range}: ~{predicted} ±{ci_half}"

    return PredictionResult(predicted, ci_half, slope, r2, years_used, confidence, label)


# ---------------------------------------------------------------------------
# Парсинг HTML-таблиц МПГУ
# ---------------------------------------------------------------------------

def _fetch(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return r.read()
    except Exception as e:
        log.debug("fetch %s: %s", url, e)
        return None


def _normalize_code(raw: str) -> str | None:
    m = re.search(r"\d{2}\.\d{2}\.\d{2}", raw or "")
    return m.group() if m else None


def _extract_passing_score(cell: str) -> int | None:
    """Ищет число 100–400 (суммарный проходной) в тексте ячейки."""
    for m in re.finditer(r"\b(\d{3})\b", cell):
        v = int(m.group(1))
        if 100 <= v <= 400:
            return v
    return None


def _parse_score_table(soup: "BeautifulSoup") -> dict[str, int]:
    """Возвращает {code: passing_score} из таблиц на странице."""
    result: dict[str, int] = {}
    if soup is None:
        return result

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [th.get_text(" ", strip=True).lower()
                   for th in rows[0].find_all(["th", "td"])]

        # Находим индексы нужных колонок
        code_idx = passing_idx = -1
        for i, h in enumerate(headers):
            if any(k in h for k in ("код", "шифр", "направлен")):
                if code_idx < 0:
                    code_idx = i
            if any(k in h for k in ("проходной", "проход", "мин.*балл", "балл")):
                if passing_idx < 0:
                    passing_idx = i

        if code_idx < 0 or passing_idx < 0:
            # Попробуем угадать по структуре: первая колонка — код, последняя — балл
            if len(headers) >= 3:
                code_idx = 0
                passing_idx = len(headers) - 1

        if code_idx < 0:
            continue

        for row in rows[1:]:
            cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            if not cells:
                continue
            if code_idx >= len(cells) or passing_idx >= len(cells):
                continue
            code = _normalize_code(cells[code_idx])
            if not code:
                # Ищем код в любой ячейке строки
                for c in cells:
                    code = _normalize_code(c)
                    if code:
                        break
            if not code:
                continue
            score = _extract_passing_score(cells[passing_idx])
            if score is None:
                # fallback: последняя ненулевая числовая ячейка
                for c in reversed(cells):
                    score = _extract_passing_score(c)
                    if score:
                        break
            if score:
                result[code] = score

    return result


# ---------------------------------------------------------------------------
# URL-генератор для страниц исторических данных
# ---------------------------------------------------------------------------

_URL_TEMPLATES = [
    # Новый стиль (2020+)
    "{base}/postuplenie/priemnaya-komissiya/priemnaya-kampaniya-{year}/"
    "konkurs-i-prokhodnoj-ball-v-{year}-godu/",
    # Архивный стиль (2014-2020)
    "{base}/postuplenie/priemnaya-komissiya/"
    "priemnyie-kampanii-20hh-2014-godov/priemnaja-kampanija-{year}/"
    "konkurs-i-prohodnoj-ball-v-{year}-godu/",
    # Вариант написания без смягчения
    "{base}/postuplenie/priemnaya-komissiya/"
    "priemnye-kampanii-proshlyh-let/priemnaya-kampaniya-{year}/"
    "konkurs-i-prokhodnoj-ball-v-{year}-godu/",
    # Совсем короткий
    "{base}/postuplenie/priemnaya-komissiya/"
    "konkurs-i-prokhodnoj-ball-v-{year}-godu/",
]


def _candidate_urls(year: int) -> list[str]:
    return [t.format(base=_BASE, year=year) for t in _URL_TEMPLATES]


def scrape_year(year: int) -> dict[str, int]:
    """
    Пытается получить таблицу проходных баллов за `year`.
    Возвращает {program_code: passing_score} или пустой dict при неудаче.
    """
    if BeautifulSoup is None:
        log.warning("BeautifulSoup не установлен — скрейпинг невозможен")
        return {}

    for url in _candidate_urls(year):
        html = _fetch(url)
        if html is None:
            continue
        soup = BeautifulSoup(html, "lxml")
        scores = _parse_score_table(soup)
        if scores:
            log.info("  год %d: нашёл %d программ → %s", year, len(scores), url)
            return scores
        # Страница загрузилась, но таблицы нет — попробуем дочерние ссылки
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                href = _BASE + href
            subhtml = _fetch(href)
            if subhtml is None:
                continue
            subsoup = BeautifulSoup(subhtml, "lxml")
            subscores = _parse_score_table(subsoup)
            if subscores:
                log.info("  год %d: нашёл %d программ (subpage) → %s",
                         year, len(subscores), href)
                return subscores

    log.debug("  год %d: данные не найдены", year)
    return {}


def scrape_all_historical(
    years: list[int] | None = None,
) -> dict[str, dict[int, int]]:
    """
    Скачивает исторические проходные баллы за указанные годы.
    Возвращает {program_code: {year: score}}.
    """
    if years is None:
        years = _HISTORY_YEARS

    all_scores: dict[str, dict[int, int]] = {}
    for year in years:
        year_data = scrape_year(year)
        for code, score in year_data.items():
            all_scores.setdefault(code, {})[year] = score

    total = sum(len(v) for v in all_scores.values())
    log.info("Исторические данные: %d программ, %d записей", len(all_scores), total)
    return all_scores


# ---------------------------------------------------------------------------
# Прогнозы по всем программам
# ---------------------------------------------------------------------------

def build_predictions(
    all_historical: dict[str, dict[int, int]],
    target_year: int = _TARGET_YEAR,
) -> dict[str, dict]:
    """
    По историческим данным строит прогноз для каждой программы.
    Возвращает {code: {predicted, ci_half, label, confidence, years_used, ...}}
    """
    predictions: dict[str, dict] = {}
    for code, history in all_historical.items():
        if not history:
            continue
        pr = predict_score(history, target_year)
        if pr.predicted == 0:
            continue
        predictions[code] = {
            "code": code,
            "predicted": pr.predicted,
            "ci_half": pr.ci_half,
            "label": pr.label,
            "confidence": pr.confidence,
            "slope": round(pr.slope, 2),
            "r2": round(pr.r2, 3),
            "years_used": pr.years_used,
            "history": history,
            "updated_at": str(date.today()),
        }
    return predictions


def format_prediction_tag(entry: dict | None) -> str:
    """Форматирует строку вида '~248 ±8 (прогноз 2026)' для бота."""
    return _prediction_suffix_from_entry(entry)


def _prediction_suffix_from_entry(entry: dict | None) -> str:
    """Внутренний helper — принимает prediction entry, возвращает суффикс для бота."""
    if not entry:
        return ""
    p = entry.get("predicted", 0)
    if not p:
        return ""
    ci = entry.get("ci_half", 0)
    yr = _TARGET_YEAR
    conf_icon = {"high": "📊", "medium": "📈", "low": "📉"}.get(
        entry.get("confidence", "low"), "📉"
    )
    return f"{conf_icon} прогноз {yr}: ~{p} ±{ci}"


# ---------------------------------------------------------------------------
# Сохранение / загрузка
# ---------------------------------------------------------------------------

def save_historical(data: dict[str, dict[int, int]], dry_run: bool = False) -> None:
    dest = _DATA_PATH / "admissions" / "historical_scores.json"
    if dry_run:
        log.info("[dry-run] historical_scores.json (%d программ)", len(data))
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("saved %s", dest)


def save_predictions(data: dict[str, dict], dry_run: bool = False) -> None:
    dest = _DATA_PATH / "admissions" / "predictions.json"
    if dry_run:
        log.info("[dry-run] predictions.json (%d программ)", len(data))
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("saved %s", dest)


def load_predictions_from_cdn(get_json_fn: Any) -> dict[str, dict]:
    """Загружает predictions.json через переданную get_json_fn (CDN или local)."""
    try:
        data = get_json_fn("admissions/predictions.json")
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    dry_run = "--dry-run" in sys.argv

    years_arg = [int(a) for a in sys.argv[1:] if a.isdigit()]
    years = years_arg if years_arg else None

    historical = scrape_all_historical(years)
    if historical:
        save_historical(historical, dry_run)
        predictions = build_predictions(historical)
        save_predictions(predictions, dry_run)
        print(f"\nПрогнозы на {_TARGET_YEAR}:")
        for code, pred in list(predictions.items())[:10]:
            print(f"  {code}: {pred['label']}")
    else:
        print("Исторические данные не найдены. "
              "Возможно, сайт недоступен или структура URL изменилась.")
