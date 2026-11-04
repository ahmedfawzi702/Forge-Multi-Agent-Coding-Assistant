"""Real filesystem/process validation with deterministic model fault injection."""
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.code_intelligence.repository_scanner import ProjectScanner
from app.config import Settings
from app.llm.base import (
    CompletionReply,
    CompletionRequest,
    LLMProvider,
    ProviderCapabilities,
    ToolCall,
)
from app.llm.providers.http import OllamaProvider, OpenAICompatibleProvider
from app.schemas.domain import ChatRequest, ProjectView
from app.security.policy import SafetyViolation
from app.services.preferences import (
    CapabilityRequired,
    PermissionPolicy,
    Preferences,
    PreferenceStore,
)
from app.services.proposals import stage_proposal
from app.services.rules import RulesLoader
from app.services.run_control import RunControl, SteeringUpdate
from app.tools.registry import ToolRegistry

IMPLEMENTATION = '''import argparse


def calculate(left, operator, right):
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    if operator == "/":
        return left / right
    raise ValueError("Unknown operator")


def main():
    parser = argparse.ArgumentParser(description="Calculator")
    parser.add_argument("left", type=float)
    parser.add_argument("operator", choices=["+", "-", "*", "/"])
    parser.add_argument("right", type=float)
    args = parser.parse_args()
    try:
        print(calculate(args.left, args.operator, args.right))
    except ZeroDivisionError:
        parser.error("Cannot divide by zero")


if __name__ == "__main__":
    main()
'''
TESTS = '''import pytest
from calculator import calculate


@pytest.mark.parametrize("left,operator,right,expected", [(2,"+",3,5), (9,"-",2,7), (3,"*",4,12), (8,"/",2,4)])
def test_operations(left, operator, right, expected):
    assert calculate(left, operator, right) == expected


def test_zero_division():
    with pytest.raises(ZeroDivisionError):
        calculate(1, "/", 0)
'''


class NativeEngineer(LLMProvider):
    name = "scripted_native_verification"

    def __init__(self, broken_first: bool = False):
        self.attempts = 0
        self.broken_first = broken_first
        self.requests: list[CompletionRequest] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tool_calls=True)

    async def complete(self, request: CompletionRequest) -> str:
        self.requests.append(request)
        return json.dumps({"approved": True, "score": 9, "critical_issues": [], "warnings": [], "suggestions": []})

    async def respond(self, request: CompletionRequest, tools: list[dict[str, Any]], turns: list[dict[str, Any]] | None = None) -> CompletionReply:
        self.requests.append(request)
        if request.role in {"security", "reviewer"}:
            return CompletionReply(tool_calls=[ToolCall("report", "submit_structured_result", {"approved": True, "score": 9, "critical_issues": [], "warnings": [], "suggestions": []})])
        round_index = sum(turn["role"] == "assistant" for turn in turns or [])
        if not turns:
            self.attempts += 1
        if round_index == 0:
            calls = [ToolCall("tree", "get_tree", {}), ToolCall("rules", "load_rules", {})]
            if self.attempts > 1:
                calls += [ToolCall("read_source", "read_file", {"path": "calculator.py"}), ToolCall("read_tests", "read_file", {"path": "test_calculator.py"})]
        elif round_index == 1:
            source = IMPLEMENTATION.replace("return left + right", "return left - right") if self.broken_first and self.attempts == 1 else IMPLEMENTATION
            edit = "create_file" if self.attempts == 1 else "write_file"
            calls = [ToolCall("source", edit, {"path": "calculator.py", "content": source, "reason": "Implement the CLI"}),
                ToolCall("tests", edit, {"path": "test_calculator.py", "content": TESTS, "reason": "Cover operations and zero division"}),
                ToolCall("folder", "create_directory", {"path": "examples"})]
        elif round_index == 2:
            calls = [ToolCall("pytest", "run_command", {"argv": ["python", "-m", "pytest", "-q"]})]
        else:
            return CompletionReply(tool_calls=[ToolCall("done", "complete_implementation", {"summary": "Implemented calculator CLI and regression tests", "pending_steps": []})])
        return CompletionReply(tool_calls=calls, finish_reason="tool_calls", usage={"total_tokens": 10})


@pytest.mark.parametrize("broken", [False, True])
def test_empty_project_native_build_test_repair_review_apply_restore(client: TestClient, broken: bool) -> None:
    provider = NativeEngineer(broken)
    client.app.state.chat.provider = provider
    project = client.post("/projects/new", json={"name": "Calculator", "template": "empty"}).json()
    root = Path(project["path"])
    assert not list(root.iterdir())
    result = client.post("/chat", json={"project_id": project["id"], "message": "Build a Python calculator CLI with tests", "allow_execution": True}).json()
    assert result["status"] == "proposed", result
    assert provider.attempts == (2 if broken else 1)
    assert not list(root.iterdir()), "Only staged source may change before Apply"
    change = client.get(f"/changes/{result['change_id']}").json()
    assert change["can_apply"]
    assert change["proposal"]["tests"]["exit_code"] == 0
    assert "5 passed" in change["proposal"]["tests"]["stdout"]
    applied = client.post(f"/changes/{result['change_id']}/apply", json={})
    assert applied.status_code == 200, applied.text
    assert (root / "calculator.py").read_text() == IMPLEMENTATION
    assert (root / "examples").is_dir()
    checkpoint = client.get(f"/projects/{project['id']}/checkpoints").json()[0]
    restore = client.post(f"/projects/{project['id']}/checkpoints/{checkpoint['id']}/restore")
    assert restore.status_code == 200, restore.text
    assert not (root / "calculator.py").exists()


async def test_tools_enforce_roles_inspection_ignore_and_permissions(client: TestClient, settings: Settings, project_dir: Path) -> None:
    project = ProjectView.model_validate(client.post("/projects/open", json={"path": str(project_dir)}).json())
    policy = PermissionPolicy(settings, ChatRequest(project_id=project.id, message="Build"))
    readonly = ToolRegistry(project, settings, policy, [])
    assert (await readonly.execute("write_file", {"path": "x.py", "content": "", "reason": "x"}))["status"] == "blocked"
    coder = ToolRegistry(project, settings, policy, [], role="coder")
    assert (await coder.execute("write_file", {"path": "app/service.py", "content": "bad", "reason": "x"}))["status"] == "blocked"
    await coder.execute("read_range", {"path": "app/service.py", "start_line": 3, "end_line": 3})
    patched = await coder.execute("apply_patch", {"path": "app/service.py", "search": 'return f"Hello {name}"', "replace": 'return f"Welcome {name}"', "reason": "Update greeting"})
    assert patched["status"] == "staged"
    stage, patches, _ = stage_proposal(project, coder.proposal("Greeting"), coder.context, settings)
    assert "Welcome" in (stage / "app/service.py").read_text()
    assert "Hello" in (project_dir / "app/service.py").read_text()
    assert len(patches) == 1
    with pytest.raises(CapabilityRequired):
        await coder.execute("run_command", {"argv": ["python", "-m", "pytest"]})
    (project_dir / ".forgeignore").write_text("app/service.py\n")
    blocked = ToolRegistry(project, settings, policy, [], role="coder")
    assert (await blocked.execute("read_file", {"path": "app/service.py"}))["status"] == "blocked"
    assert (await blocked.execute("read_file", {"path": "../outside.py"}))["status"] == "blocked"
    assert (await blocked.execute("read_file", {"path": ".env"}))["status"] == "blocked"


def test_project_rules_preferences_and_denial_are_real(client: TestClient, project_dir: Path, settings: Settings) -> None:
    (project_dir / "AGENTS.md").write_text("Use small functions.")
    (project_dir / "app/FORGE.md").write_text("Preserve public APIs.")
    rules = RulesLoader(project_dir).load(["app/service.py"])
    assert {item["file"] for item in rules} == {"AGENTS.md", "app/FORGE.md"}
    project = client.post("/projects/open", json={"path": str(project_dir)}).json()
    store = PreferenceStore(settings)
    store.save(Preferences(instructions="Global rule", explanation_level="beginner"))
    store.save(Preferences(instructions="Local rule", capabilities={"filesystem.read": "deny"}), project["id"])
    assert store.effective(project["id"]).explanation_level == "beginner"
    denied = client.post("/chat", json={"project_id": project["id"], "message": "Explain auth", "approvals": ["filesystem.read"]}).json()
    assert denied["status"] == "blocked"
    assert client.get(f"/projects/{project['id']}/file", params={"path": "app/service.py"}).status_code == 200
    ask = PermissionPolicy(settings, ChatRequest(project_id=project["id"], message="Build", mode="ask", allow_execution=True))
    with pytest.raises(SafetyViolation):
        ask.require("terminal.execute")


@pytest.mark.parametrize("ollama", [False, True])
async def test_native_provider_normalization_and_redaction(settings: Settings, project_dir: Path, ollama: bool) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["tools"][0]["function"]["name"] == "get_tree"
        assert "private-secret" not in request.content.decode()
        call = {"id": "tool_1", "type": "function", "function": {"name": "get_tree", "arguments": {} if ollama else "{}"}}
        message = {"content": "<think>private reasoning</think>", "tool_calls": [call]}
        return httpx.Response(200, json={"message": message, "done_reason": "stop"} if ollama else {"choices": [{"message": message, "finish_reason": "tool_calls"}], "usage": {"total_tokens": 12}})
    config = settings.model_copy(update={"llm_model": "test", "llm_base_url": "http://provider"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = OllamaProvider(config, client) if ollama else OpenAICompatibleProvider(config, client)
        reply = await provider.respond(CompletionRequest(system="Test", message="Inspect", context=[],
            project_map=ProjectScanner(settings).scan(project_dir), level="advanced", auxiliary_context='password = "private-secret"'),
            [{"type": "function", "function": {"name": "get_tree", "parameters": {"type": "object"}}}])
    assert not reply.content
    assert reply.tool_calls[0].arguments == {}


def test_steering_is_consumed_only_at_boundaries() -> None:
    control = RunControl("project")
    control.steer("Do not change the database")
    with pytest.raises(SteeringUpdate) as caught:
        control.boundary()
    assert caught.value.messages == ["Do not change the database"]
    control.boundary()
    control.stopped = True
    from app.services.run_control import RunInterrupted
    with pytest.raises(RunInterrupted):
        control.boundary()
