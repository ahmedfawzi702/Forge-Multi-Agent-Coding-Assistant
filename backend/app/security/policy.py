from pathlib import Path

from pathspec import PathSpec
from pathspec.pattern import Pattern

IGNORED_DIRECTORIES = frozenset({
    ".git", ".svn", ".hg", "node_modules", ".next", ".venv", "venv", "env",
    "__pycache__", ".data", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "dist", "build", "coverage", ".idea", ".vscode",
})
SENSITIVE_NAMES = frozenset({
    ".env", ".npmrc", ".pypirc", ".netrc", "id_rsa", "id_ed25519",
    "credentials", "credentials.json", "secrets.json", "secrets.yaml", "secrets.yml",
    "terraform.tfstate", "package-lock.json", "uv.lock", "pnpm-lock.yaml", "yarn.lock",
})


class SafetyViolation(ValueError):
    """A deterministic workspace policy rejected the request."""


def is_sensitive(path: Path) -> bool:
    name = path.name.lower()
    return (
        name in SENSITIVE_NAMES
        or (name.startswith(".env.") and name not in {".env.example", ".env.sample"})
        or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".sqlite", ".db"}
        or any(p.lower() in {".ssh", ".aws", ".azure", ".gnupg"} for p in path.parts)
    )


def load_ignore(root: Path, *, forge: bool = True) -> PathSpec[Pattern]:
    lines: list[str] = []
    for name in ([".gitignore", ".forgeignore"] if forge else [".gitignore"]):
        path = root / name
        if path.is_file() and not path.is_symlink() and not bool(getattr(path, "is_junction", lambda: False)()) and path.stat().st_size < 65536:
            lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines())
    return PathSpec.from_lines("gitignore", lines)
