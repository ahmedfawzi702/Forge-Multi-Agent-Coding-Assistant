"""Progress control with real files/validators, fault-injected model decisions."""
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.graph.runtime import RunRuntime, RuntimeStopped, current_runtime
from app.llm.base import (
    CompletionReply,
    CompletionRequest,
    LLMProvider,
    ProviderCapabilities,
    ProviderError,
    ToolCall,
)
from app.models.entities import RunCheckpoint
from app.schemas.domain import ChatRequest, ProjectView
from app.services.preferences import PermissionPolicy
from app.tools.registry import ToolRegistry

APP = '''from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}
'''
APP_TEST = '''from fastapi.testclient import TestClient
from app import app


def test_health():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
'''


class ScenarioProvider(LLMProvider):
    name = "progress_scenario_fixture"

    def __init__(self, files: dict[str, str], *, repeat_reads: bool = False, review_failures: int = 0, outage_after_write: bool = False):
        self.files, self.repeat_reads, self.review_failures, self.outage_after_write = files, repeat_reads, review_failures, outage_after_write
        self.requests: list[CompletionRequest] = []
        self.attempts = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tool_calls=True)

    async def complete(self, request: CompletionRequest) -> str:
        self.requests.append(request)
        return "app.py:4–5 defines the health function. This is inspected source evidence; no runtime execution is claimed."

    async def respond(self, request: CompletionRequest, tools: list[dict[str, Any]], turns: list[dict[str, Any]] | None = None) -> CompletionReply:
        self.requests.append(request)
        if request.role in {"security", "reviewer"}:
            if request.role == "reviewer" and self.review_failures:
                self.review_failures -= 1
                raise ProviderError("Fixture provider temporarily unavailable")
            return CompletionReply(tool_calls=[ToolCall("report", "submit_structured_result", {
                "approved": True, "score": 9, "critical_issues": [], "warnings": [], "suggestions": []})])
        if tools[0]["function"]["name"] == "submit_structured_result":
            return CompletionReply(tool_calls=[ToolCall("implementation", "submit_structured_result", {
                "summary": "Implement the requested files", "files": [{"path": path, "content": content, "reason": "Requested implementation"} for path, content in self.files.items()]})])
        if not turns and "previous edits already exist" in request.message.lower() and "Verification feedback to repair" not in request.message:
            return CompletionReply(tool_calls=[ToolCall("done", "complete_implementation", {"summary": "Preserved implementation is complete", "pending_steps": []})])
        if not turns:
            self.attempts += 1
            if self.repeat_reads:
                return CompletionReply(tool_calls=[ToolCall("repeat", "search_files", {"query": "auth"})])
            editing = "write_file" if "previous edits already exist" in request.message.lower() else "create_file"
            return CompletionReply(tool_calls=[ToolCall(f"write{i}", editing, {"path": path, "content": content, "reason": "Requested implementation"}) for i, (path, content) in enumerate(self.files.items())])
        if self.repeat_reads:
            return CompletionReply(tool_calls=[ToolCall("repeat", "search_files", {"query": "auth"})])
        if self.outage_after_write:
            self.outage_after_write = False
            raise ProviderError("Fixture model connection interrupted after source was staged")
        return CompletionReply(tool_calls=[ToolCall("done", "complete_implementation", {"summary": "Requested implementation and tests are complete", "pending_steps": []})])


def new_project(client: TestClient, name: str = "Progress") -> dict[str, Any]:
    return client.post("/projects/new", json={"name": name}).json()


def run(client: TestClient, project: dict[str, Any], message: str, provider: LLMProvider, **extra: Any) -> dict[str, Any]:
    client.app.state.chat.provider = provider
    response = client.post("/chat", json={"project_id": project["id"], "message": message, "allow_execution": True, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_hello_fast_path_has_one_write_no_exploration(client: TestClient) -> None:
    project = new_project(client, "Hello fast path")
    provider = ScenarioProvider({"hello.py": 'print("Hello World")\n'})
    result = run(client, project, "Create hello.py that prints Hello World", provider)
    assert result["status"] == "proposed", result
    metrics = result["diagnostics"]
    assert metrics["tool_calls"] == 2  # one edit, actual script run; strict AST checks need no subprocess
    assert metrics["write_calls"] == 1 and metrics["search_calls"] == 0 and metrics["read_calls"] == 0
    assert metrics["llm_calls"] == 1 and metrics["test_calls"] == 1
    change = client.get(f"/changes/{result['change_id']}").json()
    assert change["can_apply"] and change["proposal"]["tests"]["stdout"].strip() == "Hello World"
    assert change["proposal"]["review"]["kind"] == "deterministic_trivial"
    assert not Path(project["path"], "hello.py").exists()
    assert client.post(f"/changes/{result['change_id']}/apply", json={}).status_code == 200
    assert Path(project["path"], "hello.py").read_text() == 'print("Hello World")\n'


def test_empty_fastapi_with_fix_errors_does_not_enter_debugger(client: TestClient) -> None:
    project = new_project(client)
    provider = ScenarioProvider({"app.py": APP, "test_app.py": APP_TEST})
    result = run(client, project, "Create a FastAPI app with a /health endpoint and one pytest test. Fix any errors you discover; do not stop at planning.", provider)
    assert result["status"] == "proposed", result
    assert not any(request.role == "debugger" for request in provider.requests)
    assert result["diagnostics"]["search_calls"] == 0
    assert result["diagnostics"]["write_calls"] == 2
    assert result["diagnostics"]["test_calls"] == 1
    assert result["diagnostics"]["stage_history"] == ["UNDERSTAND", "CONTEXT", "PLAN", "IMPLEMENT", "VALIDATE", "SECURITY", "TEST", "REVIEW", "FINALIZE"]
    events = client.get(f"/runs/{result['run_id']}").json()["events"]
    types = [event["type"] for event in events]
    assert types.count("plan_created") == 1
    assert types.index("changeset_updated") < types.index("test_result")
    assert client.get(f"/runs/{result['run_id']}/diagnostics").json()["diagnostics"] == result["diagnostics"]


async def test_duplicate_cache_invalidates_when_file_changes(client: TestClient, settings: Settings, project_dir: Path) -> None:
    project = ProjectView.model_validate(client.post("/projects/open", json={"path": str(project_dir)}).json())
    runtime = RunRuntime(settings)
    token = current_runtime.set(runtime)
    try:
        registry = ToolRegistry(project, settings, PermissionPolicy(settings, ChatRequest(project_id=project.id, message="Fix")), [], role="coder")
        first = await registry.execute("read_file", {"path": "app/service.py"})
        second = await registry.execute("read_file", {"path": "app/service.py"})
        third = await registry.execute("read_file", {"path": "app/service.py"})
        assert "cached" not in first and second["cached"]
        assert third["signal"] == "REPEATED_TOOL_CALL" and runtime.cache_hits == 2
        assert runtime.tool_calls == 1 and runtime.repeated_calls == 1
        (project_dir / "app/service.py").write_text("def greet(name):\n    return name\n")
        changed = await registry.execute("read_file", {"path": "app/service.py"})
        assert "cached" not in changed and "return name" in changed["content"]
        assert runtime.tool_calls == 2
    finally:
        current_runtime.reset(token)


async def test_context_budget_does_not_consume_write_budget(client: TestClient, settings: Settings, project_dir: Path) -> None:
    settings = settings.model_copy(update={"forge_max_context_searches": 1, "forge_max_context_file_reads": 1})
    project = ProjectView.model_validate(client.post("/projects/open", json={"path": str(project_dir)}).json())
    registry = ToolRegistry(project, settings, PermissionPolicy(settings, ChatRequest(project_id=project.id, message="Fix")), [], role="coder")
    await registry.execute("search_files", {"query": "service"})
    assert (await registry.execute("search_files", {"query": "main"}))["signal"] == "IMPLEMENT_NOW"
    await registry.execute("read_file", {"path": "app/service.py"})
    assert (await registry.execute("read_file", {"path": "app/main.py"}))["signal"] == "IMPLEMENT_NOW"
    assert (await registry.execute("create_file", {"path": "new.py", "content": "value = 1\n", "reason": "Create requested code"}))["status"] == "staged"


def test_repeated_exploration_forces_concrete_implementation(client: TestClient) -> None:
    provider = ScenarioProvider({"hello.py": 'print("Hello World")\n'}, repeat_reads=True)
    result = run(client, new_project(client), "Create hello.py that prints Hello World", provider)
    assert result["status"] == "proposed", result
    assert result["diagnostics"]["llm_calls"] == 3  # two faulty inspection replies, then a schema-only implementation
    assert result["diagnostics"]["write_calls"] == 1


def test_review_outage_resumes_review_without_reimplementing_or_retesting(client: TestClient) -> None:
    project = new_project(client)
    provider = ScenarioProvider({"app.py": APP, "test_app.py": APP_TEST}, review_failures=1)
    result = run(client, project, "Create a FastAPI app with a health endpoint and pytest test", provider)
    assert result["status"] == "paused" and result["resumable"], result
    checkpoint = client.get(f"/runs/{result['run_id']}/diagnostics").json()["checkpoint"]
    assert checkpoint["stage"] == "REVIEW"
    resumed = client.post(f"/runs/{result['run_id']}/resume", json={"allow_execution": True}).json()
    assert resumed["status"] == "proposed", resumed
    assert resumed["change_id"] == result["change_id"]
    assert resumed["diagnostics"]["write_calls"] == 0 and resumed["diagnostics"]["test_calls"] == 0
    assert resumed["diagnostics"]["llm_calls"] == 1 and provider.attempts == 1


def test_global_limit_preserves_work_and_resume_starts_at_validation(client: TestClient) -> None:
    project = new_project(client)
    chat = client.app.state.chat
    chat.settings = chat.settings.model_copy(update={"forge_max_tool_calls": 3})
    provider = ScenarioProvider({"app.py": APP, "test_app.py": APP_TEST})
    result = run(client, project, "Implement JWT authentication foundation with health endpoint and tests", provider)
    assert result["status"] == "paused" and result["change_id"] and result["resumable"], result
    assert "Global tool operation limit" in result["answer"]
    assert result["diagnostics"]["tool_calls"] == 3
    change = client.get(f"/changes/{result['change_id']}").json()
    assert not change["can_apply"] and len(change["proposal"]["files"]) == 2
    assert client.get(f"/runs/{result['run_id']}/diagnostics").json()["checkpoint"]["stage"] == "VALIDATE"
    chat.settings = chat.settings.model_copy(update={"forge_max_tool_calls": 64})
    resumed = client.post(f"/runs/{result['run_id']}/resume", json={"allow_execution": True}).json()
    assert resumed["status"] == "proposed", resumed
    assert resumed["diagnostics"]["write_calls"] == 0 and resumed["diagnostics"]["test_calls"] == 1
    assert resumed["diagnostics"]["stage_history"][0] == "VALIDATE"
    assert provider.attempts == 1


def test_provider_interruption_preserves_first_writes(client: TestClient) -> None:
    provider = ScenarioProvider({"app.py": APP, "test_app.py": APP_TEST}, outage_after_write=True)
    result = run(client, new_project(client), "Create a FastAPI health endpoint and test", provider)
    assert result["status"] == "paused" and result["change_id"], result
    with client.app.state.chat.sessions() as session:
        checkpoint = session.get(RunCheckpoint, result["run_id"])
        assert checkpoint and checkpoint.payload["next_stage"] == "IMPLEMENT"
        assert len(checkpoint.payload["engineering"]["files"]) == 2
        assert Path(checkpoint.payload["engineering"]["stage_path"], "app.py").exists()


def test_resume_rejects_changed_source(client: TestClient) -> None:
    project = new_project(client)
    result = run(client, project, "Create a FastAPI health endpoint and test", ScenarioProvider({"app.py": APP, "test_app.py": APP_TEST}, review_failures=1))
    client.post(f"/projects/{project['id']}/files/write", json={"path": "app.py", "content": "# manual work\n"})
    resumed = client.post(f"/runs/{result['run_id']}/resume", json={"allow_execution": True}).json()
    assert resumed["status"] == "failed" and "manually" in resumed["answer"], resumed
    assert Path(project["path"], "app.py").read_text() == "# manual work\n"


def test_explanation_fast_path_has_no_coder_tester_security(client: TestClient) -> None:
    project = new_project(client)
    client.post(f"/projects/{project['id']}/files/write", json={"path": "app.py", "content": "def health():\n    return True\n"})
    provider = ScenarioProvider({})
    result = run(client, project, "Explain this function", provider, mode="ask", selected_files=["app.py"])
    assert result["status"] == "completed", result
    assert result["diagnostics"]["llm_calls"] == 1 and result["diagnostics"]["tool_calls"] == 0
    assert result["diagnostics"]["read_calls"] == 1
    assert [request.role for request in provider.requests] == ["explainer"]


def test_global_step_limit_is_a_last_resort(settings: Settings) -> None:
    runtime = RunRuntime(settings.model_copy(update={"forge_max_agent_steps": 5}))
    for _ in range(5):
        runtime.step()
    with pytest.raises(RuntimeStopped, match="Global agent step"):
        runtime.step()


async def test_text_search_bounds_actual_source_reads(client: TestClient, settings: Settings, project_dir: Path) -> None:
    for number in range(20):
        (project_dir / f"module_{number}.py").write_text(f"value = {number}\n")
    settings = settings.model_copy(update={"forge_max_context_file_reads": 2})
    project = ProjectView.model_validate(client.post("/projects/open", json={"path": str(project_dir)}).json())
    runtime = RunRuntime(settings)
    token = current_runtime.set(runtime)
    try:
        registry = ToolRegistry(project, settings, PermissionPolicy(settings, ChatRequest(project_id=project.id, message="Inspect")), [])
        first = await registry.execute("search_text", {"query": "value"})
        assert len(first["searched_files"]) == 2 and first["truncated"]
        assert runtime.read_calls == 2 and runtime.search_calls == 1
        await registry.execute("search_text", {"query": "def"})
        assert runtime.read_calls == 2  # cached contents or exhausted source budget
    finally:
        current_runtime.reset(token)


def test_small_login_edit_reuses_only_task_local_context(client: TestClient, project_dir: Path) -> None:
    (project_dir / "login.py").write_text('def normalize_username(value):\n    return value.strip().lower()[:-1]\n')
    (project_dir / "test_login.py").write_text('from login import normalize_username\n\n\ndef test_login():\n    assert normalize_username(" Alice ") == "alice"\n')
    for number in range(40):
        (project_dir / f"irrelevant_{number}.py").write_text(f"data = {number}\n")
    project = client.post("/projects/open", json={"path": str(project_dir)}).json()

    class PatchProvider(ScenarioProvider):
        async def respond(self, request, tools, turns=None):
            if request.role == "coder" and not turns:
                self.requests.append(request)
                self.attempts += 1
                return CompletionReply(tool_calls=[ToolCall("fix", "apply_patch", {"path": "login.py", "search": ".lower()[:-1]", "replace": ".lower()", "reason": "Preserve the last username character"})])
            return await super().respond(request, tools, turns)

    provider = PatchProvider({})
    result = run(client, project, "Fix the bug in login", provider)
    assert result["status"] == "proposed", result
    assert result["diagnostics"]["read_calls"] == 2 and result["diagnostics"]["search_calls"] == 0
    assert result["diagnostics"]["write_calls"] == 1 and result["diagnostics"]["test_calls"] == 1
    assert {chunk.evidence.file for request in provider.requests if request.role == "coder" for chunk in request.context} == {"login.py", "test_login.py"}


def test_critical_review_revisions_are_capped_without_replanning(client: TestClient) -> None:
    client.app.state.chat.settings = client.app.state.chat.settings.model_copy(update={"forge_max_repair_attempts": 5, "forge_max_review_revisions": 1})

    class CriticalReviewer(ScenarioProvider):
        async def respond(self, request, tools, turns=None):
            if request.role == "reviewer":
                self.requests.append(request)
                return CompletionReply(tool_calls=[ToolCall("review", "submit_structured_result", {"approved": False, "score": 3,
                    "critical_issues": ["Deliberate review defect for cycle-limit verification"], "warnings": [], "suggestions": []})])
            return await super().respond(request, tools, turns)

    provider = CriticalReviewer({"app.py": APP, "test_app.py": APP_TEST})
    result = run(client, new_project(client), "Create a FastAPI health endpoint and test", provider)
    assert result["status"] == "blocked", result
    assert provider.attempts == 2 and result["diagnostics"]["retry_count"] == 1
    events = client.get(f"/runs/{result['run_id']}").json()["events"]
    assert sum(event["type"] == "plan_created" for event in events) == 1


def test_resume_checks_staged_integrity(client: TestClient) -> None:
    result = run(client, new_project(client), "Create a FastAPI health endpoint and test", ScenarioProvider({"app.py": APP, "test_app.py": APP_TEST}, review_failures=1))
    with client.app.state.chat.sessions() as session:
        saved = session.get(RunCheckpoint, result["run_id"]).payload
    Path(saved["engineering"]["stage_path"], "app.py").write_text("# unexpected external stage edit\n")
    resumed = client.post(f"/runs/{result['run_id']}/resume", json={"allow_execution": True}).json()
    assert resumed["status"] == "failed" and "Working source changed" in resumed["answer"]


def test_resume_requires_fresh_execution_permission(client: TestClient) -> None:
    project = new_project(client)
    provider = ScenarioProvider({"app.py": APP, "test_app.py": APP_TEST})
    client.app.state.chat.settings = client.app.state.chat.settings.model_copy(update={"forge_max_tool_calls": 2})
    result = run(client, project, "Create a FastAPI health endpoint and test", provider)
    client.app.state.chat.settings = client.app.state.chat.settings.model_copy(update={"forge_max_tool_calls": 64})
    resumed = client.post(f"/runs/{result['run_id']}/resume", json={"allow_execution": False}).json()
    assert resumed["status"] == "awaiting_approval" and resumed["diagnostics"]["test_calls"] == 0


def test_resume_lease_blocks_shared_stage_but_not_unrelated_tasks(client: TestClient) -> None:
    from app.models.entities import AgentRun
    from app.security.policy import SafetyViolation
    from app.services.run_checkpoints import RunCheckpointStore

    project = new_project(client)
    result = run(client, project, "Create a FastAPI health endpoint and test", ScenarioProvider({"app.py": APP, "test_app.py": APP_TEST}, review_failures=1))
    sessions = client.app.state.chat.sessions
    with sessions.begin() as session:
        continuation = AgentRun(project_id=project["id"], conversation_id=result["conversation_id"], status="running")
        other = AgentRun(project_id=project["id"], conversation_id=result["conversation_id"], status="failed")
        session.add_all([continuation, other])
        session.flush()
        continuation_id, other_id = continuation.id, other.id
    store = RunCheckpointStore(sessions, result["run_id"])
    store.claim(project["id"], continuation_id)
    with pytest.raises(SafetyViolation, match="Another continuation"):
        store.claim(project["id"], other_id)
    unrelated = RunCheckpointStore(sessions, other_id)
    unrelated.save({"next_stage": "ANSWER", "change_id": None})
    unrelated.claim(project["id"], "independent-run")


def test_repair_requires_a_new_edit_instead_of_counting_previous_files(client: TestClient) -> None:
    class StalledRepair(ScenarioProvider):
        async def respond(self, request, tools, turns=None):
            if request.role == "coder" and tools[0]["function"]["name"] == "submit_structured_result":
                self.files["app.py"] = APP
            elif request.role == "coder" and self.attempts and not turns:
                self.requests.append(request)
                return CompletionReply(content="The previous files are ready for validation.")
            return await super().respond(request, tools, turns)

    provider = StalledRepair({"app.py": APP.replace('return {"status": "ok"}', 'return MISSING_VALUE'), "test_app.py": APP_TEST})
    result = run(client, new_project(client), "Create a FastAPI health endpoint and test", provider)
    assert result["status"] == "proposed", result
    assert result["diagnostics"]["write_calls"] == 4  # initial two files plus forced concrete repair
    assert result["diagnostics"]["test_calls"] == 1


def test_redaction_preserves_injected_secret_parameters_and_json() -> None:
    import ast
    import json

    from app.agents.security_agent import SecurityAgent
    from app.security.redaction import redact_secrets

    source = 'def sign(payload: dict, secret: str) -> str:\n    return secret\n'
    assert redact_secrets(source) == source
    assert not SecurityAgent.inspect_source("auth.py", source)
    literal = 'api_key: str = "super-private-value"\n'
    hidden = redact_secrets(literal)
    assert "super-private-value" not in hidden
    ast.parse(hidden)
    assert json.loads(redact_secrets('{"password": "super-private-value"}')) == {"password": "[REDACTED]"}
    assert "super-private-value" not in redact_secrets("SECRET_KEY=super-private-value\n")


def test_empty_repair_submission_pauses_without_revalidating_old_files(client: TestClient) -> None:
    class EmptyRepair(ScenarioProvider):
        async def respond(self, request, tools, turns=None):
            if request.role == "coder" and tools[0]["function"]["name"] == "submit_structured_result":
                return CompletionReply(tool_calls=[ToolCall("empty", "submit_structured_result", {"summary": "No edits", "files": []})])
            if request.role == "coder" and self.attempts and not turns:
                return CompletionReply(content="Reuse the previous implementation.")
            return await super().respond(request, tools, turns)

    provider = EmptyRepair({"app.py": APP.replace('return {"status": "ok"}', 'return MISSING_VALUE'), "test_app.py": APP_TEST})
    result = run(client, new_project(client), "Create a FastAPI health endpoint and test", provider)
    assert result["status"] == "paused" and result["resumable"], result
    assert "No executable editing action" in result["answer"]
    assert result["diagnostics"]["execution_calls"] == 2 and result["diagnostics"]["write_calls"] == 2
    assert len(client.get(f"/changes/{result['change_id']}").json()["proposal"]["files"]) == 2
    assert client.get(f"/runs/{result['run_id']}/diagnostics").json()["checkpoint"]["stage"] == "IMPLEMENT"
