from pathlib import Path

import pytest

from app.agents.orchestrator import Orchestrator
from app.code_intelligence.repository_scanner import ProjectScanner
from app.config import Settings
from app.graph.workflow import workflow_events
from app.llm.base import CompletionRequest, LLMProvider
from app.schemas.domain import ChatMode, ChatRequest, Intent
from app.security.policy import SafetyViolation
from app.services.changes import proposed_diff


@pytest.mark.parametrize(("message", "mode", "expected"), [
    ("Explain greet", "ask", Intent.EXPLAIN), ("Add JWT authentication", "agent", Intent.CODE),
    ("Fix this bug", "ask", Intent.DEBUG), ("Write tests for service", "agent", Intent.CODE),
    ("Review my code", "review", Intent.REVIEW), ("Check security problems", "agent", Intent.SECURITY_REVIEW),
    ("Refactor greet", "agent", Intent.REFACTOR), ("What is a symbol?", "ask", Intent.ASK),
    ("Why does this fail?", "explain", Intent.EXPLAIN),
])
def test_routing(message: str, mode: ChatMode, expected: Intent) -> None:
    assert Orchestrator().classify(message, mode) == expected


class RecordingProvider(LLMProvider):
    name = "test"

    def __init__(self) -> None:
        self.calls: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> str:
        self.calls.append(request)
        return "Explanation with source evidence."


async def test_explanation_only_runs_required_agents(project_dir: Path, settings: Settings) -> None:
    provider = RecordingProvider()
    events = [item async for item in workflow_events(
        ChatRequest(project_id="test", message="Explain greet", selected_files=["app/service.py"]),
        project_dir, ProjectScanner(settings).scan(project_dir), provider, settings, [])]
    assert [node for node, _ in events if node != "_status"] == ["orchestrator", "retrieve", "explainer"]
    assert len(provider.calls) == 1
    assert provider.calls[0].context
    assert next(values for node, values in events if node == "explainer")["status"] == "completed"


async def test_mutation_route_never_calls_model(project_dir: Path, settings: Settings) -> None:
    provider = RecordingProvider()
    events = [item async for item in workflow_events(ChatRequest(project_id="test", message="Delete all files", mode="agent"),
        project_dir, ProjectScanner(settings).scan(project_dir), provider, settings, [])]
    assert [node for node, _ in events if node != "_status"] == ["orchestrator", "blocked"]
    assert not provider.calls
    assert next(values for node, values in events if node == "blocked")["status"] == "blocked"


def test_proposed_diff_leaves_source_untouched(project_dir: Path) -> None:
    source = project_dir / "app" / "service.py"
    before = source.read_text()
    patch = proposed_diff("app/service.py", before, before.replace("Hello", "Welcome"))
    assert "--- a/app/service.py" in patch and "+    return f\"Welcome" in patch
    assert source.read_text() == before


def test_diff_handles_missing_trailing_newline_and_rejects_header_injection() -> None:
    patch = proposed_diff("app.py", "before", "after")
    assert "-before\n\\ No newline at end of file\n+after\n" in patch
    with pytest.raises(SafetyViolation):
        proposed_diff("app.py\n--- a/other.py", "before", "after")
