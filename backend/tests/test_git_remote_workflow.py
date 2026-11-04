"""Real Git state; network transport is substituted with an owned local bare repo."""
from pathlib import Path
from typing import Any

import pytest

from app.code_intelligence.repository_scanner import ProjectScanner
from app.config import Settings
from app.schemas.domain import ProjectView
from app.schemas.workspace import GitAction
from app.security.policy import SafetyViolation
from app.services.git import GitService

URL = "https://github.com/forge-tests/owned-repository.git"


class LocalTransportGit(GitService):
    def __init__(self, settings: Settings, bare: Path):
        super().__init__(settings)
        self.bare = bare
        self.sent: list[list[str]] = []

    async def run(self, root: Path, args: list[str], timeout: int = 30, *, network: bool = False) -> tuple[int, str, str]:
        if network:
            self.sent.append(args)
            args = [str(self.bare) if arg == URL else arg for arg in args]
        return await super().run(root, args, timeout, network=False)


async def repository(tmp_path: Path, settings: Settings) -> tuple[LocalTransportGit, ProjectView, Path]:
    root, bare = tmp_path / "work", tmp_path / "remote.git"
    root.mkdir()
    bare.mkdir()
    service = LocalTransportGit(settings, bare)
    assert (await service.run(bare, ["init", "--bare"]))[0] == 0
    assert (await service.run(root, ["init", "-b", "main"]))[0] == 0
    await service.run(root, ["config", "user.name", "Forge test"])
    await service.run(root, ["config", "user.email", "test@example.invalid"])
    (root / "hello.txt").write_text("original\n")
    await service.run(root, ["add", "--", "hello.txt"])
    assert (await service.run(root, ["commit", "--no-gpg-sign", "-m", "Initial"] ))[0] == 0
    await service.run(root, ["remote", "add", "origin", URL])
    project = ProjectView(id="test", name="work", path=str(root), project_map=ProjectScanner(settings).scan(root))
    return service, project, bare


@pytest.mark.asyncio
async def test_branch_edit_stage_commit_push_fetch_pull_verified(tmp_path: Path, settings: Settings) -> None:
    service, project, bare = await repository(tmp_path, settings)
    await service.action(project, GitAction(action="branch", branch="feature/calculator"))
    path = Path(project.path) / "hello.txt"
    path.write_text("approved edit\n")
    assert (await service.status(project))["files"][0]["status"] == " M"
    await service.action(project, GitAction(action="stage", paths=["hello.txt"]))
    await service.action(project, GitAction(action="commit", message="Fix greeting"))
    target = await service.network_target(project, "origin", push=True)
    with pytest.raises(SafetyViolation, match="confirmation"):
        await service.action(project, GitAction(action="push", branch=target["branch"]))
    assert not service.sent
    result = await service.action(project, GitAction(action="push", branch=target["branch"], confirmed=True, expected_url=target["url"], expected_head=target["head"]))
    assert result["remote_verified"] is True
    assert (await service.run(bare, ["rev-parse", "refs/heads/feature/calculator"]))[1].strip() == target["head"]
    assert not any("--force" in arg or arg.startswith("+") for args in service.sent for arg in args)
    assert (await service.action(project, GitAction(action="fetch", branch=target["branch"], confirmed=True)))["status"] == "completed"
    # Another owned checkout creates an actual incoming commit.
    other = tmp_path / "other"
    other.mkdir()
    assert (await service.run(other, ["clone", "--branch", target["branch"], "--", str(bare), "."]))[0] == 0
    await service.run(other, ["config", "user.name", "Forge test"])
    await service.run(other, ["config", "user.email", "test@example.invalid"])
    (other / "hello.txt").write_text("incoming change\n")
    await service.run(other, ["add", "--", "hello.txt"])
    await service.run(other, ["commit", "--no-gpg-sign", "-m", "Incoming"])
    assert (await service.run(other, ["push", "origin", target["branch"]]))[0] == 0
    pulled = await service.action(project, GitAction(action="pull", branch=target["branch"], confirmed=True))
    assert pulled["status"] == "completed" and path.read_text() == "incoming change\n"


@pytest.mark.asyncio
async def test_dirty_switch_pull_changed_destination_and_remote_failure(tmp_path: Path, settings: Settings) -> None:
    service, project, _ = await repository(tmp_path, settings)
    target = await service.network_target(project, "origin", push=True)
    path = Path(project.path) / "hello.txt"
    path.write_text("manual work\n")
    with pytest.raises(SafetyViolation, match="working-tree"):
        await service.action(project, GitAction(action="switch", branch="main"))
    with pytest.raises(SafetyViolation, match="local changes"):
        await service.action(project, GitAction(action="pull", branch="main", confirmed=True))
    with pytest.raises(SafetyViolation, match="destination or commit changed"):
        await service.action(project, GitAction(action="push", branch="main", confirmed=True, expected_url=URL + "changed", expected_head=target["head"]))
    # Fixed local receive policy simulates a real permission rejection, not a mocked success response.
    await service.run(service.bare, ["config", "receive.denyCurrentBranch", "refuse"])
    await service.run(service.bare, ["config", "core.bare", "false"])
    await service.run(service.bare, ["symbolic-ref", "HEAD", "refs/heads/main"])
    with pytest.raises(SafetyViolation, match="operation failed"):
        await service.action(project, GitAction(action="push", branch="main", confirmed=True, expected_url=URL, expected_head=target["head"]))
    assert path.read_text() == "manual work\n"


@pytest.mark.asyncio
async def test_real_conflict_versions_and_resolution(tmp_path: Path, settings: Settings) -> None:
    service, project, _ = await repository(tmp_path, settings)
    root = Path(project.path)
    await service.action(project, GitAction(action="branch", branch="other"))
    (root / "hello.txt").write_text("incoming\n")
    await service.action(project, GitAction(action="stage", paths=["hello.txt"]))
    await service.action(project, GitAction(action="commit", message="Other side"))
    await service.action(project, GitAction(action="switch", branch="main"))
    (root / "hello.txt").write_text("current\n")
    await service.action(project, GitAction(action="stage", paths=["hello.txt"]))
    await service.action(project, GitAction(action="commit", message="Current side"))
    assert (await service.run(root, ["merge", "--no-edit", "other"]))[0] != 0
    detail = await service.conflicts(project, "hello.txt")
    assert detail["base"] == "original\n" and detail["current"] == "current\n" and detail["incoming"] == "incoming\n"
    assert (await service.status(project))["files"][0]["status"] == "UU"
    (root / "hello.txt").write_text("reviewed resolution\n")
    await service.action(project, GitAction(action="stage", paths=["hello.txt"]))
    await service.action(project, GitAction(action="commit", message="Resolve conflict"))
    assert (await service.status(project))["files"] == []


@pytest.mark.parametrize("url", ["https://token@github.com/a/b.git", "https://github.com/a/b?token=secret", "ext::cmd", "file:///tmp/repo", "--upload-pack=evil", "https://github.com/a/b\n-c core.sshCommand=evil"])
def test_remote_url_validation(url: str) -> None:
    with pytest.raises(SafetyViolation):
        GitService.validate_url(url)


@pytest.mark.parametrize("branch", ["--force", "a..b", "a/.hidden", "a.lock/x", "a//b", "a/", "x;whoami"])
def test_branch_validation(branch: str) -> None:
    with pytest.raises(SafetyViolation):
        GitService.validate_branch(branch)


@pytest.mark.asyncio
async def test_repo_helper_is_not_trusted_for_network(tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.execution.base import ExecutionResult
    from app.execution.commands import CommandRunner
    seen: list[list[str]] = []
    async def run(self: CommandRunner, argv: list[str], timeout: int, **kwargs: Any) -> ExecutionResult:
        seen.append(argv)
        # Only the fixed user's global helper is eligible.
        output = "manager\n" if "--global" in argv else ""
        return ExecutionResult(exit_code=0, stdout=output, stderr="", timed_out=False)
    monkeypatch.setattr(CommandRunner, "run", run)
    await GitService(settings).run(tmp_path, ["ls-remote", URL], network=True)
    final = seen[-1]
    assert "credential.helper=" in final and "credential.helper=manager" in final
    assert "protocol.allow=never" in final and "protocol.https.allow=always" in final
    assert "http.sslVerify=true" in final
    assert all("--local" not in argv for argv in seen)
