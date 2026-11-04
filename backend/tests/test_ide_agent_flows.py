from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.base import (
    CompletionReply,
    CompletionRequest,
    LLMProvider,
    ProviderCapabilities,
    ToolCall,
)
from app.services.git import GitService

AUTH = 'def authenticate(token):\n    return token.strip() == ""\n'
AUTH_TESTS = '''from auth import authenticate


def test_valid_session():
    assert authenticate(" valid-session ")


def test_empty_session():
    assert not authenticate("")
'''


class AuthEngineer(LLMProvider):
    name = "scripted_auth_verification"

    def __init__(self):
        self.requests: list[CompletionRequest] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tool_calls=True)

    async def complete(self, request: CompletionRequest) -> str:
        self.requests.append(request)
        return "auth.py:2 compares the normalized session to an empty string. The regression tests specify a valid-session identifier."

    async def respond(self, request: CompletionRequest, tools: list[dict[str, Any]], turns: list[dict[str, Any]] | None = None) -> CompletionReply:
        self.requests.append(request)
        if request.role in {"reviewer", "security"}:
            return CompletionReply(tool_calls=[ToolCall("report", "submit_structured_result", {"approved": True, "score": 9,
                "critical_issues": [], "warnings": [], "suggestions": []})])
        step = sum(item["role"] == "assistant" for item in turns or [])
        if step == 0:
            return CompletionReply(tool_calls=[ToolCall("search", "search_text", {"query": "authenticate"}),
                ToolCall("read", "read_file", {"path": "auth.py"})])
        if request.role == "coder" and step == 1:
            return CompletionReply(tool_calls=[ToolCall("fix", "apply_patch", {"path": "auth.py", "search": 'token.strip() == ""',
                "replace": 'token.strip() == "valid-session"', "reason": "Compare against the valid session identifier"})])
        if request.role == "coder" and step == 2:
            return CompletionReply(tool_calls=[ToolCall("done", "complete_implementation", {"summary": "Login fix is complete", "pending_steps": []})])
        return CompletionReply(content="auth.py:1–2 normalizes the session token and compares it with the accepted value. The inspected source establishes the comparison; runtime behavior requires test evidence.")


def auth_project(client: TestClient, tmp_path: Path) -> tuple[dict[str, Any], AuthEngineer]:
    root = tmp_path / "login"
    root.mkdir()
    (root / "auth.py").write_text(AUTH)
    (root / "test_auth.py").write_text(AUTH_TESTS)
    (root / "AGENTS.md").write_text("Preserve public function names.")
    provider = AuthEngineer()
    client.app.state.chat.provider = provider
    return client.post("/projects/open", json={"path": str(root)}).json(), provider


def test_repository_explanation_debug_fix_and_selected_draft(client: TestClient, tmp_path: Path) -> None:
    project, provider = auth_project(client, tmp_path)
    explained = client.post("/chat", json={"project_id": project["id"], "message": "Explain how authentication works", "mode": "ask"}).json()
    assert explained["status"] == "completed", explained
    assert any(item["file"] == "auth.py" for item in explained["evidence"])
    assert any("Preserve public function names" in request.system for request in provider.requests)
    file = client.get(f"/projects/{project['id']}/file", params={"path": "auth.py"}).json()
    selected = client.post("/chat", json={"project_id": project["id"], "message": "Explain this selected code", "mode": "ask",
        "selected_code": {"file": "auth.py", "start_line": 1, "end_line": 2},
        "working_drafts": [{"file": "auth.py", "base_hash": file["sha256"], "content": "def authenticate(token):\n    return bool(token)\n"}]}).json()
    assert selected["status"] == "completed", selected
    assert any("UNSAVED BUFFER" in request.auxiliary_context and "return bool(token)" in request.auxiliary_context for request in provider.requests)
    assert Path(project["path"], "auth.py").read_text() == AUTH
    fixed = client.post("/chat", json={"project_id": project["id"], "message": "Find why login fails and fix it", "allow_execution": True}).json()
    assert fixed["status"] == "proposed", fixed
    change = client.get(f"/changes/{fixed['change_id']}").json()
    assert change["proposal"]["tests"]["status"] == "passed"
    assert "2 passed" in change["proposal"]["tests"]["stdout"]
    assert Path(project["path"], "auth.py").read_text() == AUTH


async def test_git_review_receives_actual_diff_and_excludes_ignored_content(client: TestClient, tmp_path: Path, settings: Settings) -> None:
    project, provider = auth_project(client, tmp_path)
    root = Path(project["path"])
    git = GitService(settings)
    for argv in (["init"], ["config", "user.email", "forge-test@example.invalid"], ["config", "user.name", "Forge test"], ["add", "."], ["commit", "-m", "fixture"]):
        code, _, error = await git.run(root, list(argv))
        assert code == 0, error
    (root / "auth.py").write_text(AUTH.replace('== ""', '== "valid-session"'))
    (root / "private.py").write_text('private_marker = "do-not-send-this-file"\n')
    (root / ".forgeignore").write_text("private.py\n")
    result = client.post("/chat", json={"project_id": project["id"], "message": "Review my current changes", "mode": "ask"}).json()
    assert result["status"] == "completed", result
    review = next(request for request in provider.requests if request.role == "reviewer")
    assert "diff --git" in review.message and "valid-session" in review.message
    assert "do-not-send-this-file" not in review.message
    artifact = next(item for item in result["artifacts"] if item["type"] == "review")
    assert artifact["data"]["git_repository"]


def test_hooks_queue_approval_and_execute_real_commands(client: TestClient) -> None:
    project = client.post("/projects/new", json={"name": "Hooks"}).json()
    base = f"/projects/{project['id']}"
    config = {"hooks": [{"name": "verify arithmetic", "event": "AfterFileEdit", "argv": ["python", "-c", "print(6 * 7)"]}]}
    assert client.post(base + "/hooks/config", json=config).status_code == 200
    saved = client.post(base + "/files/write", json={"path": "hello.py", "content": 'print("Hello")\n'}).json()
    hook_id = saved["hooks"][0]["id"]
    assert saved["hooks"][0]["evidence"] == "NOT VERIFIED"
    assert client.post(base + f"/hooks/{hook_id}/run", json={"approved": False}).status_code == 403
    result = client.post(base + f"/hooks/{hook_id}/run", json={"approved": True}).json()
    assert result["status"] == "passed" and result["stdout"].strip() == "42"
    assert result["evidence"] == "VERIFIED"
    config["hooks"][0]["argv"] = ["python", "-c", "print('x'); shutdown()"]
    client.post(base + "/hooks/config", json=config)
    saved = client.post(base + "/files/write", json={"path": "next.py", "content": ""}).json()
    assert client.post(base + f"/hooks/{saved['hooks'][0]['id']}/run", json={"approved": True}).status_code == 403


def test_per_file_rejection_revalidates_remaining_scope(client: TestClient) -> None:
    project = client.post("/projects/new", json={"name": "Reject subset"}).json()
    # A two-file proposal is created with the existing native greenfield provider.
    from test_native_tools import NativeEngineer
    provider = NativeEngineer()
    client.app.state.chat.provider = provider
    result = client.post("/chat", json={"project_id": project["id"], "message": "Build calculator with tests", "allow_execution": True}).json()
    assert result["status"] == "proposed", result
    rejected = client.post(f"/changes/{result['change_id']}/reject", json={"files": ["examples"], "allow_execution": True})
    assert rejected.status_code == 200, rejected.text
    proposal = rejected.json()["proposal"]
    assert next(p for p in proposal["files"] if p["path"] == "examples")["rejected"]
    assert proposal["tests"]["status"] == "passed"
    assert rejected.json()["can_apply"]
    applied = client.post(f"/changes/{result['change_id']}/apply", json={})
    assert applied.status_code == 200, applied.text
    assert not Path(project["path"], "examples").exists()


def test_running_task_incorporates_steering_at_safe_boundary(client: TestClient, tmp_path: Path) -> None:
    project, _ = auth_project(client, tmp_path)
    chat = client.app.state.chat

    class Steered(AuthEngineer):
        updated = False

        async def complete(self, request: CompletionRequest) -> str:
            if not self.updated:
                self.updated = True
                next(iter(chat.controls.values())).steer("Focus on empty session handling")
            return await super().complete(request)

    provider = Steered()
    chat.provider = provider
    result = client.post("/chat", json={"project_id": project["id"], "message": "Explain auth", "mode": "ask"}).json()
    assert result["status"] == "completed", result
    assert any("Focus on empty session handling" in request.message for request in provider.requests)
    run = client.get(f"/runs/{result['run_id']}").json()
    assert any(event["type"] == "task_restarted" for event in run["events"])
    assert not chat.controls


def test_task_total_deadline_cleans_up_controls(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    project, _ = auth_project(client, tmp_path)
    chat = client.app.state.chat

    class Slow(AuthEngineer):
        async def complete(self, request: CompletionRequest) -> str:
            await asyncio.sleep(2)
            return "Late answer"

    chat.provider = Slow()
    chat.settings = chat.settings.model_copy(update={"agent_timeout_seconds": 1})
    result = client.post("/chat", json={"project_id": project["id"], "message": "Explain auth", "mode": "ask"}).json()
    assert result["status"] == "paused"
    assert "total time limit" in result["answer"]
    assert not chat.controls
