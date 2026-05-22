"""Crawls mpgu.su department (кафедра) pages to collect full teacher names.

Each teacher on a кафедра page is linked as:
    <a href="https://mpgu.su/staff/{last}-{first}-{patr}/">Full Name</a>
The staff slug is a reliable unique identifier.
"""
import asyncio
import logging
import re
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

MPGU_BASE = "https://mpgu.su"
REQUEST_DELAY = 0.6  # seconds between requests, be polite

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; MPGUScheduleBot/1.0; "
        "+https://github.com/mvbulgakova/mpgu-schedule)"
    )
}

# Institutes where slug can't be inferred from schedule_url
STRUCTURE_SLUG_OVERRIDES: dict[str, str] = {
    "childhood": "institut-detstva",
}


def institute_slug_from_url(schedule_url: str) -> str | None:
    m = re.search(r"/faculties/([^/]+)/", schedule_url)
    return m.group(1) if m else None


class TeacherCrawler:
    def __init__(self, session: aiohttp.ClientSession):
        self._session = session
        self._seen_staff: set[str] = set()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    async def _get_soup(self, url: str) -> BeautifulSoup | None:
        try:
            async with self._session.get(url, headers=HEADERS) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                html = await resp.text(encoding="utf-8", errors="replace")
                await asyncio.sleep(REQUEST_DELAY)
                return BeautifulSoup(html, "lxml")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("fetch %s → %s", url, e)
            raise

    async def crawl_institute(self, institute_id: str, structure_slug: str) -> list[dict]:
        """Crawl all кафедра pages for one institute and return teacher records."""
        structure_url = f"{MPGU_BASE}/ob-mpgu/struktura/faculties/{structure_slug}/struktura/"
        soup = await self._get_soup(structure_url)
        if not soup:
            log.warning("No structure page for %s (%s)", institute_id, structure_url)
            return []

        kafedra_links = self._find_kafedra_links(soup, structure_url)
        log.info("  %s: %d кафедра links", institute_id, len(kafedra_links))

        results: list[dict] = []
        for kurl, kname in kafedra_links.items():
            entries = await self._crawl_kafedra(kurl, kname, institute_id)
            results.extend(entries)
            log.info("    %s → %d teachers", kname[:50], len(entries))

        return results

    def _find_kafedra_links(self, soup: BeautifulSoup, base_url: str) -> dict[str, str]:
        """Return {url: name} for all кафедра links on a structure page."""
        links: dict[str, str] = {}
        for a in soup.find_all("a", href=True):
            href = str(a["href"])
            text = a.get_text(strip=True)
            if "kafedra" not in href.lower():
                continue
            full_url = urljoin(base_url, href)
            if not full_url.startswith(MPGU_BASE):
                continue
            canonical = full_url.rstrip("/") + "/"
            if canonical not in links:
                links[canonical] = text
        return links

    async def _crawl_kafedra(self, url: str, kafedra_name: str, institute_id: str) -> list[dict]:
        """Extract teacher records from one кафедра page."""
        try:
            soup = await self._get_soup(url)
        except Exception:
            return []
        if not soup:
            return []

        records: list[dict] = []
        for a in soup.find_all("a", href=True):
            href = str(a["href"])
            m = re.search(r"/staff/([^/?#]+)/?$", href)
            if not m:
                continue
            staff_slug = m.group(1).rstrip("/")
            if staff_slug in self._seen_staff:
                continue
            name_text = " ".join(a.get_text(" ", strip=True).split())
            if not name_text or len(name_text.split()) < 2:
                continue
            self._seen_staff.add(staff_slug)
            records.append({
                "staff_slug": staff_slug,
                "full_name": name_text,
                "position": _position_after(a),
                "institute_id": institute_id,
                "kafedra_name": kafedra_name,
            })
        return records


def _position_after(a_tag) -> str:
    """Extract position text from the siblings immediately after a <a> tag."""
    parts: list[str] = []
    node = a_tag.next_sibling
    while node is not None and len(parts) < 3:
        if hasattr(node, "get_text"):
            t = node.get_text(strip=True)
        else:
            t = str(node).strip()
        if t:
            parts.append(t)
        node = node.next_sibling
    # First non-empty part is usually the position title
    for p in parts:
        if p and not p.startswith("+7") and "@" not in p:
            return p
    return ""
