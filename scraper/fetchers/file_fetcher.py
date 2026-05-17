"""Скачивает файлы расписания с отслеживанием изменений."""
import hashlib
import os
import tempfile
from pathlib import Path

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; MPGUScheduleBot/1.0; "
        "+https://github.com/mpgu-schedule)"
    )
}


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=16))
async def fetch_file(session: aiohttp.ClientSession, url: str) -> tuple[bytes, str]:
    """Скачивает файл, возвращает (content, md5)."""
    async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=60)) as resp:
        resp.raise_for_status()
        content = await resp.read()
    return content, hashlib.md5(content).hexdigest()


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=16))
async def check_changed(session: aiohttp.ClientSession, url: str, known_md5: str | None) -> bool:
    """True если файл изменился. Использует HEAD + ETag до полной загрузки."""
    if known_md5 is None:
        return True
    try:
        async with session.head(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            etag = resp.headers.get("ETag", "").strip('"')
            if etag and etag == known_md5:
                return False
            # ETag не совпал или отсутствует — скачиваем и сравниваем
    except Exception:
        pass
    content, new_md5 = await fetch_file(session, url)
    return new_md5 != known_md5


def save_to_temp(content: bytes, suffix: str) -> str:
    """Сохраняет байты во временный файл, возвращает путь."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        os.write(fd, content)
    finally:
        os.close(fd)
    return path
