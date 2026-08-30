"""Тесты извлечения ссылок для обхода приказов о зачислении (без сети)."""
from scraper.fetchers import enrollment_order_fetcher as EOF

INDEX_HTML = """
<a href="https://mpgu.su/postuplenie/svedenija-zachislenii-2026/zachislenie-03-08-2026-budget/">03.08</a>
<a href="/postuplenie/svedenija-zachislenii-2026/zachislenie-05-08-2026-budget/">05.08</a>
<a href="https://mpgu.su/postuplenie/podgotovitelnyie-kursyi/">не то</a>
"""

ORDER_PAGE_HTML = """
<a href="https://mpgu.su/wp-content/uploads/2026/08/pk26_svedeniya-o-zachislenii_03-08-26_bvi.pdf">БВИ</a>
<a href="https://mpgu.su/wp-content/uploads/2026/08/pk26_svedeniya-o-zachislenii_03-08-26_kvoty.pdf">Квоты</a>
<a href="https://mpgu.su/postuplenie/">назад</a>
"""


def test_order_subpage_links_filters_to_zachislenie_pages():
    links = EOF.order_subpage_links(INDEX_HTML)
    assert links == [
        "https://mpgu.su/postuplenie/svedenija-zachislenii-2026/zachislenie-03-08-2026-budget/",
        "https://mpgu.su/postuplenie/svedenija-zachislenii-2026/zachislenie-05-08-2026-budget/",
    ]


def test_pdf_links_extracts_only_pdfs():
    links = EOF.pdf_links(ORDER_PAGE_HTML)
    assert links == [
        "https://mpgu.su/wp-content/uploads/2026/08/pk26_svedeniya-o-zachislenii_03-08-26_bvi.pdf",
        "https://mpgu.su/wp-content/uploads/2026/08/pk26_svedeniya-o-zachislenii_03-08-26_kvoty.pdf",
    ]
