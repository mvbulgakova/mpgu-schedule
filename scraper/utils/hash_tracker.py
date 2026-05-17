import hashlib
import json
import os
from pathlib import Path


class HashTracker:
    def __init__(self, hashes_path: str):
        self.path = Path(hashes_path)
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, key: str) -> dict | None:
        return self._data.get(key)

    def update(self, key: str, url: str, md5: str, size: int, last_changed: str):
        self._data[key] = {
            "url": url,
            "md5": md5,
            "size_bytes": size,
            "last_changed": last_changed,
        }

    def has_changed(self, key: str, new_md5: str) -> bool:
        entry = self._data.get(key)
        if entry is None:
            return True
        return entry.get("md5") != new_md5


def md5_of_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()
