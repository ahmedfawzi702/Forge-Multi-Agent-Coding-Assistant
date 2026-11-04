"""Run-local diagnostics and last-resort safety limits, independent of stage budgets."""
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.llm.base import CompletionReply, CompletionRequest, LLMProvider, ProviderCapabilities


class RuntimeStopped(RuntimeError):
    def __init__(self, message: str, reason: str | None = None):
        super().__init__(message)
        self.reason = reason or ("GLOBAL_AGENT_STEP_LIMIT" if "step limit" in message.lower() else "TOOL_CALL_BUDGET")


@dataclass
class RunRuntime:
    settings: Settings
    run_id: str | None = None
    total_steps: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    tool_requests: int = 0
    read_calls: int = 0
    search_calls: int = 0
    write_calls: int = 0
    execution_calls: int = 0
    test_calls: int = 0
    retry_count: int = 0
    cache_hits: int = 0
    blocked_calls: int = 0
    repeated_calls: int = 0
    agent_name: str = "orchestrator"
    current_stage: str = "UNDERSTAND"
    last_tool: str | None = None
    complexity: str = "SMALL"
    stage_history: list[str] = field(default_factory=list)
    stage_states: dict[str, str] = field(default_factory=dict)
    stage_tool_calls: dict[str, int] = field(default_factory=dict)
    stage_budget_used: dict[str, int] = field(default_factory=dict)
    budget_events: list[str] = field(default_factory=list)
    provider_events: list[dict[str, Any]] = field(default_factory=list)

    def step(self) -> None:
        if self.total_steps >= self.settings.forge_max_agent_steps:
            raise RuntimeStopped("Global agent step limit reached")
        self.total_steps += 1

    def transition(self, stage: str, agent: str) -> None:
        self.step()
        if self.current_stage != stage:
            self.stage_budget_used[stage] = 0
        self.current_stage, self.agent_name = stage, agent
        if not self.stage_history or self.stage_history[-1] != stage:
            self.stage_history.append(stage)

    def tool(self, name: str, category: str) -> None:
        self.step()
        if self.tool_calls >= self.settings.forge_max_tool_calls:
            raise RuntimeStopped("Global tool operation limit reached")
        bucket = self.current_stage
        limit = {"IMPLEMENT": self.settings.forge_max_implementation_calls, "VALIDATE": self.settings.forge_max_validation_calls,
            "SECURITY": self.settings.forge_max_validation_calls, "TEST": self.settings.forge_max_test_calls,
            "REVIEW": self.settings.forge_max_review_calls}.get(bucket)
        if limit is not None and self.stage_budget_used.get(bucket, 0) >= limit:
            raise RuntimeStopped(f"{bucket} tool budget reached", "TOOL_CALL_BUDGET")
        self.stage_tool_calls[bucket] = self.stage_tool_calls.get(bucket, 0) + 1
        self.stage_budget_used[bucket] = self.stage_budget_used.get(bucket, 0) + 1
        self.tool_calls += 1
        self.last_tool = name
        if category == "search":
            self.search_calls += 1
        elif category == "read":
            self.read_calls += 1
        elif category == "write":
            self.write_calls += 1
        elif category == "test":
            self.test_calls += 1
            self.execution_calls += 1
        elif category == "execute":
            self.execution_calls += 1

    def diagnostics(self) -> dict[str, Any]:
        result = {key: value for key, value in self.__dict__.items() if key != "settings"}
        result["limits"] = {key: value for key, value in self.settings.model_dump().items() if key.startswith("forge_")}
        return result

    def stopped_message(self, reason: str, changes: int) -> str:
        return (f"Agent execution paused after {self.tool_calls} tool operations and {self.llm_calls} model calls. "
            f"Stage: {self.current_stage}. Staged file changes: {changes}. Cause: {reason}. "
            "The task checkpoint is preserved. Resume to continue from this stage.")


current_runtime: ContextVar[RunRuntime | None] = ContextVar("forge_runtime", default=None)


class MeasuredProvider(LLMProvider):
    def __init__(self, delegate: LLMProvider, runtime: RunRuntime):
        self.delegate, self.runtime, self.name = delegate, runtime, delegate.name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self.delegate.capabilities

    def call(self, role: str) -> None:
        if self.runtime.llm_calls >= self.runtime.settings.forge_max_model_calls:
            raise RuntimeStopped("Model call limit reached", "MODEL_CALL_LIMIT")
        self.runtime.step()
        self.runtime.llm_calls += 1
        self.runtime.agent_name = role

    async def complete(self, request: CompletionRequest) -> str:
        self.call(request.role)
        return await self.delegate.complete(request)

    async def respond(self, request: CompletionRequest, tools: list[dict[str, Any]], turns: list[dict[str, Any]] | None = None) -> CompletionReply:
        self.call(request.role)
        return await self.delegate.respond(request, tools, turns)
