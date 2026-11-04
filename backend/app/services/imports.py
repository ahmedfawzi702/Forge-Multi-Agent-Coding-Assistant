import shutil
import uuid
from pathlib import Path

from app.code_intelligence.repository_scanner import LANGUAGES
from app.schemas.engineering import ProjectImport
from app.security.paths import safe_target
from app.security.policy import SafetyViolation


def import_snapshot(directory: Path, request: ProjectImport, max_bytes: int) -> Path:
    """Store explicitly selected text in a new owned directory, never original paths."""
    if sum(len(file.content.encode("utf-8")) for file in request.files) > 20 * 1024 * 1024:
        raise SafetyViolation("Folder snapshot exceeds the 20 MB import limit")
    directory.mkdir(parents=True, exist_ok=True)
    root = directory / str(uuid.uuid4())
    root.mkdir()
    try:
        seen: set[str] = set()
        for file in request.files:
            target = safe_target(root, file.path)
            name = file.path.replace("\\", "/").casefold()
            if name in seen or target.suffix.lower() not in LANGUAGES and target.name not in {".gitignore", "Makefile", "Dockerfile"}:
                raise SafetyViolation("Duplicate or unsupported import filename")
            seen.add(name)
            if len(file.content.encode("utf-8")) > max_bytes or "\x00" in file.content:
                raise SafetyViolation("Imported file is oversized or binary")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(file.content, encoding="utf-8", newline="")
        return root
    except Exception:
        # Only the UUID directory created by this call is removed.
        if root.parent.resolve() == directory.resolve():
            shutil.rmtree(root)
        raise
