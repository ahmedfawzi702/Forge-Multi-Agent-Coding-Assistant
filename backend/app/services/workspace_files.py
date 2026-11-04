import fnmatch
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from app.config import Settings
from app.execution.file_io import atomic_write, text_hash, workspace_lock
from app.execution.local import LocalExecutionEnvironment, is_link
from app.schemas.domain import ProjectView
from app.security.paths import safe_target
from app.security.policy import IGNORED_DIRECTORIES, SafetyViolation, is_sensitive, load_ignore


class WorkspaceFiles:
    """Human filesystem operations; no LLM approval is required for a manual save."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = threading.RLock()

    def read(self, project: ProjectView, path: str) -> dict[str, Any]:
        text = LocalExecutionEnvironment(Path(project.path), self.settings.max_file_bytes, agent=False).read_file(path)
        return {"path": path, "content": text, "sha256": text_hash(text)}

    def write(self, project: ProjectView, path: str, content: str, base_hash: str | None) -> dict[str, Any]:
        with self.lock, workspace_lock(Path(project.path)):
            target = safe_target(Path(project.path), path)
            if len(content.encode()) > self.settings.max_file_bytes or "\x00" in content:
                raise SafetyViolation("Only bounded UTF-8 text can be saved")
            if target.exists():
                current = self.read(project, path)["sha256"]
                if base_hash != current:
                    raise SafetyViolation("File changed on disk. Reload it or save this draft under a new name.")
            elif base_hash is not None:
                raise SafetyViolation("File was removed. Use Save As to create a new file.")
            atomic_write(target, content)
            return self.read(project, path)

    def mkdir(self, project: ProjectView, path: str) -> None:
        with self.lock, workspace_lock(Path(project.path)):
            target = safe_target(Path(project.path), path)
            if target.exists():
                raise SafetyViolation("A file or folder already exists at this path")
            target.mkdir(parents=True)

    def move(self, project: ProjectView, path: str, destination: str) -> None:
        with self.lock, workspace_lock(Path(project.path)):
            root = Path(project.path)
            source, target = safe_target(root, path), safe_target(root, destination)
            if not source.exists():
                raise FileNotFoundError(path)
            if target.exists() or target.is_relative_to(source):
                raise SafetyViolation("Destination already exists or is inside the source folder")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)

    def trash(self, project: ProjectView, path: str) -> str:
        with self.lock, workspace_lock(Path(project.path)):
            source = safe_target(Path(project.path), path)
            if not source.exists():
                raise FileNotFoundError(path)
            key = str(uuid.uuid4())
            owned = self.settings.data_directory / "trash" / key
            owned.mkdir(parents=True)
            (owned / "record.json").write_text(json.dumps({"project_id": project.id, "path": path}), encoding="utf-8")
            os.replace(source, owned / "content")
            return key

    def restore(self, project: ProjectView, key: str) -> str:
        with self.lock, workspace_lock(Path(project.path)):
            key = str(uuid.UUID(key))
            owned = self.settings.data_directory / "trash" / key
            data = json.loads((owned / "record.json").read_text(encoding="utf-8"))
            if data["project_id"] != project.id:
                raise SafetyViolation("Trash item belongs to another workspace")
            target = safe_target(Path(project.path), data["path"])
            if target.exists():
                raise SafetyViolation("Restore would overwrite a newer file")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(owned / "content", target)
            return str(data["path"])

    def tree(self, project: ProjectView, *, agent: bool = False) -> list[dict[str, str]]:
        root = Path(project.path)
        ignore = load_ignore(root, forge=agent)
        result: list[dict[str, str]] = []
        for current, dirs, files in os.walk(root, followlinks=False):
            base = Path(current)
            dirs[:] = sorted(d for d in dirs if d.lower() not in IGNORED_DIRECTORIES and not is_link(base / d)
                             and not is_sensitive((base / d).relative_to(root))
                             and not ignore.match_file((base / d).relative_to(root).as_posix() + "/"))
            for directory in dirs:
                result.append({"path": (base / directory).relative_to(root).as_posix(), "kind": "directory"})
            for name in sorted(files):
                path = base / name
                relative = path.relative_to(root).as_posix()
                if is_link(path) or is_sensitive(Path(relative)) or ignore.match_file(relative):
                    continue
                if path.stat().st_size <= self.settings.max_file_bytes:
                    result.append({"path": relative, "kind": "file"})
            if len(result) >= self.settings.max_files * 2:
                return result[:self.settings.max_files * 2]
        return result

    def search(self, project: ProjectView, query: str, include: str = "*", exclude: str = "", *, agent: bool = False) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        if not query:
            return hits
        source = LocalExecutionEnvironment(Path(project.path), self.settings.max_file_bytes, agent=agent)
        for item in self.tree(project, agent=agent):
            path = item["path"]
            if item["kind"] != "file" or not fnmatch.fnmatch(path, include) or exclude and fnmatch.fnmatch(path, exclude):
                continue
            try:
                text = source.read_file(path)
            except (OSError, SafetyViolation):
                continue
            for line, value in enumerate(text.splitlines(), 1):
                column = value.lower().find(query.lower())
                if column >= 0:
                    hits.append({"file": path, "line": line, "column": column + 1, "text": value[:500]})
                    if len(hits) == 200:
                        return hits
        return hits
