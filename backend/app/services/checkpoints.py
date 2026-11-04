import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings
from app.execution.file_io import atomic_write, text_hash, workspace_lock
from app.execution.local import LocalExecutionEnvironment
from app.schemas.domain import ProjectView
from app.security.paths import safe_target
from app.security.policy import SafetyViolation


class CheckpointStore:
    lock = threading.RLock()

    def __init__(self, settings: Settings):
        self.root = settings.data_directory / "checkpoints"
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = settings

    def create(self, project: ProjectView, change_id: str, patches: list[dict[str, Any]], metadata: dict[str, Any] | None = None) -> str:
        key = str(uuid.uuid4())
        root = Path(project.path).resolve()
        created_directories: set[str] = set()
        for patch in patches:
            target = safe_target(root, patch["path"])
            parent = target if patch.get("directory") else target.parent
            while parent != root and not parent.exists():
                created_directories.add(parent.relative_to(root).as_posix())
                parent = parent.parent
        record = {"id": key, "project_id": project.id, "change_id": change_id, "created_at": datetime.now(UTC).isoformat(),
                  "metadata": metadata or {},
                  "created_directories": sorted(created_directories, key=lambda path: len(Path(path).parts), reverse=True),
                  "status": "prepared", "files": [{"path": patch["path"], "before": patch["before"] if patch["base_hash"] is not None else None,
                      "after": patch["after"], "after_hash": text_hash(patch["after"]),
                      "before_hash": patch["base_hash"], "reason": patch["reason"], "diff": patch["diff"],
                      "delete": patch.get("delete", False), "directory": patch.get("directory", False)} for patch in patches]}
        atomic_write(self.root / f"{key}.json", json.dumps(record))
        return key

    def load(self, project: ProjectView, key: str) -> dict[str, Any]:
        path = self.root / f"{uuid.UUID(key)}.json"
        record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if record["project_id"] != project.id:
            raise SafetyViolation("Checkpoint belongs to another workspace")
        return record

    def status(self, project: ProjectView, key: str, status: str) -> None:
        record = self.load(project, key)
        atomic_write(self.root / f"{key}.json", json.dumps({**record, "status": status}))

    def list(self, project: ProjectView) -> list[dict[str, Any]]:
        result = []
        for path in self.root.glob("*.json"):
            if path.is_symlink():
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["project_id"] == project.id:
                result.append({**{k: record[k] for k in ("id", "change_id", "created_at", "status")}, "metadata": record.get("metadata", {}), "files": [f["path"] for f in record["files"]]})
        return sorted(result, key=lambda item: str(item["created_at"]), reverse=True)[:100]

    def restore(self, project: ProjectView, key: str) -> dict[str, Any]:
        with self.lock, workspace_lock(Path(project.path)):
            record = self.load(project, key)
            if record["status"] != "applied":
                raise SafetyViolation("Only an applied checkpoint can be restored")
            source = LocalExecutionEnvironment(Path(project.path), self.settings.max_file_bytes, agent=False)
            for file in record["files"]:
                target = safe_target(Path(project.path), file["path"])
                if file.get("delete"):
                    if target.exists():
                        raise SafetyViolation("Deleted source was recreated; restore would overwrite later work")
                    continue
                if file.get("directory"):
                    if not target.is_dir() or any(target.iterdir()):
                        raise SafetyViolation("Directory contains later work; restore was blocked")
                    continue
                try:
                    current = source.read_file(file["path"])
                except (OSError, SafetyViolation) as error:
                    raise SafetyViolation("Checkpoint source is missing; no files were restored") from error
                if text_hash(current) != file["after_hash"]:
                    raise SafetyViolation(f"{file['path']} changed after the agent edit. Restore would overwrite later work.")
            restored: list[dict[str, Any]] = []
            try:
                for file in record["files"]:
                    target = safe_target(Path(project.path), file["path"])
                    if file.get("directory"):
                        target.rmdir()
                    elif file["before"] is None:
                        target.unlink()
                    else:
                        atomic_write(target, file["before"])
                    restored.append(file)
            except Exception:
                for file in restored:
                    target = safe_target(Path(project.path), file["path"])
                    if file.get("directory"):
                        target.mkdir(parents=True, exist_ok=True)
                    elif file.get("delete"):
                        target.unlink(missing_ok=True)
                    else:
                        atomic_write(target, file["after"])
                raise
            self.status(project, key, "restored")
            for directory in record.get("created_directories", []):
                target = safe_target(Path(project.path), directory)
                if target.is_dir() and not any(target.iterdir()):
                    target.rmdir()
            return {"id": key, "change_id": record["change_id"], "files": [file["path"] for file in record["files"]], "status": "restored"}
