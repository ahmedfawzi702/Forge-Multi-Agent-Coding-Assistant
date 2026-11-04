import uuid
from pathlib import Path

from app.config import Settings
from app.execution.file_io import text_hash
from app.execution.local import LocalExecutionEnvironment
from app.schemas.domain import ProjectMap
from app.security.paths import safe_target
from app.security.policy import SafetyViolation


def inspection_snapshot(root: Path, project_map: ProjectMap, settings: Settings, baseline: dict[str, str] | None = None) -> Path:
    snapshot = settings.data_directory / "workspaces" / str(uuid.uuid4())
    snapshot.mkdir(parents=True)
    environment = LocalExecutionEnvironment(root, settings.max_file_bytes)
    total = 0
    for file in project_map.files:
        content = environment.read_file(file.path)
        if baseline is not None:
            baseline[file.path] = text_hash(content)
        total += len(content.encode())
        if total > 20 * 1024 * 1024:
            raise SafetyViolation("Validation snapshot exceeds 20 MB")
        target = safe_target(snapshot, file.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
    return snapshot
