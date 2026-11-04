"""Lifecycle acceptance: real staging/validators with controlled provider faults."""
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from test_progress_runtime import APP, APP_TEST, ScenarioProvider, new_project, run

from app.config import Settings
from app.llm.base import CompletionReply, CompletionRequest, ProviderError, ToolCall
from app.llm.providers.http import OpenAICompatibleProvider
from app.models.entities import RunCheckpoint


class FoundationProvider(ScenarioProvider):
    def __init__(self, *, repeated_throttle: bool = False, retry_after: float = 0):
        super().__init__({"app.py": APP, "test_app.py": APP_TEST})
        self.repeated_throttle, self.retry_after = repeated_throttle, retry_after
        self.failed_continuations = 0

    async def respond(self, request: CompletionRequest, tools: list[dict[str, Any]], turns: list[dict[str, Any]] | None = None) -> CompletionReply:
        if request.role != "coder":
            return await super().respond(request, tools, turns)
        self.requests.append(request)
        continuing = "previous edits already exist" in request.message.lower()
        if not turns:
            if continuing:
                if self.repeated_throttle and not self.failed_continuations:
                    self.failed_continuations += 1
                    raise ProviderError("Provider throttling", reason="PROVIDER_RATE_LIMIT", retry_after_seconds=self.retry_after)
                assert "app.py" in request.message and "test_app.py" in request.message
                return CompletionReply(tool_calls=[ToolCall("remaining", "create_file", {"path": "README.md", "content": "# Health API\n", "reason": "Finish the missing documentation subtask"})])
            self.attempts += 1
            return CompletionReply(tool_calls=[
                *[ToolCall(f"file{i}", "create_file", {"path": path, "content": text, "reason": "Build the foundation"}) for i, (path, text) in enumerate(self.files.items())],
                *[ToolCall(f"dir{i}", "create_directory", {"path": f"module_{i}"}) for i in range(5)],
                ToolCall("checkpoint", "checkpoint_implementation", {"summary": "Foundation ready; README pending", "completed_steps": ["Project foundation"], "pending_steps": ["README"]}),
            ])
        if not continuing:
            raise ProviderError("Model provider rate limit", reason="PROVIDER_RATE_LIMIT", retry_after_seconds=self.retry_after)
        return CompletionReply(tool_calls=[ToolCall("complete", "complete_implementation", {"summary": "Foundation and missing documentation complete", "completed_steps": ["Project foundation", "README"], "pending_steps": []})])


def assert_incomplete_pause(client: TestClient, result: dict[str, Any]) -> dict[str, Any]:
    assert result["status"] == "paused" and result["task_status"] == "PAUSED", result
    assert result["stage"] == "IMPLEMENT" and not result["implementation_complete"]
    assert result["checkpoint_preserved"] and result["resumable"]
    assert result["staged_changes"]["files"] == 2 and result["staged_changes"]["directories"] == 5
    assert result["staged_changes"]["applied_files"] == 0
    for key in ("tests", "security", "review", "static_validation"):
        assert result[key]["status"] == "NOT_RUN", result[key]
        assert "score" not in result[key]
    for stage in ("VALIDATE", "SECURITY", "TEST", "REVIEW"):
        assert result["stage_states"][stage] == "NOT_STARTED"
    change = client.get(f"/changes/{result['change_id']}").json()
    assert not change["can_apply"]
    for key in ("static", "tests", "security", "review"):
        assert change["proposal"][key]["status"] == "not_run"
    return change


def test_seven_staged_entries_rate_limit_pause_resume_complete(client: TestClient) -> None:
    project = new_project(client)
    provider = FoundationProvider(repeated_throttle=True)
    initial = run(client, project, "Create a FastAPI health API foundation, five module directories and README with tests", provider)
    assert initial["pause_reason"] == "PROVIDER_RATE_LIMIT" and initial["retryable"]
    change = assert_incomplete_pause(client, initial)
    originals = {item["path"]: item["after"] for item in change["proposal"]["files"]}
    retry = client.post(f"/runs/{initial['run_id']}/resume", json={"allow_execution": True}).json()
    assert_incomplete_pause(client, retry)
    assert retry["diagnostics"]["tool_calls"] == 0 and retry["diagnostics"]["llm_calls"] == 1
    assert retry["change_id"] == initial["change_id"]
    assert retry["diagnostics"]["stage_history"] == ["IMPLEMENT"]
    with client.app.state.chat.sessions() as session:
        saved = session.get(RunCheckpoint, retry["run_id"]).payload
        assert saved["attempt"] == 1 and saved["completed_implementation_steps"] == ["Project foundation"]
        assert saved["pending_implementation_steps"] == ["README"] and saved["project_state_version"]
        assert saved["model_selection"]["provider"] == provider.name
    completed = client.post(f"/runs/{retry['run_id']}/resume", json={"allow_execution": True}).json()
    assert completed["task_status"] == "COMPLETED" and completed["status"] == "proposed", completed
    assert completed["implementation_complete"] and completed["diagnostics"]["write_calls"] == 1
    assert completed["tests"]["status"] == "PASSED" and completed["security"]["status"] == "PASSED"
    assert completed["review"]["status"] == "APPROVED"
    assert completed["diagnostics"]["stage_history"][0] == "IMPLEMENT"
    assert not any(stage in completed["diagnostics"]["stage_history"] for stage in ["UNDERSTAND", "CONTEXT", "PLAN"])
    final = client.get(f"/changes/{completed['change_id']}").json()
    assert final["can_apply"]
    assert all(next(item for item in final["proposal"]["files"] if item["path"] == path)["after"] == text for path, text in originals.items())
    assert not Path(project["path"], "app.py").exists()
    events = client.get(f"/runs/{retry['run_id']}").json()["events"]
    assert any(event["type"] == "task_paused" for event in events)
    assert not any(event["type"] in {"test_result", "security_result", "review_result", "task_failed", "task_completed"} for event in events)


def test_stage_tool_budget_pauses_then_refills_for_continuation(client: TestClient) -> None:
    service = client.app.state.chat
    service.settings = service.settings.model_copy(update={"forge_max_implementation_calls": 7})
    project = new_project(client)
    result = run(client, project, "Create a FastAPI health foundation with tests", FoundationProvider())
    assert_incomplete_pause(client, result)
    assert result["pause_reason"] == "TOOL_CALL_BUDGET" and result["diagnostics"]["tool_calls"] == 7
    service.settings = service.settings.model_copy(update={"forge_max_implementation_calls": 32})
    completed = client.post(f"/runs/{result['run_id']}/resume", json={"allow_execution": True}).json()
    assert completed["task_status"] == "COMPLETED" and completed["tests"]["status"] == "PASSED", completed


def test_actual_pytest_failure_is_failed_and_not_run_is_distinct(client: TestClient) -> None:
    client.app.state.chat.settings = client.app.state.chat.settings.model_copy(update={"forge_max_repair_attempts": 1})
    result = run(client, new_project(client), "Create a FastAPI health API with tests", ScenarioProvider({"app.py": APP, "test_app.py": APP_TEST.replace('"ok"', '"incorrect"')}))
    assert result["task_status"] == "BLOCKED" and result["implementation_complete"], result
    assert result["tests"]["status"] == "FAILED" and result["tests"]["exit_code"] == 1
    assert result["diagnostics"]["test_calls"] == 1 and result["pause_reason"] == "REPAIR_LIMIT"


def test_actual_security_finding_fails_security_but_does_not_fail_unexecuted_tests(client: TestClient) -> None:
    client.app.state.chat.settings = client.app.state.chat.settings.model_copy(update={"forge_max_repair_attempts": 1})
    result = run(client, new_project(client), "Create an API foundation with tests", ScenarioProvider({"app.py": APP + "\n\ndef unsafe(value):\n    return eval(value)\n", "test_app.py": APP_TEST}))
    assert result["implementation_complete"] and result["security"]["status"] == "FAILED", result
    assert any("dangerous call eval" in finding for finding in result["security"]["findings"])
    assert result["tests"]["status"] == "NOT_RUN" and result["diagnostics"]["test_calls"] == 0


def test_final_reviewer_rejection_has_real_score_only_after_completion(client: TestClient) -> None:
    class RejectingReviewer(ScenarioProvider):
        async def respond(self, request, tools, turns=None):
            if request.role == "reviewer":
                return CompletionReply(tool_calls=[ToolCall("review", "submit_structured_result", {"approved": False, "score": 2, "critical_issues": ["Verified fixture rejection"], "warnings": [], "suggestions": []})])
            return await super().respond(request, tools, turns)
    client.app.state.chat.settings = client.app.state.chat.settings.model_copy(update={"forge_max_repair_attempts": 1})
    result = run(client, new_project(client), "Create a FastAPI health API and tests", RejectingReviewer({"app.py": APP, "test_app.py": APP_TEST}))
    assert result["implementation_complete"] and result["tests"]["status"] == "PASSED", result
    assert result["review"]["status"] == "NOT_APPROVED" and result["review"]["score"] == 2
    assert result["review"]["kind"] == "FINAL_REVIEW"


@pytest.mark.parametrize("header", ["120", "Thu, 29 Oct 2099 14:00:00 GMT"])
async def test_http_429_preserves_retry_after_without_retries(settings: Settings, header: str) -> None:
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": header}, text="private-provider-body")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(settings.model_copy(update={"llm_model": "model-a", "llm_base_url": "http://provider/v1"}), client)
        with pytest.raises(ProviderError) as caught:
            await provider.complete(CompletionRequest(system="", message="hi", context=[], project_map=new_project_map(), level="beginner"))
    error = caught.value
    assert error.reason == "PROVIDER_RATE_LIMIT" and error.retryable and error.retry_after_seconds > 0
    assert error.retry_at and len(calls) == 1 and "private-provider-body" not in str(error)


def new_project_map():
    from app.schemas.domain import ProjectMap
    return ProjectMap(language=[], framework=[], entry_points=[], dependencies=[], files=[], important_directories=[],
        symbols=[], architecture_summary="Empty acceptance workspace", scanned_at="2026-10-29T00:00:00Z")


def test_retry_after_prevents_repeat_resume_and_cancel_is_terminal(client: TestClient) -> None:
    provider = FoundationProvider(retry_after=120)
    project = new_project(client)
    result = run(client, project, "Create an API foundation and tests", provider)
    calls = len(provider.requests)
    response = client.post(f"/runs/{result['run_id']}/resume", json={"allow_execution": True})
    assert response.status_code == 403 and "cooling down" in response.text and len(provider.requests) == calls
    assert result["retry_after_seconds"] == 120 and result["retry_at"]
    assert client.post(f"/runs/{result['run_id']}/cancel").json()["task_status"] == "CANCELLED"
    assert client.get(f"/runs/{result['run_id']}").json()["result"]["task_status"] == "CANCELLED"
    history = client.get(f"/projects/{project['id']}/conversations/{result['conversation_id']}").json()
    assert history[-1]["result"]["task_status"] == "CANCELLED"
    assert client.post(f"/runs/{result['run_id']}/resume", json={}).status_code == 403


@pytest.mark.parametrize("enabled", [False, True])
async def test_model_specific_cooldown_and_opt_in_failover(settings: Settings, enabled: bool) -> None:
    from app.llm.resilience import ModelCooldowns, RunProvider
    seen = []
    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        seen.append(model)
        return httpx.Response(429, headers={"Retry-After": "120"}) if model == "model-a" else httpx.Response(200, json={"choices": [{"message": {"content": "Grounded answer"}}]})
    settings = settings.model_copy(update={"llm_model": "model-a", "llm_base_url": "http://provider/v1", "llm_fallback_models": ["model-b"], "llm_fallback_enabled": enabled})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cooldowns = ModelCooldowns()
        provider = RunProvider(OpenAICompatibleProvider(settings, client), settings, cooldowns)
        request = CompletionRequest(system="", message="hello", context=[], project_map=new_project_map(), level="beginner")
        if enabled:
            assert await provider.complete(request) == "Grounded answer"
            assert seen == ["model-a", "model-b"] and provider.selection["role_models"]["general"] == "model-b"
        else:
            with pytest.raises(ProviderError):
                await provider.complete(request)
            assert seen == ["model-a"]
        assert cooldowns.get(provider.key, "model-a") and not cooldowns.get(provider.key, "model-b")


def test_legacy_paused_reports_are_not_presented_as_current_failures(client: TestClient) -> None:
    from app.models.entities import AgentRun, ChangeSet
    from app.schemas.lifecycle import LIFECYCLE_FIELDS
    result = run(client, new_project(client), "Create a health API foundation", FoundationProvider())
    with client.app.state.chat.sessions.begin() as session:
        record = session.get(AgentRun, result["run_id"])
        legacy = {key: value for key, value in record.result.items() if key not in LIFECYCLE_FIELDS}
        record.result = {**legacy, "status": "partial", "answer": "Agent paused due to model provider rate limit.\n\nTests: failed. Security: failed. Review: not approved (1/10)."}
        record.status = "partial"
        checkpoint = session.get(RunCheckpoint, result["run_id"])
        payload = checkpoint.payload
        old_proposal = {key: value for key, value in payload["engineering"].items() if key != "implementation_complete"}
        old_proposal.update(tests={"status": "failed"}, security={"status": "failed"}, review={"approved": False, "score": 1})
        checkpoint.payload = {**payload, "engineering": old_proposal}
        session.get(ChangeSet, result["change_id"]).proposal = old_proposal
    current = client.get(f"/runs/{result['run_id']}").json()
    assert current["status"] == "paused" and current["result"]["tests"]["status"] == "NOT_RUN"
    assert "score" not in current["result"]["review"] and "1/10" not in current["result"]["answer"]
    assert current["checkpoint"]["files"] == 2 and current["checkpoint"]["directories"] == 5
    change = client.get(f"/changes/{result['change_id']}").json()
    assert change["proposal"]["review"]["status"] == "not_run" and not change["can_apply"]
    with client.app.state.chat.sessions() as session:
        assert session.get(RunCheckpoint, result["run_id"]).payload["engineering"]["review"]["score"] == 1  # Historical evidence is retained.


def test_gate_methods_reject_incomplete_implementation(client: TestClient) -> None:
    result = run(client, new_project(client), "Create an API foundation", FoundationProvider())
    assert client.post(f"/changes/{result['change_id']}/validate", json={"allow_execution": True}).status_code == 403
    assert client.post(f"/changes/{result['change_id']}/apply", json={}).status_code == 403


async def test_explicit_model_switch_resumes_same_checkpoint_without_automatic_fallback(client: TestClient) -> None:
    seen = []
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body["model"])
        if body["model"] == "model-a":
            return httpx.Response(429, headers={"Retry-After": "120"})
        definitions = {tool["function"]["name"] for tool in body["tools"]}
        if "submit_structured_result" in definitions:
            calls = [("submit_structured_result", {"approved": True, "score": 9, "critical_issues": [], "warnings": [], "suggestions": []})]
        else:
            calls = [("create_file", {"path": "app.py", "content": APP, "reason": "Implement health API"}),
                ("create_file", {"path": "test_app.py", "content": APP_TEST, "reason": "Regression test"}),
                ("complete_implementation", {"summary": "Implementation complete", "pending_steps": []})]
        return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {"content": None,
            "tool_calls": [{"id": str(i), "type": "function", "function": {"name": name, "arguments": json.dumps(args)}} for i, (name, args) in enumerate(calls)]}}]})
    service = client.app.state.chat
    service.settings = service.settings.model_copy(update={"llm_model": "model-a", "llm_base_url": "http://provider/v1", "llm_fallback_models": ["model-b"], "llm_fallback_enabled": False})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as remote:
        provider = OpenAICompatibleProvider(service.settings, remote)
        result = run(client, new_project(client), "Create a FastAPI health API with one pytest test", provider)
        assert result["task_status"] == "PAUSED" and seen == ["model-a"]
        assert result["diagnostics"]["tool_calls"] == 0 and result["diagnostics"]["llm_calls"] == 1
        assert client.post(f"/runs/{result['run_id']}/resume", json={"model": "unconfigured-model"}).status_code == 403
        available = client.get("/models").json()
        assert not available["automatic_fallback"] and available["models"][0]["status"] == "rate_limited"
        resumed = client.post(f"/runs/{result['run_id']}/resume", json={"model": "model-b", "allow_execution": True}).json()
        assert resumed["task_status"] == "COMPLETED" and resumed["tests"]["status"] == "PASSED", resumed
        assert seen == ["model-a", "model-b", "model-b", "model-b"]
        assert resumed["model_selection"]["model"] == "model-b" and not resumed["model_selection"]["automatic_fallback"]


def test_partial_security_scan_is_not_a_failed_final_security_review(client: TestClient) -> None:
    class InterruptedSecurity(ScenarioProvider):
        async def respond(self, request, tools, turns=None):
            if request.role == "security":
                raise ProviderError("Security model throttled", reason="PROVIDER_RATE_LIMIT", retry_after_seconds=0)
            return await super().respond(request, tools, turns)
    result = run(client, new_project(client), "Create a FastAPI health API and test", InterruptedSecurity({"app.py": APP, "test_app.py": APP_TEST}))
    assert result["task_status"] == "PAUSED" and result["stage"] == "SECURITY" and result["implementation_complete"]
    assert result["security"]["status"] == "PARTIAL" and result["security"]["final_review"]["status"] == "not_run"
    assert result["tests"]["status"] == "NOT_RUN" and result["review"]["status"] == "NOT_RUN"
    assert result["diagnostics"]["test_calls"] == 0 and "score" not in result["review"]


def test_backend_restart_restores_pending_task_as_paused(client: TestClient, settings: Settings, monkeypatch) -> None:
    from app.main import create_app
    from app.models.entities import AgentRun
    result = run(client, new_project(client), "Create an API foundation with tests", FoundationProvider())
    with client.app.state.chat.sessions.begin() as session:
        record = session.get(AgentRun, result["run_id"])
        record.status, record.result = "running", None
    monkeypatch.setattr("app.main.create_provider", lambda settings, client: FoundationProvider())
    with TestClient(create_app(settings)) as restarted:
        recovered = restarted.get(f"/runs/{result['run_id']}").json()
        assert recovered["status"] == "paused" and recovered["result"]["pause_reason"] == "TASK_INTERRUPTED"
        assert recovered["result"]["staged_changes"]["files"] == 2 and recovered["result"]["tests"]["status"] == "NOT_RUN"
        completed = restarted.post(f"/runs/{result['run_id']}/resume", json={"allow_execution": True}).json()
        assert completed["task_status"] == "COMPLETED" and completed["tests"]["status"] == "PASSED", completed


async def test_cooldown_is_restored_after_service_restart(client: TestClient) -> None:
    from app.services.chat import ChatService
    seen = []
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})
    service = client.app.state.chat
    service.settings = service.settings.model_copy(update={"llm_model": "model-a", "llm_base_url": "http://provider/v1"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as remote:
        provider = OpenAICompatibleProvider(service.settings, remote)
        result = run(client, new_project(client), "Create a FastAPI app", provider)
        assert result["pause_reason"] == "PROVIDER_RATE_LIMIT" and len(seen) == 1
        restored = ChatService(service.settings, service.sessions, service.projects, provider)
        from app.llm.resilience import RunProvider
        selected = RunProvider(provider, service.settings, restored.cooldowns)
        assert restored.cooldowns.get(selected.key, "model-a")
        with pytest.raises(ProviderError):
            await selected.complete(CompletionRequest(system="", message="hello", context=[], project_map=new_project_map(), level="beginner"))
        assert len(seen) == 1


def test_stage_allowance_refills_without_resetting_global_counters(settings: Settings) -> None:
    from app.graph.runtime import RunRuntime, RuntimeStopped
    runtime = RunRuntime(settings.model_copy(update={"forge_max_implementation_calls": 2}))
    runtime.transition("IMPLEMENT", "coder")
    runtime.tool("create_file", "write")
    runtime.tool("create_file", "write")
    with pytest.raises(RuntimeStopped, match="IMPLEMENT tool budget"):
        runtime.tool("create_file", "write")
    runtime.transition("VALIDATE", "validator")
    runtime.transition("IMPLEMENT", "coder")
    runtime.tool("apply_patch", "write")
    assert runtime.tool_calls == 3 and runtime.stage_tool_calls["IMPLEMENT"] == 3
    assert runtime.stage_budget_used["IMPLEMENT"] == 1
