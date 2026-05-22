"""Запись JSON-данных в data-ветку репозитория."""
import json
import os
import re
import subprocess
from pathlib import Path


def _safe_filename(name: str) -> str:
    """Преобразует имя группы в безопасное имя файла."""
    safe = re.sub(r"[^\w\-]", "_", name, flags=re.UNICODE)
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe or "group"


class GitStorage:
    def __init__(self, data_path: str):
        self.root = Path(data_path)

    def read_schedule(self, institute_id: str) -> dict | None:
        """Читает манифест (список групп без расписаний)."""
        path = self.root / "institutes" / institute_id / "schedule.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def write_schedule(self, institute_id: str, data: dict):
        """Записывает лёгкий манифест + отдельный файл на каждую группу.

        Структура:
          institutes/{id}/schedule.json        — манифест (без schedule в группах)
          institutes/{id}/groups/{name}.json   — расписание одной группы
        """
        groups = data.get("groups", [])
        groups_dir = self.root / "institutes" / institute_id / "groups"
        groups_dir.mkdir(parents=True, exist_ok=True)

        current_files: set[str] = set()
        manifest_groups: list[dict] = []

        for group in groups:
            filename = _safe_filename(group["name"])
            current_files.add(filename + ".json")
            _write_json(groups_dir / (filename + ".json"), group)
            manifest_groups.append({
                "name": group["name"],
                "file": filename,
                "year": group.get("year"),
                "form": group.get("form"),
                "degree": group.get("degree"),
            })

        # Удаляем файлы групп которых больше нет
        for f in groups_dir.iterdir():
            if f.suffix == ".json" and f.name not in current_files:
                f.unlink()

        # Манифест без поля groups[*].schedule
        manifest = {k: v for k, v in data.items() if k != "groups"}
        manifest["version"] = 1
        manifest["groups"] = manifest_groups
        _write_json(self.root / "institutes" / institute_id / "schedule.json", manifest)

    def read_index(self) -> dict | None:
        path = self.root / "meta" / "index.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def write_index(self, index: dict):
        _write_json(self.root / "meta" / "index.json", index)

    def write_hashes(self, hashes: dict):
        _write_json(self.root / "meta" / "hashes.json", hashes)

    def write_exams(self, institute_id: str, doc: dict):
        path = self.root / "institutes" / institute_id / "exams.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(path, doc)

    def write_teachers_index(self, doc: dict):
        _write_json(self.root / "meta" / "teachers.json", doc)

    def write_teacher_schedule(self, staff_slug: str, doc: dict):
        out_dir = self.root / "teachers"
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_json(out_dir / f"{staff_slug}.json", doc)

    def remove_stale_teacher_files(self, current_slugs: set[str]):
        teachers_dir = self.root / "teachers"
        if not teachers_dir.exists():
            return
        for f in teachers_dir.glob("*.json"):
            if f.stem not in current_slugs:
                f.unlink()

    def commit_and_push(self, message: str):
        _git(self.root, ["config", "user.name", "MPGU Schedule Bot"])
        _git(self.root, ["config", "user.email", "bot@github-actions"])
        _git(self.root, ["add", "-A"])
        result = _git(self.root, ["diff", "--staged", "--quiet"], check=False)
        if result.returncode == 0:
            print("Нет изменений для коммита")
            return
        _git(self.root, ["commit", "-m", message])
        _retry_push(self.root)


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _git(cwd: Path, args: list[str], check=True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True, check=check
    )


def _retry_push(cwd: Path):
    import time
    delays = [2, 4, 8, 16]
    for i, delay in enumerate(delays):
        result = _git(cwd, ["push", "-u", "origin", "data"], check=False)
        if result.returncode == 0:
            return
        if i < len(delays) - 1:
            print(f"Push не удался, повтор через {delay}с...")
            time.sleep(delay)
    raise RuntimeError("git push провалился после 4 попыток")
