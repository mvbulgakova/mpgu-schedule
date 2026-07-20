"""Сбор обратной связи (отзывы студентов, свободные вопросы) — хранение и экспорт.

Хранение — локальный JSON-файл, в проде переживает рестарты через actions/cache
(вместе с подписками). user_id хранится ТОЛЬКО как усечённый хеш: видно, что
«человек №a1b2» написал трижды, но восстановить личность нельзя.
"""
import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

_SALT = "mpgu-abitur-feedback"

_STOP = {
    "и", "в", "не", "на", "что", "как", "это", "то", "по", "но", "за", "из",
    "же", "бы", "ли", "или", "для", "так", "вот", "все", "всё", "есть", "был",
    "была", "было", "быть", "мне", "меня", "нас", "вы", "он", "она", "они",
    "мы", "его", "ее", "её", "их", "там", "тут", "очень", "просто", "еще",
    "ещё", "уже", "только", "если", "когда", "который", "можно", "нужно",
}


def anon(user_id: int) -> str:
    return hashlib.sha256(f"{_SALT}:{user_id}".encode()).hexdigest()[:12]


def load(path) -> List[dict]:
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def add(path, items: List[dict], user_id: int, kind: str, text: str) -> List[dict]:
    """Добавляет запись и сохраняет файл (если path задан). Возвращает список."""
    items = list(items)
    items.append({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "anon": anon(user_id), "kind": kind, "text": text[:1000]})
    if path:
        Path(path).write_text(json.dumps(items, ensure_ascii=False),
                              encoding="utf-8")
    return items


def to_csv(items: List[dict]) -> bytes:
    """CSV с BOM — чтобы Excel не покрошил кириллицу."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["дата (UTC)", "тип", "аноним", "текст"])
    for e in items:
        w.writerow([e.get("ts"), e.get("kind"), e.get("anon"), e.get("text")])
    return buf.getvalue().encode("utf-8-sig")


def stats_text(items: List[dict]) -> str:
    if not items:
        return "Сообщений пока нет."
    users = len({e["anon"] for e in items})
    kinds = Counter(e.get("kind") for e in items)
    words = Counter(w for e in items
                    for w in re.findall(r"[а-яёa-z]{3,}", e["text"].lower())
                    if w not in _STOP)
    top = ", ".join(f"{w} ({n})" for w, n in words.most_common(15)) or "—"
    kinds_s = ", ".join(f"{k}: {n}" for k, n in kinds.items())
    return (f"Сообщений: {len(items)} ({kinds_s})\n"
            f"Уникальных людей: {users}\nТоп слов: {top}")
