"""Real staging, approval and version checks with scripted provider responses."""
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.execution.file_io import text_hash
from app.llm.base import (
    CompletionReply,
    CompletionRequest,
    LLMProvider,
    ProviderCapabilities,
    ToolCall,
)
from app.schemas.domain import SelectedCode
from app.schemas.engineering import ImplementationProposal
from app.services.direct_edits import direct_proposal
from app.services.selection import selection_bounds, verify_selection


class EditProvider(LLMProvider):
    name = "edit_contract_test"

    def __init__(self, actions: list[ToolCall] | None = None, recovery: dict[str, Any] | None = None):
        self.actions = actions
        self.recovery = recovery
        self.code_calls = 0
        self.recovery_calls = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tool_calls=True)

    async def complete(self, request: CompletionRequest) -> str:
        raise AssertionError("The native action contract must be used")

    async def respond(self, request: CompletionRequest, tools: list[dict[str, Any]], turns: list[dict[str, Any]] | None = None) -> CompletionReply:
        if request.role in {"security", "reviewer"}:
            return CompletionReply(tool_calls=[ToolCall("review", "submit_structured_result", {"approved": True, "score": 9, "critical_issues": [], "warnings": [], "suggestions": []})])
        self.code_calls += 1
        if tools[0]["function"]["name"] == "submit_structured_result":
            self.recovery_calls += 1
            if self.recovery is not None:
                return CompletionReply(tool_calls=[ToolCall("recover", "submit_structured_result", self.recovery)])
            return CompletionReply(content='{"summary":"I wrote the code"}')
        if not self.actions:
            return CompletionReply(content="I can implement that file.")
        if not turns:
            return CompletionReply(tool_calls=self.actions)
        return CompletionReply(tool_calls=[ToolCall("done", "complete_implementation", {"summary": "Prepared requested changes", "pending_steps": []})])


def workspace(client: TestClient) -> dict[str, Any]:
    return client.post("/projects/new", json={"name": "Edit acceptance", "template": "empty"}).json()  # type: ignore[no-any-return]


def test_prose_recovers_once_into_real_file_then_approval_and_history(client: TestClient) -> None:
    provider = EditProvider(recovery={"summary": "Hello implementation", "files": [{"path": "hello.py", "content": 'print("Hello World")\n', "reason": "Requested greeting"}]})
    client.app.state.chat.provider = provider
    project = workspace(client)
    result = client.post("/chat", json={"project_id": project["id"], "message": "Create hello.py and make it print Hello World"}).json()
    assert result["status"] == "proposed", result
    assert provider.code_calls == 2 and provider.recovery_calls == 1
    assert not (Path(project["path"]) / "hello.py").exists()
    change = client.get(f"/changes/{result['change_id']}").json()
    assert change["proposal"]["files"][0]["after"] == 'print("Hello World")\n'
    assert change["can_apply"]
    assert client.post(f"/changes/{result['change_id']}/apply", json={}).status_code == 200
    assert (Path(project["path"]) / "hello.py").read_text() == 'print("Hello World")\n'
    assert any(f["path"] == "hello.py" for f in client.get(f"/projects/{project['id']}/tree").json())
    checkpoints = client.get(f"/projects/{project['id']}/checkpoints").json()
    detail = client.get(f"/projects/{project['id']}/checkpoints/{checkpoints[0]['id']}").json()
    assert detail["metadata"]["task_id"] == result["run_id"]
    assert detail["metadata"]["conversation_id"] == result["conversation_id"]
    assert detail["files"][0]["after_hash"] == text_hash('print("Hello World")\n')
    assert "+print" in detail["files"][0]["diff"]


@pytest.mark.parametrize("recovery", [None, {"summary": "Nothing", "files": []}, {"summary": "Wrong contract", "action": "create_file", "path": "hello.py", "content": "pass\n"}])
def test_invalid_action_stops_after_one_recovery_without_fabricated_edits(client: TestClient, recovery: dict[str, Any] | None) -> None:
    provider = EditProvider(recovery=recovery)
    client.app.state.chat.provider = provider
    project = workspace(client)
    result = client.post("/chat", json={"project_id": project["id"], "message": "Create calculator.py with arithmetic"}).json()
    assert provider.code_calls == 2 and provider.recovery_calls == 1
    assert result["task_status"] == "PAUSED", result
    assert result["pause_reason"] == "MODEL_OUTPUT_INCOMPLETE"
    assert result["staged_changes"]["files"] == 0
    assert result["tests"]["status"] == "NOT_RUN"
    assert not list(Path(project["path"]).iterdir())


@pytest.mark.parametrize("message,expected", [("Create an empty file named hello.py", ""), ('Create hello.py with this code:\n```python\nprint("Hello World")\n```', 'print("Hello World")\n')])
def test_exact_user_content_bypasses_coder_model(client: TestClient, message: str, expected: str) -> None:
    provider = EditProvider()
    client.app.state.chat.provider = provider
    project = workspace(client)
    result = client.post("/chat", json={"project_id": project["id"], "message": message}).json()
    assert result["change_id"], result
    assert provider.code_calls == 0
    change = client.get(f"/changes/{result['change_id']}").json()
    assert change["proposal"]["files"][0]["after"] == expected
    assert not list(Path(project["path"]).iterdir())
    assert client.post(f"/changes/{result['change_id']}/apply", json={}).status_code == 200
    assert (Path(project["path"]) / "hello.py").read_text() == expected


def test_selected_patch_preserves_other_functions_and_reject_protects_disk(client: TestClient) -> None:
    original = "def add(a, b):\n    return a + b\n\n\ndef divide(a, b):\n    return a / b\n"
    replacement = 'def divide(a, b):\n    if b == 0:\n        raise ValueError("Cannot divide by zero")\n    return a / b\n'
    provider = EditProvider(actions=[ToolCall("read", "read_file", {"path": "calculator.py"}), ToolCall("patch", "apply_patch", {"path": "calculator.py", "search": original[original.index("def divide"):], "replace": replacement, "reason": "Guard selected division"})])
    client.app.state.chat.provider = provider
    project = workspace(client)
    file = client.post(f"/projects/{project['id']}/files/write", json={"path": "calculator.py", "content": original}).json()
    result = client.post("/chat", json={"project_id": project["id"], "message": "Handle division by zero", "selected_code": {"file": "calculator.py", "start_line": 5, "end_line": 6, "base_hash": file["sha256"]}}).json()
    assert result["change_id"], result
    proposed = client.get(f"/changes/{result['change_id']}").json()["proposal"]["files"][0]
    assert proposed["after"] == original[:original.index("def divide")] + replacement
    assert client.post(f"/changes/{result['change_id']}/reject", json={}).status_code == 200
    assert (Path(project["path"]) / "calculator.py").read_text() == original


def test_stale_selection_and_later_manual_save_are_protected(client: TestClient) -> None:
    project = workspace(client)
    path = Path(project["path"]) / "hello.py"
    path.write_text("pass\n")
    client.app.state.chat.provider = EditProvider()
    result = client.post("/chat", json={"project_id": project["id"], "message": "Add error handling", "selected_code": {"file": "hello.py", "start_line": 1, "end_line": 1, "base_hash": text_hash("old\n")}}).json()
    assert not result.get("change_id")
    assert path.read_text() == "pass\n"


def test_selection_bounds_unicode_and_scope() -> None:
    source = 'const x = "😀";\nconst y = 2;\n'
    selection = SelectedCode(file="x.js", start_line=1, end_line=1, start_column=12, end_column=14, text="😀")
    bounds = selection_bounds(source, selection)
    verify_selection(source.replace("😀", "مرحبا"), bounds)
    with pytest.raises(Exception, match="outside the selected"):
        verify_selection(source.replace("y = 2", "y = 3"), bounds)


def test_direct_parser_does_not_guess_code_or_execute_embedded_instructions() -> None:
    assert direct_proposal("Create calculator.py with arithmetic and tests") is None
    assert direct_proposal("Explain how to create an empty file named hello.py") is None
    with pytest.raises(ValidationError):
        ImplementationProposal.model_validate({"summary": "just prose"})


def test_manual_change_blocks_agent_save_and_checkpoint_revert(client: TestClient) -> None:
    project = workspace(client)
    client.app.state.chat.provider = EditProvider(recovery={"summary": "Greeting", "files": [{"path": "hello.py", "content": 'print("Hello")\n', "reason": "Greeting"}]})
    result = client.post("/chat", json={"project_id": project["id"], "message": "Create hello.py and print Hello"}).json()
    path = Path(project["path"]) / "hello.py"
    path.write_text("# Later manual source\n")
    response = client.post(f"/changes/{result['change_id']}/apply", json={})
    assert response.status_code == 403
    assert path.read_text() == "# Later manual source\n"
    # An independent accepted proposal gets an undo entry, whose restore checks later edits.
    other = workspace(client)
    result = client.post("/chat", json={"project_id": other["id"], "message": "Create hello.py and print Hello"}).json()
    assert client.post(f"/changes/{result['change_id']}/apply", json={}).status_code == 200
    checkpoint = client.get(f"/projects/{other['id']}/checkpoints").json()[0]
    other_path = Path(other["path"]) / "hello.py"
    other_path.write_text("# Manual changes after save\n")
    response = client.post(f"/projects/{other['id']}/checkpoints/{checkpoint['id']}/restore")
    assert response.status_code == 403
    assert other_path.read_text() == "# Manual changes after save\n"


def test_empty_file_needs_no_model_or_executable_test(client: TestClient) -> None:
    project = workspace(client)
    result = client.post("/chat", json={"project_id": project["id"], "message": "Create an empty file named blank.py"}).json()
    assert result["status"] == "proposed", result
    assert result["diagnostics"]["llm_calls"] == 0
    assert result["tests"]["status"] == "NOT_APPLICABLE"
    assert "score" not in result["review"]
    assert client.post(f"/changes/{result['change_id']}/apply", json={}).status_code == 200
    assert (Path(project["path"]) / "blank.py").read_text() == ""
