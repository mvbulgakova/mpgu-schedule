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
    """Подменённая сеть: индекс приказов, подстраница и PDF.

    По умолчанию у каждой страницы один pdf `prikaz_07-08-26_budget.pdf`;
    для тестов, где важно несколько pdf или добор — задаётся page_pdfs.
    fail — множество URL, которые бросают ошибку (симуляция таймаута).
    """

    def __init__(self, pages, page_pdfs=None, fail=None):
        self.pages = pages
        self.page_pdfs = page_pdfs or {}
        self.fail = fail or set()
        self.downloaded = []

    def __call__(self, url, timeout=60):
        if url in self.fail:
            raise RuntimeError("502 от mpgu.su")
        if url == OW.INDEX_PAGE:
            links = "".join(f'<a href="{p}">приказ</a>' for p in self.pages)
            return links.encode()
        if url.endswith(".pdf"):
            self.downloaded.append(url)
            return b"%PDF-1.4 fake"
        # Дефолтный pdf — уникальный для страницы: иначе миграция по одной
        # странице «съедает» pdf другой (везде один и тот же URL — везде
        # уже видели). Реальные страницы всегда дают разные имена файлов.
        date = OW.order_date(url) or "unknown"
        pdfs = self.page_pdfs.get(url, [
            f"https://mpgu.su/files/prikaz_{date.replace('.', '-')}.pdf"])
        return "".join(f'<a href="{u}">файл</a>' for u in pdfs).encode()


def _wire(monkeypatch, pages, page_pdfs=None, fail=None):
    net = _Net(pages, page_pdfs=page_pdfs, fail=fail)
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
    bot.SEEN_PDFS.clear()
    # ALREADY_PUBLISHED — те приказы, что вышли ДО появления вахты, их pdf
    # тоже считаем разосланными (тем же способом, что и штатная миграция
    # в _load_seen_orders): иначе на первом тике бот их «доберёт».
    bot._seed_seen_pdfs_from(OW.ALREADY_PUBLISHED)
    return sent, docs, net


def test_new_order_is_pushed_to_everyone_with_the_file(monkeypatch):
    sent, docs, _net = _wire(monkeypatch, [_OLD, _NEW])
    bot.SUBS.update({"11": {"code": "1914288"}, "22": {"lists_updates": True}})

    bot._check_orders("token")

    assert sorted(c for c, _ in sent) == [11, 22]
    assert "приказ" in sent[0][1].lower()
    assert sorted(c for c, _ in docs) == [11, 22]
    assert docs[0][1].endswith(".pdf")


def test_the_same_order_is_never_sent_twice(monkeypatch):
    sent, _docs, _net = _wire(monkeypatch, [_OLD, _NEW])
    bot.SUBS["11"] = {"code": "1914288"}
    bot._check_orders("token")
    assert len(sent) == 1
    bot._check_orders("token")
    assert len(sent) == 1, "повтор рассылки о том же приказе"


def test_nothing_is_sent_while_only_the_old_order_is_up(monkeypatch):
    sent, _docs, _net = _wire(monkeypatch, [_OLD])
    bot.SUBS["11"] = {"code": "1914288"}
    bot._check_orders("token")
    assert sent == []


def test_a_broken_subpage_leaves_the_order_unsent(monkeypatch):
    """Не отметить приказ разосланным — значит повторить на следующем круге."""
    sent, _docs, _net = _wire(monkeypatch, [_NEW])
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
    sent, _docs, _net = _wire(monkeypatch, [_OLD, _NEW])
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


# ── Кому какой приказ: тип по слагу и «фактически видимые» приказы ────────────

def test_order_kind_by_slug():
    """Плюс двойная ловушка: «spo» — часть «spvo», но это разные типы."""
    def k(u): return OW.order_kind(u)
    assert k("https://mpgu.su/.../zachislenie-07-08-2026-budget/") == "budget-bachelor"
    assert k("https://mpgu.su/.../zachislenie-25-08-2026-budget-spvo/") == "budget-mag"
    assert k("https://mpgu.su/.../zachislenie-25-08-2026-budget-spo/") == "budget-spo"
    assert k("https://mpgu.su/.../zachislenie-31-08-2026-dogovor/") == "paid"
    assert k("https://mpgu.su/.../pk26_platnye_v1.pdf") == "paid"
    assert k("https://mpgu.su/что-то-другое/") is None


def test_register_pages_remembers_the_latest_date_per_kind():
    """Основной этап 7 августа, дополнительный 11-го — оба «budget-bachelor».
    В карточку «опубликован от…» показываем последнюю дату из виденных."""
    OW.clear_published()
    OW.register_pages([
        "https://mpgu.su/.../zachislenie-07-08-2026-budget/",
        "https://mpgu.su/.../zachislenie-11-08-2026-budget/",
        "https://mpgu.su/.../zachislenie-25-08-2026-budget-spvo/",
        "https://mpgu.su/что-то-другое/",       # не приказ — пропускаем
    ])
    assert OW.published("budget-bachelor") == "11.08.2026"
    assert OW.published("budget-mag") == "25.08.2026"
    assert OW.published("paid") is None
    OW.clear_published()


def test_register_pages_is_idempotent_and_survives_reordering():
    OW.clear_published()
    urls = ["https://mpgu.su/.../zachislenie-11-08-2026-budget/",
            "https://mpgu.su/.../zachislenie-07-08-2026-budget/"]
    OW.register_pages(urls)
    OW.register_pages(reversed(urls))          # тот же снимок, другой порядок
    assert OW.published("budget-bachelor") == "11.08.2026"
    OW.clear_published()


def test_bot_feeds_orders_watch_from_the_index_and_from_seen(monkeypatch):
    """Вахта заполняет orders_watch каждый обход — иначе lists.py на
    холодном старте будет 3 минуты писать «приказы не опубликованы»."""
    OW.clear_published()
    sent, docs, _net = _wire(monkeypatch, [_OLD, _NEW])
    bot._load_seen_orders()             # приходит с диска: только 03.08 в SEEN
    assert OW.published("budget-bachelor") == "03.08.2026"
    bot._check_orders("token")
    # После обхода индекса orders_watch знает и про 07.08.
    assert OW.published("budget-bachelor") == "07.08.2026"
    OW.clear_published()


# ── Частичная доставка: pdf добирается, страница не помечается разосланной ────

_PART1 = "https://mpgu.su/files/dogovor_part-1.pdf"
_PART2 = "https://mpgu.su/files/dogovor_part-2.pdf"
_DOGOVOR = ("https://mpgu.su/postuplenie/svedenija-zachislenii-2026/"
            "zachislenie-31-08-2026-dogovor/")


def test_pdf_added_after_the_first_visit_is_still_delivered(monkeypatch):
    """Live 2026-08-31: part-2 приказа dogovor появился позже — вахта
    его пропустила навсегда, потому что страница уже стояла в SEEN. Теперь
    при переобходе страницы бот замечает новый pdf и рассылает добор.
    """
    sent, docs, net = _wire(monkeypatch, [_DOGOVOR], page_pdfs={_DOGOVOR: [_PART1]})
    bot.SUBS["11"] = {"code": "1914288"}
    bot._check_orders("token")
    assert [d for _, d in docs] == ["dogovor_part-1.pdf"]
    assert _PART1 in bot.SEEN_PDFS
    # На следующем тике на странице появился part-2
    net.page_pdfs[_DOGOVOR] = [_PART1, _PART2]
    bot._check_orders("token")
    assert [d for _, d in docs] == ["dogovor_part-1.pdf", "dogovor_part-2.pdf"]
    assert _PART2 in bot.SEEN_PDFS
    assert "добавлен файл" in sent[-1][1].lower()


def test_first_notice_stays_the_full_publication_notice(monkeypatch):
    """Первую рассылку по странице не переименовываем в «добор»."""
    sent, _docs, _net = _wire(monkeypatch, [_DOGOVOR],
                              page_pdfs={_DOGOVOR: [_PART1, _PART2]})
    bot.SUBS["11"] = {"code": "1914288"}
    bot._check_orders("token")
    # Один тик, одно письмо со всеми pdf; текст — «опубликован приказ».
    assert len(sent) == 1
    assert "опубликован" in sent[0][1].lower()
    assert "добавлен" not in sent[0][1].lower()
    assert _PART1 in bot.SEEN_PDFS and _PART2 in bot.SEEN_PDFS


def test_download_failure_leaves_pdf_out_of_seen_pdfs(monkeypatch):
    """Не скачался pdf → не помечаем разосланным → следующий круг его добирает.
    Иначе временный сбой сети превращает pdf в невидимый.
    """
    sent, docs, net = _wire(monkeypatch, [_DOGOVOR],
                            page_pdfs={_DOGOVOR: [_PART1, _PART2]},
                            fail={_PART2})
    bot.SUBS["11"] = {"code": "1914288"}
    bot._check_orders("token")
    assert _PART1 in bot.SEEN_PDFS
    assert _PART2 not in bot.SEEN_PDFS
    assert [d for _, d in docs] == ["dogovor_part-1.pdf"]
    # На следующем тике всё ок — part-2 докачивается и уходит добором
    net.fail.clear()
    bot._check_orders("token")
    assert _PART2 in bot.SEEN_PDFS
    assert [d for _, d in docs] == ["dogovor_part-1.pdf", "dogovor_part-2.pdf"]


def test_six_pdfs_are_all_delivered_not_capped_at_four(monkeypatch):
    """У dogovor-spo 6 файлов; прежний cap [:4] терял два. Теперь идут все."""
    six = [f"https://mpgu.su/files/pk26_31-08-26_dogovor_spo_{i}.pdf"
           for i in range(1, 7)]
    page = ("https://mpgu.su/postuplenie/svedenija-zachislenii-2026/"
            "zachislenie-31-08-2026-dogovor-spo/")
    _sent, docs, _net = _wire(monkeypatch, [page], page_pdfs={page: six})
    bot.SUBS["11"] = {"code": "1914288"}
    bot._check_orders("token")
    assert [d for _, d in docs] == [u.rsplit("/", 1)[-1] for u in six]


def test_legacy_state_migrates_without_spamming_subscribers(monkeypatch):
    """Апгрейд со старой схемы (только «sent»): считаем всё уже разосланным.

    Иначе на первом же тике новой схемы бот пришлёт всем 19 pdf-ок
    приказов заново — их не должно быть в очереди повторных рассылок.
    """
    sent, docs, _net = _wire(monkeypatch, [_DOGOVOR],
                             page_pdfs={_DOGOVOR: [_PART1, _PART2]})
    # Легаси-состояние: страница разослана, но список pdf НЕ хранился
    bot.SUBS[bot._ORDERS_KEY] = {"sent": [_DOGOVOR]}
    bot.SEEN_ORDERS.clear()
    bot.SEEN_PDFS.clear()
    bot._load_seen_orders()
    # После миграции оба pdf помечены как разосланные
    assert _PART1 in bot.SEEN_PDFS and _PART2 in bot.SEEN_PDFS
    # На тике ничего не рассылаем (все pdf в SEEN_PDFS, страница в SEEN_ORDERS)
    bot._check_orders("token")
    assert sent == [] and docs == []


def test_addition_notice_reads_as_a_follow_up_not_a_new_order():
    """Тексты добора и первой публикации отличаются интонацией и словами."""
    txt = OW.format_addition(_DOGOVOR, ["part-2.pdf"])
    assert "добавлен файл" in txt
    assert "Опубликован приказ" not in txt
    assert "31.08.2026" in txt
    assert _DOGOVOR in txt

    plural = OW.format_addition(_DOGOVOR, ["a.pdf", "b.pdf", "c.pdf"])
    assert "добавлены файлы (3)" in plural
