import asyncio
import shutil
from pathlib import Path

import pytest

from app.config import Settings
from app.execution.commands import CommandRunner
from app.execution.local import LocalExecutionEnvironment
from app.execution.terminal import TerminalManager
from app.schemas.domain import ProjectView
from app.schemas.workspace import GitAction
from app.security.command_guard import CommandGuard
from app.security.policy import SafetyViolation
from app.services.git import GitService


async def test_real_guarded_command_and_timeout(project_dir: Path) -> None:
    (project_dir / "hello.py").write_text('print("FORGE_COMMAND_OK")\n')
    result = await LocalExecutionEnvironment(project_dir, allow_execute=True).execute(["python", "hello.py"])
    assert result.exit_code == 0
    assert "FORGE_COMMAND_OK" in result.stdout
    assert not CommandGuard().development(["ruff", "format", "hello.py"]).blocked
    for argv in (["rm", "-rf", "/"], ["git", "push", "--force"], ["python", "../outside.py"], ["bash", "-c", "echo x"]):
        assert CommandGuard().development(argv).blocked
    with pytest.raises(SafetyViolation):
        await CommandRunner(project_dir).run(["pip", "install", "requests"])


async def test_real_manual_terminal_input_output_and_cleanup(project_dir: Path) -> None:
    manager = TerminalManager()
    with pytest.raises(SafetyViolation):
        await manager.create(LocalExecutionEnvironment(project_dir), "project", 80, 24)
    session = await manager.create(LocalExecutionEnvironment(project_dir, agent=False, allow_execute=True), "project", 80, 24)
    try:
        import os
        command = "set /a taskCalc=6*7\recho RESULT_%taskCalc%\r" if os.name == "nt" else "printf 'RESULT_%s\\n' $((6*7))\r"
        await manager.write(session, command)
        for _ in range(80):
            if "RESULT_42" in "".join(event["data"] for event in session.events):
                break
            await asyncio.sleep(0.1)
        assert "RESULT_42" in "".join(event["data"] for event in session.events)
    finally:
        await manager.close(session)
    assert session.closed
    assert not session.process.isalive()


@pytest.mark.skipif(not shutil.which("git"), reason="Git is not installed")
async def test_real_git_stage_unstage_commit_branch(project_dir: Path, settings: Settings) -> None:
    from app.code_intelligence.repository_scanner import ProjectScanner
    project = ProjectView(id="git-test", name="sample", path=str(project_dir), project_map=ProjectScanner(settings).scan(project_dir))
    service = GitService(settings)
    await service.action(project, GitAction(action="init"))
    await service.run(project_dir, ["config", "user.name", "Forge verification"])
    await service.run(project_dir, ["config", "user.email", "verification@example.invalid"])
    await service.action(project, GitAction(action="stage", paths=["app/main.py"]))
    assert any(file["staged"] for file in (await service.status(project))["files"])
    await service.action(project, GitAction(action="unstage", paths=["app/main.py"]))
    assert (project_dir / "app/main.py").exists()
    await service.action(project, GitAction(action="stage", paths=["app/main.py"]))
    await service.action(project, GitAction(action="commit", message="Verify manual Git\n\nKeep source intact."))
    await service.action(project, GitAction(action="branch", branch="codex/verification"))
    assert (await service.status(project))["branch"] == "codex/verification"
    (project_dir / "app/main.py").write_text("# changed\n")
    assert "changed" in (await service.diff(project))["patch"]
