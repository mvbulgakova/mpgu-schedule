"""Тесты извлечения ссылок из страниц epk25 (чистые функции, без сети).

Запуск: python -m pytest scraper/tests/test_lists_fetcher.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.fetchers import lists_fetcher as LF

STRUCTURAL = """
<a href="/competitive-list/index">Competitive lists</a>
<a href="/competitive-list/direction?educationLevel=basic_higher_education&amp;university=main_university&amp;structuralUnit=1">Институт истории</a>
<a href="/competitive-list/direction?educationLevel=basic_higher_education&amp;university=anapa_branch">Анапский филиал</a>
"""

DIRECTION = """
<a href="/competitive-list/view?code=000000672">44.03.01 История</a>
<a href="/competitive-list/view?code=000000673">46.03.01 История</a>
<a href="/competitive-list/index">назад</a>
"""


def test_extract_direction_links():
    links = LF.extract_direction_links(STRUCTURAL)
    assert len(links) == 2
    assert all("competitive-list/direction" in u for u in links)
    assert all(u.startswith("https://epk25.mpgu.su") for u in links)


def test_extract_view_codes():
    codes = LF.extract_view_codes(DIRECTION)
    assert codes == ["000000672", "000000673"]


def test_structural_url_for_level():
    u = LF.structural_url("basic_higher_education")
    assert u == ("https://epk25.mpgu.su/competitive-list/structural"
                 "?educationLevel=basic_higher_education")


def test_extract_view_links_with_titles():
    links = LF.extract_view_links(DIRECTION)
    assert links == [("000000672", "44.03.01 История"),
                     ("000000673", "46.03.01 История")]


def test_crawl_fetches_all_view_pages_concurrently(monkeypatch):
    """Списки должны сниматься все разом (пул на весь набор), а не по одному."""
    struct_html = (
        '<a href="/competitive-list/direction?educationLevel=basic_higher_education'
        '&university=main_university&structuralUnit=1">Институт истории</a>'
    )
    direction_html = """
    <article class="landing-competitive-direction__card">
      <div class="landing-competitive-direction__head">44.03.01 История</div>
      <table><tbody>
        <tr><td class="landing-competitive-direction__form">очная</td>
            <td><a href="/competitive-list/view?code=111">Бюджет</a></td></tr>
        <tr><td class="landing-competitive-direction__form">очная</td>
            <td><a href="/competitive-list/view?code=222">Бюджет</a></td></tr>
        <tr><td class="landing-competitive-direction__form">очная</td>
            <td><a href="/competitive-list/view?code=333">Бюджет</a></td></tr>
      </tbody></table>
    </article>
    """

    seen_concurrently = set()
    max_concurrent = [0]
    lock = __import__("threading").Lock()

    def fake_get(url, retries=3):
        if "/direction?" in url:
            return direction_html
        if "/structural?" in url:
            return struct_html
        # view?code=... — эти вызовы должны пересекаться по времени
        with lock:
            seen_concurrently.add(url)
            max_concurrent[0] = max(max_concurrent[0], len(seen_concurrently))
        import time as _time
        _time.sleep(0.05)
        with lock:
            seen_concurrently.discard(url)
        return "<html>ok</html>"

    monkeypatch.setattr(LF, "_get", fake_get)

    pages, meta, stats = LF.crawl(levels=["basic_higher_education"], pause=0)

    assert set(pages.keys()) == {"111", "222", "333"}
    assert stats["views_total"] == 3
    assert stats["views_failed"] == 0
    assert max_concurrent[0] > 1, "view-запросы должны идти пачкой, а не по одному"
    assert meta["111"]["direction"] == "44.03.01 История"


def test_crawl_retries_pool_failures_sequentially(monkeypatch):
    """Отказ пула — часто лимит соединений, а не мёртвая страница."""
    struct_html = (
        '<a href="/competitive-list/direction?educationLevel=basic_higher_education'
        '&university=main_university&structuralUnit=1">Институт истории</a>'
    )
    direction_html = """
    <article class="landing-competitive-direction__card">
      <div class="landing-competitive-direction__head">44.03.01 История</div>
      <table><tbody>
        <tr><td class="landing-competitive-direction__form">очная</td>
            <td><a href="/competitive-list/view?code=111">Бюджет</a></td></tr>
        <tr><td class="landing-competitive-direction__form">очная</td>
            <td><a href="/competitive-list/view?code=222">Бюджет</a></td></tr>
      </tbody></table>
    </article>
    """
    seen = {"concurrent": 0}
    lock = __import__("threading").Lock()

    def fake_get(url, retries=3):
        if "/direction?" in url:
            return direction_html
        if "/structural?" in url:
            return struct_html
        # первый (параллельный) заход по каждому коду падает, второй проходит
        with lock:
            seen[url] = seen.get(url, 0) + 1
            attempt = seen[url]
        if attempt == 1:
            raise RuntimeError("connection reset by peer")
        return "<html>ok</html>"

    monkeypatch.setattr(LF, "_get", fake_get)
    pages, meta, stats = LF.crawl(levels=["basic_higher_education"], pause=0)

    assert set(pages.keys()) == {"111", "222"}   # спасены вторым проходом
    assert stats["views_failed"] == 0
    assert stats["views_retried"] == 2


def test_crawl_counts_failed_views_without_losing_the_rest(monkeypatch):
    struct_html = (
        '<a href="/competitive-list/direction?educationLevel=basic_higher_education'
        '&university=main_university&structuralUnit=1">Институт истории</a>'
    )
    direction_html = """
    <article class="landing-competitive-direction__card">
      <div class="landing-competitive-direction__head">44.03.01 История</div>
      <table><tbody>
        <tr><td class="landing-competitive-direction__form">очная</td>
            <td><a href="/competitive-list/view?code=111">Бюджет</a></td></tr>
        <tr><td class="landing-competitive-direction__form">очная</td>
            <td><a href="/competitive-list/view?code=222">Бюджет</a></td></tr>
      </tbody></table>
    </article>
    """

    def fake_get(url, retries=3):
        if "/direction?" in url:
            return direction_html
        if "/structural?" in url:
            return struct_html
        if "code=222" in url:
            raise RuntimeError("boom")
        return "<html>ok</html>"

    monkeypatch.setattr(LF, "_get", fake_get)

    pages, meta, stats = LF.crawl(levels=["basic_higher_education"], pause=0)

    assert set(pages.keys()) == {"111"}
    assert stats["views_total"] == 2
    assert stats["views_failed"] == 1


def test_shard_of_splits_without_gaps_or_overlaps():
    codes = [f"{i:06d}" for i in range(667)]
    for of in (1, 3, 8, 10):
        parts = [LF.shard_of(codes, i, of) for i in range(of)]
        union = sorted(c for p in parts for c in p)
        assert union == sorted(codes), f"of={of}: доли не покрывают весь набор"
        seen = [c for p in parts for c in p]
        assert len(seen) == len(set(seen)), f"of={of}: доли пересекаются"
        # доли примерно равны — иначе один раннер станет узким местом
        assert max(len(p) for p in parts) - min(len(p) for p in parts) <= 1


def test_shard_of_is_stable_regardless_of_input_order():
    a = LF.shard_of(["3", "1", "2", "4"], 0, 2)
    b = LF.shard_of(["4", "2", "1", "3"], 0, 2)
    assert a == b == ["1", "3"]


def test_shard_of_rejects_bad_arguments():
    import pytest
    for bad in [(0, 0), (2, 2), (-1, 3)]:
        with pytest.raises(ValueError):
            LF.shard_of(["1"], *bad)
