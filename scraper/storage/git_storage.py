"""Запись JSON-данных в data-ветку репозитория."""
import json
import os
import subprocess
from pathlib import Path


class GitStorage:
    def __init__(self, data_path: str):
        self.root = Path(data_path)

    def write_schedule(self, institute_id: str, data: dict):
        path = self.root / "institutes" / institute_id / "schedule.json"
        _write_json(path, data)

    def write_index(self, index: dict):
        _write_json(self.root / "meta" / "index.json", index)

    def write_hashes(self, hashes: dict):
        _write_json(self.root / "meta" / "hashes.json", hashes)

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
