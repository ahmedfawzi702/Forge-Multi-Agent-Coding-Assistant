from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.schemas.domain import ContextChunk, ProjectMap


class ProviderError(RuntimeError):
    """Sanitized provider error, safe to return to the client."""

    def __init__(self, message: str, *, reason: str | None = None, retryable: bool | None = None,
                 retry_after_seconds: float | None = None, provider: str | None = None, model: str | None = None):
        super().__init__(message)
        lower = message.lower()
        throttled = any(word in lower for word in ("rate limit", "rate-limit", "rate_limit", "throttl", "quota temporarily", "429"))
        self.reason = reason or ("PROVIDER_RATE_LIMIT" if throttled else "PROVIDER_UNAVAILABLE" if any(word in lower for word in ("timed out", "unavailable", "interrupted", "cannot reach")) else "MODEL_OUTPUT_INCOMPLETE" if "preserved" in lower else "MODEL_OUTPUT_INVALID")
        self.retryable = retryable if retryable is not None else self.reason in {"PROVIDER_RATE_LIMIT", "PROVIDER_UNAVAILABLE", "MODEL_OUTPUT_INCOMPLETE", "TASK_INTERRUPTED", "TASK_TIME_LIMIT"}
        self.retry_after_seconds = retry_after_seconds if retry_after_seconds is not None else 60.0 if throttled else None
        self.retry_at = (datetime.now(UTC) + timedelta(seconds=self.retry_after_seconds)).isoformat() if self.retry_after_seconds is not None else None
        self.provider, self.model = provider, model
        self.partial_report: dict[str, Any] | None = None

    def metadata(self) -> dict[str, Any]:
        return {"pause_reason": self.reason, "retryable": self.retryable, "retry_after_seconds": self.retry_after_seconds,
            "retry_at": self.retry_at, "provider": self.provider, "model": self.model}


@dataclass(frozen=True)
class CompletionRequest:
    system: str
    message: str
    context: list[ContextChunk]
    project_map: ProjectMap
    level: str
    history: list[dict[str, str]] = field(default_factory=list)
    structured: bool = False
    auxiliary_context: str = ""
    role: str = "general"
    tool_choice: Literal["auto", "required", "none"] = "auto"


@dataclass(frozen=True)
class ProviderCapabilities:
    tool_calls: bool = False
    streaming: bool = False
    json_mode: bool = False


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def wire(self) -> dict[str, Any]:
        import json
        return {"id": self.id, "type": "function", "function": {"name": self.name, "arguments": json.dumps(self.arguments, ensure_ascii=False)}}


@dataclass(frozen=True)
class CompletionReply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = "unknown"
    model: str | None = None


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> str: ...

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    async def respond(self, request: CompletionRequest, tools: list[dict[str, Any]],
                      turns: list[dict[str, Any]] | None = None) -> CompletionReply:
        if tools or turns:
            raise ProviderError("This provider does not support native tool calls")
        return CompletionReply(content=await self.complete(request))
