import hashlib
import os
import tempfile
import threading
from pathlib import Path

_locks: dict[str, threading.RLock] = {}
_guard = threading.Lock()


def workspace_lock(root: Path) -> threading.RLock:
    with _guard:
        return _locks.setdefault(str(root.resolve()).casefold(), threading.RLock())


def text_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def atomic_write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".forge-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
