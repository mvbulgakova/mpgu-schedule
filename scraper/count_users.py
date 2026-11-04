"""Нижняя оценка числа уникальных пользователей бота по сохранённым данным.

Точного счётчика у бота нет: Telegram не отдаёт владельцу бота число
уникальных пользователей, а per-user лог не велся. Но два файла хранят
пользователей:
  • feedback.json — кто писал свободным текстом (хранится хеш anon, не ID);
  • subs.json     — кто подписался на /follow (ключи словаря — chat_id).

Объединяем их БЕЗ двойного счёта: chat_id подписчиков хешируем тем же anon,
что и feedback (в приватном чате Telegram chat_id == user_id), и считаем
мощность объединения множеств хешей.

Это НИЖНЯЯ оценка: тех, кто пользовался только кнопками (/spisok, калькулятор,
проходные, планы) и не подписался и не писал текстом, ни один файл не
фиксирует. Скрипт печатает только числа, не сырые идентификаторы.

Запуск: SUBS_PATH=subs.json FEEDBACK_PATH=feedback.json python -m scraper.count_users
"""
import json
import os
from pathlib import Path

from scraper.abitur import feedback

_ORDERS_KEY = "__orders__"   # служебная запись в subs.json, не пользователь


def feedback_hashes(items) -> set:
    """Множество anon-хешей из записей обратной связи."""
    return {e.get("anon") for e in items if e.get("anon")}


def subscriber_hashes(subs: dict) -> set:
    """anon-хеши подписчиков /follow (служебный ключ пропускаем)."""
    out = set()
    for key in subs:
        if key == _ORDERS_KEY:
            continue
        try:
            out.add(feedback.anon(int(key)))
        except (ValueError, TypeError):
            continue
    return out


def count(subs: dict, fb_items) -> dict:
    fb = feedback_hashes(fb_items)
    su = subscriber_hashes(subs)
    return {"feedback": len(fb), "subscribers": len(su),
            "overlap": len(fb & su), "union": len(fb | su)}


def main() -> int:
    subs = {}
    sp = os.environ.get("SUBS_PATH")
    if sp and Path(sp).exists():
        try:
            subs = json.loads(Path(sp).read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"subs.json не прочитан: {e}")
    fb = feedback.load(os.environ.get("FEEDBACK_PATH") or "")
    r = count(subs, fb)
    print(f"Писали свободным текстом (feedback): {r['feedback']}")
    print(f"Подписаны на /follow (subs):        {r['subscribers']}")
    print(f"Пересечение (и то, и другое):       {r['overlap']}")
    print(f"ВСЕГО уникальных (объединение):     {r['union']}")
    print("Это нижняя оценка: пользователи, работавшие только через кнопки, "
          "в сохранённых данных не зафиксированы.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
