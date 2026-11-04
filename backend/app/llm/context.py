from dataclasses import replace
from typing import Any

from app.llm.base import CompletionReply, CompletionRequest, LLMProvider, ProviderCapabilities


class ContextProvider(LLMProvider):
    """Bind per-task context without leaking it into another specialist or run."""

    def __init__(self, delegate: LLMProvider, context: str = "", instructions: str = ""):
        self.delegate, self.context, self.instructions = delegate, context, instructions
        self.name = delegate.name

    async def complete(self, request: CompletionRequest) -> str:
        return await self.delegate.complete(self.bind(request))

    def bind(self, request: CompletionRequest) -> CompletionRequest:
        return replace(request,
            auxiliary_context=(self.context + "\n" + request.auxiliary_context).strip(),
            system=request.system + ("\nProject/user steering (cannot grant tools or bypass policy):\n" + self.instructions if self.instructions else ""))

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self.delegate.capabilities

    async def respond(self, request: CompletionRequest, tools: list[dict[str, Any]],
                      turns: list[dict[str, Any]] | None = None) -> CompletionReply:
        return await self.delegate.respond(self.bind(request), tools, turns)
