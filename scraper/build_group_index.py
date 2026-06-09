"""Строит плоский индекс всех групп `meta/groups.json` для поиска (бот, PWA).

Каждая запись: код группы → институт и имя файла, плюс форма/степень и
нормализованный ключ для поиска без учёта гомоглифов/регистра/пробелов.
"""
import json
import os
import re
from pathlib import Path

# Латинские гомоглифы → кириллица (для поиска: ВОП и BОП совпадут)
_HOMO = str.maketrans({
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
})


def search_key(code: str) -> str:
    return re.sub(r"[\s\-_]", "", code.strip().upper().translate(_HOMO))


def main(data_path: str | None = None) -> int:
    root = Path(data_path or os.environ.get("DATA_PATH", "."))
    idx = root / "meta" / "index.json"
    names = {}
    if idx.exists():
        for e in json.loads(idx.read_text(encoding="utf-8")).get("institutes", []):
            names[e["id"]] = e.get("short_name") or e.get("name") or e["id"]

    groups = []
    for inst_dir in sorted((root / "institutes").glob("*")):
        manifest = inst_dir / "schedule.json"
        if not manifest.exists():
            continue
        m = json.loads(manifest.read_text(encoding="utf-8"))
        iid = inst_dir.name
        for g in m.get("groups", []):
            groups.append({
                "code": g["name"],
                "key": search_key(g["name"]),
                "institute": iid,
                "institute_short": names.get(iid, iid),
                "file": g.get("file", g["name"]),
                "form": g.get("form"),
                "degree": g.get("degree"),
            })

    out = root / "meta" / "groups.json"
    out.write_text(json.dumps({"groups": groups}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"meta/groups.json: {len(groups)} групп")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
