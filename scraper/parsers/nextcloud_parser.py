"""Парсер для файлов из NextCloud (oc.mpgu.su).

NextCloud раздаёт файлы через публичные ссылки вида:
  https://oc.mpgu.su/index.php/s/{token}
  или /index.php/s/{token}/download

Скачиваем файл (может быть PDF, xlsx, docx или ZIP-архив с несколькими файлами)
и передаём в нужный парсер.
"""
import os
import re
import zipfile

from scraper.parsers.base import BaseParser, ParseResult
from scraper.parsers.pdf_parser import PDFParser
from scraper.parsers.excel_parser import ExcelParser
from scraper.parsers.docx_parser import DocxParser

_GENERIC_EXTS = {"bin", "tmp", ""}


def nextcloud_download_url(url: str) -> str:
    """Превращает ссылку просмотра в ссылку для скачивания."""
    if "/download" in url:
        return url
    m = re.search(r"/(?:index\.php/)?s/[a-zA-Z0-9]+", url)
    if m:
        return url.rstrip("/") + "/download"
    return url


class NextcloudParser(BaseParser):
    def parse(self, source: str | bytes) -> ParseResult:
        path = source if isinstance(source, str) else _bytes_to_tmp(source, ".bin")
        fmt = _detect_format(path)

        with open(path, "rb") as f:
            data = f.read()

        if fmt == "zip":
            return self._parse_zip(path)
        elif fmt == "pdf":
            return PDFParser(self.config).parse(data)
        elif fmt in {"xlsx", "xls"}:
            return ExcelParser(self.config).parse(data)
        elif fmt in {"docx", "doc"}:
            return DocxParser(self.config).parse(data)
        elif fmt == "html":
            return ParseResult(groups=[], parser_used="nextcloud",
                               confidence=0.0,
                               warnings=["Nextcloud вернул HTML — ссылка требует авторизации или недоступна"])
        else:
            return ParseResult(groups=[], parser_used="nextcloud",
                               confidence=0.0, warnings=[f"Неизвестный формат: {fmt}"])

    def _parse_zip(self, zip_path: str) -> ParseResult:
        """Извлекаем каждый файл из ZIP и парсим."""
        all_groups: list[dict] = []
        warnings: list[str] = []

        try:
            with zipfile.ZipFile(zip_path) as zf:
                for name in zf.namelist():
                    if name.endswith("/"):
                        continue
                    ext = os.path.splitext(name)[1].lower().lstrip(".")
                    if ext not in {"pdf", "xlsx", "xls", "docx", "doc"}:
                        continue
                    try:
                        data = zf.read(name)
                        if ext == "pdf":
                            result = PDFParser(self.config).parse(data)
                        elif ext in {"xlsx", "xls"}:
                            result = ExcelParser(self.config).parse(data)
                        else:
                            result = DocxParser(self.config).parse(data)
                        all_groups.extend(result.groups)
                        if result.warnings:
                            warnings.extend(result.warnings[:2])
                    except Exception as e:
                        warnings.append(f"{name}: {e}")
        except Exception as e:
            return ParseResult(groups=[], parser_used="nextcloud",
                               confidence=0.0, warnings=[str(e)])

        confidence = min(1.0, len(all_groups) / 5) if all_groups else 0.0
        return ParseResult(groups=all_groups, parser_used="nextcloud",
                           confidence=confidence, warnings=warnings)


def _detect_format(path: str) -> str:
    """Определяет формат файла по расширению и сигнатуре байт."""
    suffix = os.path.splitext(path)[1].lower().lstrip(".")
    if suffix and suffix not in _GENERIC_EXTS:
        return suffix

    try:
        with open(path, "rb") as f:
            sig = f.read(8)

        if sig[:4] == b"%PDF":
            return "pdf"

        if sig[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            return "xls"  # старый бинарный Excel

        if sig[:4] == b"PK\x03\x04":
            # ZIP-based: xlsx, docx или обычный архив
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
            if "[Content_Types].xml" in names:
                # Определяем xlsx vs docx по наличию характерных файлов
                if any(n.startswith("xl/") for n in names):
                    return "xlsx"
                if any(n.startswith("word/") for n in names):
                    return "docx"
                return "xlsx"  # предполагаем xlsx
            return "zip"  # архив с несколькими файлами

        # HTML — Nextcloud вернул страницу авторизации или ошибку
        if sig[:5] in (b"<!DOC", b"<html", b"<?xml") or sig[:1] == b"<":
            return "html"
    except Exception:
        pass

    return "unknown"


def _bytes_to_tmp(data: bytes, ext: str) -> str:
    import tempfile
    fd, path = tempfile.mkstemp(suffix=ext)
    os.write(fd, data)
    os.close(fd)
    return path
