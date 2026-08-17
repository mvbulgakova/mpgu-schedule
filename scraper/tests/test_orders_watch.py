"""Вахта приказов о зачислении: что считать новым и что рассылать.

Запуск: python -m pytest scraper/tests/test_orders_watch.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scraper.telegram_bot as bot
from scraper.abitur import orders_watch as OW

_OLD = ("https://mpgu.su/postuplenie/svedenija-zachislenii-2026/"
        "zachislenie-03-08-2026-budget/")
_NEW = ("https://mpgu.su/postuplenie/svedenija-zachislenii-2026/"
        "zachislenie-07-08-2026-budget/")


def test_order_date_from_url():
    assert OW.order_date(_OLD) == "03.08.2026"
    assert OW.order_date("https://mpgu.su/что-то-другое/") is None


def test_only_unseen_orders_are_new():
    assert OW.new_orders([_OLD, _NEW], {_OLD}) == [_NEW]
    assert OW.new_orders([_OLD], {_OLD}) == []


def test_the_already_published_order_is_not_announced():
    """Приказ приоритетного этапа вышел до появления вахты.

    Без этого первый же запуск разослал бы всем «опубликован приказ» о
    новости недельной давности.
    """
    assert OW.new_orders([_OLD], set(OW.ALREADY_PUBLISHED)) == []


def test_notice_names_the_date_and_the_kind_of_order():
    txt = OW.format_notice(_NEW, [
        "https://mpgu.su/wp-content/uploads/2026/08/pk26_..._07-08-26_budget.pdf"])
    assert "07.08.2026" in txt
    assert "бюджет" in txt
    assert _NEW in txt


def test_everyone_subscribed_gets_the_order():
    """Приказ касается всех подписчиков, а не только следящих за кодом."""
    subs = {"1": {"code": "1914288"}, "2": {"lists_updates": True}}
    assert set(OW.recipients(subs)) == {"1", "2"}


# ── Рассылка в боте ──────────────────────────────────────────────────────────

class _Net:
    """Подменённая сеть: индекс приказов, подстраница и PDF."""

    def __init__(self, pages):
        self.pages = pages
        self.downloaded = []

    def __call__(self, url, timeout=60):
        if url == OW.INDEX_PAGE:
            links = "".join(f'<a href="{p}">приказ</a>' for p in self.pages)
            return links.encode()
        if url.endswith(".pdf"):
            self.downloaded.append(url)
            return b"%PDF-1.4 fake"
        return (f'<a href="https://mpgu.su/files/prikaz_07-08-26_budget.pdf">'
                f'скачать</a>').encode()


def _wire(monkeypatch, pages):
    net = _Net(pages)
    sent, docs = [], []
    monkeypatch.setattr(bot, "_fetch", net)
    monkeypatch.setattr(bot, "_send", lambda t, c, r: sent.append((c, r.text)))
    monkeypatch.setattr(bot, "_send_document",
                        lambda t, c, data, name, caption="": docs.append((c, name)))
    monkeypatch.setattr(bot.time, "sleep", lambda s: None)
    monkeypatch.setattr(bot, "SUBS_PATH", "")
    bot.SUBS.clear()
    bot.SEEN_ORDERS.clear()
    bot.SEEN_ORDERS.update(OW.ALREADY_PUBLISHED)
    return sent, docs


def test_new_order_is_pushed_to_everyone_with_the_file(monkeypatch):
    sent, docs = _wire(monkeypatch, [_OLD, _NEW])
    bot.SUBS.update({"11": {"code": "1914288"}, "22": {"lists_updates": True}})

    bot._check_orders("token")

    assert sorted(c for c, _ in sent) == [11, 22]
    assert "приказ" in sent[0][1].lower()
    assert sorted(c for c, _ in docs) == [11, 22]
    assert docs[0][1].endswith(".pdf")


def test_the_same_order_is_never_sent_twice(monkeypatch):
    sent, _docs = _wire(monkeypatch, [_OLD, _NEW])
    bot.SUBS["11"] = {"code": "1914288"}
    bot._check_orders("token")
    assert len(sent) == 1
    bot._check_orders("token")
    assert len(sent) == 1, "повтор рассылки о том же приказе"


def test_nothing_is_sent_while_only_the_old_order_is_up(monkeypatch):
    sent, _docs = _wire(monkeypatch, [_OLD])
    bot.SUBS["11"] = {"code": "1914288"}
    bot._check_orders("token")
    assert sent == []


def test_a_broken_subpage_leaves_the_order_unsent(monkeypatch):
    """Не отметить приказ разосланным — значит повторить на следующем круге."""
    sent, _docs = _wire(monkeypatch, [_NEW])
    bot.SUBS["11"] = {"code": "1914288"}

    def flaky(url, timeout=60):
        if url == OW.INDEX_PAGE:
            return f'<a href="{_NEW}">приказ</a>'.encode()
        raise RuntimeError("502 от mpgu.su")

    monkeypatch.setattr(bot, "_fetch", flaky)
    bot._check_orders("token")
    assert sent == []
    assert _NEW not in bot.SEEN_ORDERS


def test_the_service_record_is_not_treated_as_a_subscriber(monkeypatch):
    """Список разосланных приказов лежит в том же файле, что подписки."""
    sent, _docs = _wire(monkeypatch, [_OLD, _NEW])
    bot.SUBS["11"] = {"code": "1914288"}
    bot._check_orders("token")
    assert bot._ORDERS_KEY in bot.SUBS          # отметка сохранена
    assert [c for c, _ in sent] == [11]         # но письмо ушло только человеку


# ── Слаг страницы — соглашение вуза, а не гарантия ────────────────────────────

def test_a_differently_named_page_is_still_caught():
    """Назови МПГУ страницу «prikaz-…» — прежний поиск промолчал бы."""
    html = ('<a href="/postuplenie/svedenija-zachislenii-2026/">раздел</a>'
            '<a href="/postuplenie/svedenija-zachislenii-2026/'
            'prikaz-osnovnoy-etap-2026/">приказ</a>')
    assert OW.order_pages(html) == [
        "https://mpgu.su/postuplenie/svedenija-zachislenii-2026/"
        "prikaz-osnovnoy-etap-2026/"]


def test_a_pdf_posted_without_a_page_is_caught():
    """Приказ могут выложить файлом прямо в разделе."""
    html = ('<a href="https://mpgu.su/wp-content/uploads/2026/08/'
            'pk26_svedeniya-o-zachislenii_07-08-26.pdf">скачать</a>')
    assert OW.order_pages(html) == [
        "https://mpgu.su/wp-content/uploads/2026/08/"
        "pk26_svedeniya-o-zachislenii_07-08-26.pdf"]


def test_the_section_itself_and_wordpress_junk_are_ignored():
    """Иначе вахта сработала бы на служебных ссылках в первую же минуту."""
    html = ('<a href="https://mpgu.su/postuplenie/svedenija-zachislenii-2026/">'
            'раздел</a>'
            '<a href="https://mpgu.su/wp-json/oembed/1.0/embed?url=https%3A%2F%2F'
            'mpgu.su%2Fpostuplenie%2Fsvedenija-zachislenii-2026%2F">oembed</a>'
            '<a href="/postuplenie/bakalavriat/">бакалавриат</a>'
            '<a href="/wp-content/uploads/2026/08/pravila-priema.pdf">правила</a>')
    assert OW.order_pages(html) == []


def test_the_live_page_still_yields_exactly_the_known_order():
    """Реальная разметка mpgu.su на 2026-08-07: один приказ, ничего лишнего."""
    html = ('<a href="https://mpgu.su/postuplenie/svedenija-zachislenii-2026/">'
            'Сведения о зачислении</a>'
            '<a href="https://mpgu.su/wp-json/oembed/1.0/embed?url=x">o</a>'
            '<a href="https://mpgu.su/postuplenie/svedenija-zachislenii-2026/'
            'zachislenie-03-08-2026-budget/">Зачисление 03.08.2026</a>')
    assert OW.order_pages(html) == [_OLD]
    assert OW.new_orders(OW.order_pages(html), set(OW.ALREADY_PUBLISHED)) == []
