from pathlib import Path, PureWindowsPath

from app.execution.local import is_link
from app.security.policy import IGNORED_DIRECTORIES, SafetyViolation, is_sensitive


def safe_target(root: Path, path: str) -> Path:
    """Validate existing AND new destinations without following links or drive syntax."""
    normalized = path.replace("\\", "/")
    relative = Path(normalized)
    if (not path or relative.is_absolute() or PureWindowsPath(path).drive
            or PureWindowsPath(path).root or any(part in {"..", ".", ""} for part in normalized.split("/"))
            or ":" in path or any(ord(c) < 32 for c in path)
            or any(part.lower() in IGNORED_DIRECTORIES for part in relative.parts)
            or is_sensitive(relative)):
        raise SafetyViolation("Destination is outside the source-file policy")
    current = root.resolve(strict=True)
    for part in relative.parts:
        if part.rstrip(". ") != part or part.lower().split(".")[0] in {"con", "prn", "aux", "nul", *{f"com{i}" for i in range(1, 10)}, *{f"lpt{i}" for i in range(1, 10)}}:
            raise SafetyViolation("Reserved or ambiguous filename")
        current /= part
        if is_link(current):
            raise SafetyViolation("Symbolic links and junctions are forbidden")
    if not current.resolve().is_relative_to(root.resolve()):
        raise SafetyViolation("Destination escapes the workspace")
    return current
