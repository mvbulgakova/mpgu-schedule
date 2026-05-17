"""Парсер для файлов из NextCloud (oc.mpgu.su).

NextCloud раздаёт файлы через публичные ссылки вида:
  https://oc.mpgu.su/index.php/s/{token}
  или /index.php/s/{token}/download

Скачиваем файл и передаём в нужный парсер по расширению.
"""
import os
import re
from urllib.parse import urlparse

import aiohttp

from scraper.parsers.base import BaseParser, ParseResult
from scraper.parsers.pdf_parser import PDFParser
from scraper.parsers.excel_parser import ExcelParser
from scraper.parsers.docx_parser import DocxParser


def nextcloud_download_url(url: str) -> str:
    """Превращает ссылку просмотра в ссылку для скачивания."""
    if "/download" in url:
        return url
    # /index.php/s/{token} → /index.php/s/{token}/download
    m = re.search(r"(/index\.php/s/[a-zA-Z0-9]+)", url)
    if m:
        return url.rstrip("/") + "/download"
    return url


class NextcloudParser(BaseParser):
    def parse(self, source: str | bytes) -> ParseResult:
        # source здесь — путь к уже скачанному файлу
        path = source if isinstance(source, str) else _bytes_to_tmp(source, ".bin")
        ext = _detect_extension(path)

        if ext == "pdf":
            return PDFParser(self.config).parse(path)
        elif ext in {"xlsx", "xls"}:
            return ExcelParser(self.config).parse(path)
        elif ext in {"docx", "doc"}:
            return DocxParser(self.config).parse(path)
        else:
            return ParseResult(groups=[], parser_used="nextcloud",
                               confidence=0.0, warnings=[f"Неизвестное расширение: {ext}"])


def _detect_extension(path: str) -> str:
    suffix = os.path.splitext(path)[1].lower().lstrip(".")
    if suffix:
        return suffix
    # пытаемся угадать по сигнатуре файла
    try:
        with open(path, "rb") as f:
            sig = f.read(8)
        if sig[:4] == b"%PDF":
            return "pdf"
        if sig[:4] == b"PK\x03\x04":
            return "xlsx"  # ZIP-based (xlsx, docx)
    except Exception:
        pass
    return "unknown"


def _bytes_to_tmp(data: bytes, ext: str) -> str:
    import tempfile
    fd, path = tempfile.mkstemp(suffix=ext)
    os.write(fd, data)
    os.close(fd)
    return path
