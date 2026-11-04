import os
from pathlib import Path, PureWindowsPath

from pathspec import PathSpec

from app.execution.base import ExecutionEnvironment, ExecutionResult
from app.security.command_guard import CommandGuard
from app.security.policy import (
    IGNORED_DIRECTORIES,
    SafetyViolation,
    is_sensitive,
    load_ignore,
)


def is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


class LocalExecutionEnvironment(ExecutionEnvironment):
    """Workspace environment with explicit read/write/execute capabilities.

    Defaults remain read only. Manual editing and approved development execution
    opt into separate capabilities; this boundary is not an OS sandbox.
    """

    def __init__(self, root: Path, max_file_bytes: int = 262144, *, agent: bool = True,
                 allow_write: bool = False, allow_execute: bool = False):
        self.root = root.resolve(strict=True)
        self.max_file_bytes = max_file_bytes
        self.ignore = load_ignore(self.root) if agent else PathSpec.from_lines("gitignore", [])
        self.allow_write, self.allow_execute = allow_write, allow_execute

    def resolve_file(self, path: str) -> Path:
        windows = PureWindowsPath(path)
        normalized = path.replace("\\", "/")
        relative = Path(normalized)
        if (not path or relative.is_absolute() or windows.drive or windows.root
                or ".." in relative.parts or ":" in path or "\x00" in path):
            raise SafetyViolation("Expected a relative path inside the project")
        if any(p.lower() in IGNORED_DIRECTORIES for p in relative.parts):
            raise SafetyViolation("Directory is excluded by workspace policy")
        if is_sensitive(relative) or self.ignore.match_file(relative.as_posix()):
            raise SafetyViolation("File is excluded by workspace policy")
        current = self.root
        for part in relative.parts:
            current = current / part
            if is_link(current):
                raise SafetyViolation("Symbolic links and junctions are not readable")
        resolved = current.resolve(strict=True)
        if not resolved.is_relative_to(self.root) or not resolved.is_file():
            raise SafetyViolation("File must stay inside the project")
        return resolved

    def read_file(self, path: str) -> str:
        target = self.resolve_file(path)
        if target.stat().st_size > self.max_file_bytes:
            raise SafetyViolation("File exceeds the configured size limit")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags)
        with os.fdopen(descriptor, "rb") as stream:
            if self.resolve_file(path) != target:
                raise SafetyViolation("File location changed while reading")
            data = stream.read(self.max_file_bytes + 1)
        if len(data) > self.max_file_bytes or b"\x00" in data:
            raise SafetyViolation("Binary or oversized files cannot be read")
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise SafetyViolation("Only UTF-8 text files are supported") from error

    def write_file(self, path: str, content: str) -> None:
        if not self.allow_write:
            raise SafetyViolation("File modification requires the approved ChangeSet service")
        from app.execution.file_io import atomic_write
        from app.security.paths import safe_target
        if len(content.encode()) > self.max_file_bytes or "\x00" in content:
            raise SafetyViolation("Only bounded text can be written")
        atomic_write(safe_target(self.root, path), content)

    async def execute(self, argv: list[str], timeout: int = 30) -> ExecutionResult:
        if self.allow_execute:
            from app.execution.commands import CommandRunner
            return await CommandRunner(self.root).run(argv, timeout)
        decision = CommandGuard().inspect(argv)
        if decision.blocked:
            raise SafetyViolation(decision.reason)
        raise SafetyViolation("Process execution requires the guarded validation runner")

    async def run_tests(self) -> ExecutionResult:
        if self.allow_execute:
            from app.execution.process import ValidationRunner
            return await ValidationRunner(self.root, allow_tests=True).run("pytest")
        raise SafetyViolation("Project tests require explicit permission through the validation runner")
