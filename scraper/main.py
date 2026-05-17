"""Оркестратор: обход всех институтов, парсинг, сохранение данных."""
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

load_dotenv()

from scraper.fetchers.site_fetcher import fetch_schedule_links
from scraper.fetchers.file_fetcher import fetch_file, check_changed, save_to_temp
from scraper.parsers.pdf_parser import PDFParser
from scraper.parsers.excel_parser import ExcelParser
from scraper.parsers.gsheets_parser import GSheetsParser, gsheets_to_csv_url
from scraper.parsers.nextcloud_parser import NextcloudParser, nextcloud_download_url
from scraper.parsers.docx_parser import DocxParser
from scraper.storage.git_storage import GitStorage
from scraper.utils.hash_tracker import HashTracker, md5_of_bytes

CONFIG_PATH = Path(__file__).parent / "config" / "institutes.json"
DATA_PATH = os.environ.get("DATA_PATH", "./data")
CHANGED_ONLY = os.environ.get("CHANGED_ONLY", "true").lower() == "true"
INSTITUTE_FILTER = os.environ.get("INSTITUTE_ID")  # конкретный институт или все


def load_institutes() -> list[dict]:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    institutes = data["institutes"]
    if INSTITUTE_FILTER:
        institutes = [i for i in institutes if i["id"] == INSTITUTE_FILTER]
    return institutes


def get_parser(parser_type: str, config: dict):
    return {
        "pdf": PDFParser,
        "excel": ExcelParser,
        "gsheets": GSheetsParser,
        "nextcloud": NextcloudParser,
        "docx": DocxParser,
    }.get(parser_type, PDFParser)(config)


async def process_institute(
    session: aiohttp.ClientSession,
    institute: dict,
    tracker: HashTracker,
    storage: GitStorage,
) -> dict:
    inst_id = institute["id"]
    inst_name = institute["name"]
    print(f"\n▶ {inst_name} ({inst_id})")

    schedule_url = institute["schedule_url"]
    parser_type = institute.get("parser_type", "pdf")
    fallback_type = institute.get("fallback_parser_type")

    try:
        links = await fetch_schedule_links(session, schedule_url)
        print(f"  Найдено ссылок: {len(links)}")
    except Exception as e:
        print(f"  Ошибка при получении ссылок: {e}")
        return _error_entry(inst_id, inst_name, str(e))

    all_groups = []
    parser_used = parser_type
    file_hashes: dict[str, str] = {}

    for link in links:
        url = link["url"]
        link_type = link["type"]
        link_key = f"{inst_id}:{url}"

        # выбираем парсер под тип ссылки
        actual_type = link_type if link_type in {"pdf", "excel", "gsheets", "nextcloud", "docx"} else parser_type

        # Google Sheets — конвертируем URL и скачиваем CSV
        if actual_type == "gsheets":
            csv_url = gsheets_to_csv_url(url)
            try:
                content, md5 = await fetch_file(session, csv_url)
            except Exception as e:
                print(f"  ✗ gsheets {url}: {e}")
                continue
        elif actual_type == "nextcloud":
            dl_url = nextcloud_download_url(url)
            try:
                content, md5 = await fetch_file(session, dl_url)
            except Exception as e:
                print(f"  ✗ nextcloud {url}: {e}")
                continue
        else:
            try:
                content, md5 = await fetch_file(session, url)
            except Exception as e:
                print(f"  ✗ {url}: {e}")
                continue

        # пропускаем если не изменилось
        if CHANGED_ONLY and not tracker.has_changed(link_key, md5):
            print(f"  ↔ без изменений: {url[-60:]}")
            continue

        file_hashes[link_key] = md5

        # сохраняем во временный файл и парсим
        ext = f".{actual_type}" if actual_type in {"pdf", "excel", "docx"} else ".csv"
        ext = ".xlsx" if actual_type == "excel" else ext
        tmp_path = save_to_temp(content, ext)

        try:
            parser = get_parser(actual_type, institute)
            result = parser.parse(tmp_path)

            if not result.groups and fallback_type:
                print(f"  ⚠ Fallback на {fallback_type}: {url[-60:]}")
                parser = get_parser(fallback_type, institute)
                result = parser.parse(tmp_path)

            print(f"  ✓ {result.parser_used} conf={result.confidence:.2f} "
                  f"групп={len(result.groups)} [{url[-50:]}]")

            all_groups.extend(result.groups)
            parser_used = result.parser_used

            if result.warnings:
                for w in result.warnings:
                    print(f"    ⚠ {w}")
        except Exception as e:
            print(f"  ✗ Ошибка парсинга {url}: {e}")
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    # обновляем хеши
    for key, md5 in file_hashes.items():
        tracker.update(key, key.split(":", 1)[1], md5, 0, datetime.now(timezone.utc).isoformat())

    if not all_groups:
        return _error_entry(inst_id, inst_name, "Группы не найдены")

    now = datetime.now(timezone.utc).isoformat()
    schedule_doc = {
        "institute_id": inst_id,
        "institute_name": inst_name,
        "short_name": institute.get("short_name", ""),
        "academic_year": _current_academic_year(),
        "updated_at": now,
        "parser_used": parser_used,
        "groups": all_groups,
    }
    storage.write_schedule(inst_id, schedule_doc)

    return {
        "id": inst_id,
        "name": inst_name,
        "short_name": institute.get("short_name", ""),
        "groups_count": len(all_groups),
        "updated_at": now,
        "status": "ok",
        "parser_used": parser_used,
    }


async def main():
    institutes = load_institutes()
    storage = GitStorage(DATA_PATH)
    hashes_path = os.path.join(DATA_PATH, "meta", "hashes.json")
    tracker = HashTracker(hashes_path)

    index_entries = []

    connector = aiohttp.TCPConnector(limit=5)
    async with aiohttp.ClientSession(connector=connector) as session:
        for institute in institutes:
            entry = await process_institute(session, institute, tracker, storage)
            index_entries.append(entry)

    tracker.save()
    storage.write_hashes(json.loads(Path(hashes_path).read_text()) if Path(hashes_path).exists() else {})
    storage.write_index({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "academic_year": _current_academic_year(),
        "institutes": index_entries,
    })

    ok = sum(1 for e in index_entries if e.get("status") == "ok")
    print(f"\n{'='*50}")
    print(f"Готово: {ok}/{len(index_entries)} институтов обработано успешно")


def _current_academic_year() -> str:
    now = datetime.now()
    year = now.year if now.month >= 9 else now.year - 1
    return f"{year}-{year + 1}"


def _error_entry(inst_id, inst_name, error):
    return {
        "id": inst_id,
        "name": inst_name,
        "groups_count": 0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "error",
        "error": error,
    }


if __name__ == "__main__":
    asyncio.run(main())
