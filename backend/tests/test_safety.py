from pathlib import Path

import pytest

from app.execution.local import LocalExecutionEnvironment
from app.security.command_guard import CommandGuard
from app.security.policy import SafetyViolation
from app.security.risk_classifier import RiskClassifier, RiskLevel


@pytest.mark.parametrize("command", [
    "git status --short", ["rm", "-r", "-f", "/"], ["RM", "-rf", "../"],
    ["git", "reset", "--hard"], ["git", "clean", "-xdf"], ["git", "push", "-f"],
    ["git", "push", "--force-with-lease"], ["shutdown", "/s"], ["reboot"],
    ["cmd", "/c", "del /s /q *"], ["powershell", "-EncodedCommand", "abc"],
    ["Remove-Item", "-Recurse", "-Force", "C:\\"], ["FORMAT", "D:"],
    ["psql", "-c", "DrOp   TABLE users"], ["sqlite3", "data.db", "DROP DATABASE x"],
    ["git", "status", "--short; rm -rf /"], ["git", "status", "$(whoami)"],
    ["git", "-c", "core.sshCommand=evil", "status"], ["/usr/bin/git", "status", "--short"],
    ["python", "-m", "pytest"], ["pip", "install", "unknown"], [], ["git", "diff", "../secret"],
])
def test_guard_denies_unsafe_or_unlisted_commands(command: list[str] | str) -> None:
    decision = CommandGuard().inspect(command)
    assert decision.blocked
    assert decision.requires_user_approval
    assert decision.risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}


def test_guard_read_only_query() -> None:
    assert not CommandGuard().inspect(["git", "status", "--short"]).blocked


@pytest.mark.parametrize(("operation", "path", "risk"), [
    ("read", "main.py", RiskLevel.LOW), ("write", "main.py", RiskLevel.MEDIUM),
    ("write", ".env", RiskLevel.HIGH), ("delete", "x.py", RiskLevel.HIGH),
    ("write", "auth/config.py", RiskLevel.HIGH), ("delete_database", "", RiskLevel.CRITICAL),
])
def test_risk_classifier(operation: str, path: str, risk: RiskLevel) -> None:
    decision = RiskClassifier().classify(operation, path)
    assert decision.risk == risk
    assert decision.blocked == (risk in {RiskLevel.HIGH, RiskLevel.CRITICAL})


@pytest.mark.parametrize("path", [
    "../outside.txt", "app/../../outside.txt", "/etc/passwd", "C:\\Windows\\win.ini",
    "\\\\server\\share", "app\\..\\..\\outside.txt", "main.py:secret", ".env", ".env.production",
    ".git/config", "node_modules/file.py", "id_rsa", "private.pem", "app/credentials.json",
])
def test_file_boundary_blocks_paths(project_dir: Path, path: str) -> None:
    with pytest.raises(SafetyViolation):
        LocalExecutionEnvironment(project_dir).read_file(path)


def test_safe_reads_and_limits(project_dir: Path) -> None:
    environment = LocalExecutionEnvironment(project_dir, max_file_bytes=1024)
    assert "def main" in environment.read_file("app/main.py")
    (project_dir / "big.txt").write_text("a" * 1025)
    (project_dir / "binary.txt").write_bytes(b"hello\x00")
    for name in ("big.txt", "binary.txt"):
        with pytest.raises(SafetyViolation):
            environment.read_file(name)


def test_gitignore_also_applies_to_direct_reads(project_dir: Path) -> None:
    (project_dir / ".gitignore").write_text("app/service.py\n")
    with pytest.raises(SafetyViolation):
        LocalExecutionEnvironment(project_dir).read_file("app/service.py")


def test_symlink_escape(project_dir: Path, tmp_path: Path) -> None:
    target = tmp_path / "outside.txt"
    target.write_text("private")
    try:
        (project_dir / "link.txt").symlink_to(target)
    except OSError:
        pytest.skip("Host does not permit creating symlinks")
    with pytest.raises(SafetyViolation):
        LocalExecutionEnvironment(project_dir).read_file("link.txt")


async def test_phase_one_cannot_write_or_execute(project_dir: Path) -> None:
    environment = LocalExecutionEnvironment(project_dir)
    with pytest.raises(SafetyViolation):
        environment.write_file("new.py", "unsafe")
    with pytest.raises(SafetyViolation):
        await environment.execute(["git", "status", "--short"])
    with pytest.raises(SafetyViolation):
        await environment.run_tests()
    assert not (project_dir / "new.py").exists()
