import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.orchestrator import Orchestrator
from app.agents.tester import TesterAgent
from app.config import Settings
from app.execution.process import ValidationRunner
from app.llm.base import CompletionRequest, LLMProvider
from app.schemas.domain import Intent
from app.security.command_guard import CommandGuard
from app.security.paths import safe_target
from app.security.policy import SafetyViolation


class EngineeringProvider(LLMProvider):
    name = "test_engineering"

    def __init__(self, failing: bool = False):
        self.code_calls = 0
        self.failing = failing
        self.calls: list[str] = []

    async def complete(self, request: CompletionRequest) -> str:
        self.calls.append(request.system)
        if "implementation specialist" in request.system:
            self.code_calls += 1
            test = 'from app.service import greet\n\ndef test_greeting():\n    assert greet("Ada") == "' + ("Wrong" if self.failing else "Welcome Ada") + '"\n'
            return json.dumps({"summary": "Use Welcome greetings with regression coverage.", "files": [
                {"path": "app/service.py", "search": 'return f"Hello {name}"', "replace": 'return f"Welcome {name}"', "reason": "Use the requested greeting."},
                {"path": "tests/test_service.py", "content": test, "reason": "Cover the changed behavior."},
            ]})
        if "JSON matching" in request.system:
            return json.dumps({"approved": True, "score": 9.1, "critical_issues": [], "warnings": [], "suggestions": []})
        return "Evidence: app/service.py:1-3 returns the original greeting. The requested change is small; runtime behavior needs tests."


def setup_project(client: TestClient, project_dir: Path) -> str:
    (project_dir / "app" / "__init__.py").write_text("")
    return str(client.post("/projects/open", json={"path": str(project_dir)}).json()["id"])


def test_multi_intents_and_read_only_modes() -> None:
    decision = Orchestrator().route("Fix this function, write tests, and explain what was wrong", "auto")
    assert {Intent.DEBUG, Intent.EDIT, Intent.TEST, Intent.EXPLAIN} <= set(decision.intents)
    assert decision.workflow == "modify"
    assert Orchestrator().route("Implement JWT authentication", "ask").read_only
    assert Orchestrator().route("Plan how to fix this bug", "auto").workflow == "plan"
    assert Orchestrator().route("Explain the tests", "auto").workflow == "explain"
    assert Orchestrator().route("Run tests and fix anything that fails", "auto").workflow == "modify"


def test_proposal_gates_validation_apply_and_persisted_cards(client: TestClient, project_dir: Path) -> None:
    provider = EngineeringProvider()
    client.app.state.chat.provider = provider  # type: ignore[union-attr]
    project_id = setup_project(client, project_dir)
    original = (project_dir / "app" / "service.py").read_text()
    result = client.post("/chat", json={"project_id": project_id, "message": "Fix greet to say Welcome and write tests.", "selected_files": ["app/service.py"]}).json()
    assert result["status"] == "awaiting_approval", result
    assert provider.code_calls == 1
    assert (project_dir / "app" / "service.py").read_text() == original
    change_id = result["change_id"]
    assert client.post(f"/changes/{change_id}/apply", json={}).status_code == 403
    validation = client.post(f"/changes/{change_id}/validate", json={"allow_execution": True})
    assert validation.status_code == 200, validation.text
    assert validation.json()["proposal"]["tests"]["status"] == "passed", validation.json()
    assert validation.json()["can_apply"]
    applied = client.post(f"/changes/{change_id}/apply", json={"files": ["app/service.py"]})
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "partially_applied"
    assert "Welcome" in (project_dir / "app" / "service.py").read_text()
    assert client.post(f"/changes/{change_id}/apply", json={}).json()["status"] == "applied"
    history = client.get(f"/projects/{project_id}/conversations/{result['conversation_id']}").json()
    assert history[-1]["result"]["change_id"] == change_id
    assert {a["type"] for a in result["artifacts"]} >= {"context", "plan", "changes", "tests", "security", "review", "changeset"}


def test_repair_attempts_are_bounded(client: TestClient, project_dir: Path) -> None:
    provider = EngineeringProvider(failing=True)
    client.app.state.chat.provider = provider  # type: ignore[union-attr]
    project_id = setup_project(client, project_dir)
    result = client.post("/chat", json={"project_id": project_id, "message": "Fix greet and write tests", "selected_files": ["app/service.py"], "allow_execution": True}).json()
    assert provider.code_calls == 3, result
    assert result["status"] == "blocked", result
    assert not (project_dir / "tests" / "test_service.py").exists()
    assert client.get(f"/changes/{result['change_id']}").json()["proposal"]["attempts"] == 3


def test_source_conflict_reject_and_modes_cannot_apply(client: TestClient, project_dir: Path) -> None:
    provider = EngineeringProvider()
    client.app.state.chat.provider = provider  # type: ignore[union-attr]
    project_id = setup_project(client, project_dir)
    request = {"project_id": project_id, "message": "Fix greet and write tests", "selected_files": ["app/service.py"], "allow_execution": True}
    readonly = client.post("/chat", json={**request, "mode": "ask"}).json()
    assert readonly["status"] == "completed" and provider.code_calls == 0
    result = client.post("/chat", json=request).json()
    assert result["status"] == "proposed", result
    (project_dir / "app" / "service.py").write_text("# external change\n")
    assert client.post(f"/changes/{result['change_id']}/apply", json={}).status_code == 403
    assert client.post(f"/changes/{result['change_id']}/reject").json()["status"] == "rejected"
    assert client.post(f"/changes/{result['change_id']}/apply", json={}).status_code == 403


def test_browser_import_is_a_snapshot_with_same_read_policy(client: TestClient, settings: Settings) -> None:
    result = client.post("/projects/import", json={"name": "Browser project", "files": [{"path": "src/main.py", "content": "value = 42\n"}]} )
    assert result.status_code == 200, result.text
    project = result.json()
    assert project["source_kind"] == "browser"
    assert Path(project["path"]).parent == settings.data_directory / "imports"
    assert client.get(f"/projects/{project['id']}/file", params={"path": "src/main.py"}).json()["content"] == "value = 42\n"
    assert client.post(f"/projects/{project['id']}/refresh").json()["source_kind"] == "browser"
    for path in ("../escape.py", ".env", "x/../../escape.py", "C:/bad.py", "nul.py", "a//b.py"):
        blocked = client.post("/projects/import", json={"name": "unsafe", "files": [{"path": path, "content": "bad"}]})
        assert blocked.status_code == 403, (path, blocked.text)


def test_selected_lines_are_validated_on_server(client: TestClient, project_dir: Path) -> None:
    project_id = setup_project(client, project_dir)
    result = client.post("/chat", json={"project_id": project_id, "message": "Explain this", "selected_code": {"file": "app/main.py", "start_line": 3, "end_line": 5}}).json()
    assert result["evidence"][0]["start_line"] == 3
    invalid = client.post("/chat", json={"project_id": project_id, "message": "Explain", "selected_code": {"file": "../outside.py", "start_line": 1, "end_line": 2}}).json()
    assert invalid["status"] == "failed"


def test_tool_policy_stays_default_deny(project_dir: Path) -> None:
    safe = ["python", "-I", "-m", "pytest", "-q", "--maxfail=3", "-o", "pythonpath=.", "tests/test_main.py"]
    assert CommandGuard().inspect(safe).blocked
    assert not CommandGuard().inspect(safe, allow_tools=True).blocked
    for suffix in (["--override-ini=x"], ["../test.py"], ["C:/test.py"], ["evil.py;shutdown"]):
        assert CommandGuard().inspect(safe[:-1] + suffix, allow_tools=True).blocked
    with pytest.raises(SafetyViolation):
        safe_target(project_dir, "app/../secret.py")


async def test_runner_requires_consent_and_enforces_timeout_and_redaction(project_dir: Path) -> None:
    (project_dir / "test_slow.py").write_text("import time\n\ndef test_slow():\n    time.sleep(20)\n")
    with pytest.raises(SafetyViolation):
        await ValidationRunner(project_dir).run("pytest")
    result = await ValidationRunner(project_dir, allow_tests=True, output_limit=1024).run("pytest", timeout=1)
    assert result.timed_out
    assert len(result.stdout) <= 1024


async def test_tests_cannot_approve_modified_snapshot(project_dir: Path, settings: Settings) -> None:
    (project_dir / "source.py").write_text("value = 1\n")
    (project_dir / "test_mutate.py").write_text(
        "from pathlib import Path\n\ndef test_mutation():\n    Path('source.py').write_text('value = 2\\n')\n")
    result = await TesterAgent().run(project_dir, ["source.py", "test_mutate.py"], settings, True)
    assert result.exit_code == 0
    assert result.status == "failed"
    assert "modified indexed validation source" in result.summary
