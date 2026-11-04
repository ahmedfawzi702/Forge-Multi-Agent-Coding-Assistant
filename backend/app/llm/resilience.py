"""Configured-model selection and per-model cooldowns; no background retries."""
import copy
import hashlib
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.llm.base import (
    CompletionReply,
    CompletionRequest,
    LLMProvider,
    ProviderCapabilities,
    ProviderError,
)
from app.llm.providers.http import HTTPProvider
from app.security.policy import SafetyViolation


class ModelCooldowns:
    def __init__(self) -> None:
        self.entries: dict[tuple[str, str], dict[str, Any]] = {}

    def get(self, provider: str, model: str) -> dict[str, Any] | None:
        item = self.entries.get((provider, model))
        if item and item.get("retry_at") and datetime.fromisoformat(item["retry_at"]) > datetime.now(UTC):
            return item
        return None

    def note(self, provider: str, model: str, error: ProviderError) -> None:
        self.entries[(provider, model)] = error.metadata()


def configured_models(settings: Settings) -> list[str]:
    return list(dict.fromkeys(value for value in [settings.llm_model, *settings.llm_role_models.values(), *settings.llm_fallback_models] if value))


class RunProvider(LLMProvider):
    def __init__(self, delegate: LLMProvider, settings: Settings, cooldowns: ModelCooldowns,
                 selection: dict[str, Any] | None = None, override: str | None = None):
        self.delegate, self.settings, self.cooldowns, self.name = delegate, settings, cooldowns, delegate.name
        self.key = self.name + ":" + hashlib.sha256(settings.llm_base_url.encode()).hexdigest()[:16]
        self.selection = copy.deepcopy(selection or {"provider": self.name, "model": settings.llm_model, "role_models": settings.llm_role_models})
        if self.selection.get("provider_identity", self.key) != self.key:
            raise SafetyViolation("The configured provider endpoint changed. Restore the saved provider before resuming.")
        self.selection["provider_identity"] = self.key
        if self.selection.get("provider") != self.name:
            raise SafetyViolation("The saved provider is no longer configured. Restore it before resuming this task.")
        if override:
            if override not in configured_models(settings):
                raise SafetyViolation("Choose a model from the configured model list")
            self.selection.update(model=override, role_models={})
        if isinstance(delegate, HTTPProvider):
            required = [self.selection.get("model"), *self.selection.get("role_models", {}).values()]
            if any(model and model not in configured_models(settings) for model in required):
                raise SafetyViolation("The saved model is no longer configured. Choose a configured model to resume.")
        self.selection["automatic_fallback"] = settings.llm_fallback_enabled

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self.delegate.capabilities

    def model(self, role: str) -> str:
        return str(self.selection.get("role_models", {}).get(role, self.selection.get("model", "")))

    def selected(self, model: str) -> LLMProvider:
        if isinstance(self.delegate, HTTPProvider):
            return type(self.delegate)(self.delegate.settings.model_copy(update={"llm_model": model, "llm_role_models": {}}), self.delegate.client)
        return self.delegate

    async def invoke(self, request: CompletionRequest, tools: list[dict[str, Any]] | None = None,
                     turns: list[dict[str, Any]] | None = None) -> Any:
        from app.graph.runtime import RuntimeStopped, current_runtime
        model = self.model(request.role)
        for attempt in range(2):
            limited = self.cooldowns.get(self.key, model)
            self.selection.update(active_model=model, active_role=request.role)
            try:
                if limited:
                    runtime = current_runtime.get()
                    if runtime:
                        runtime.llm_calls = max(0, runtime.llm_calls - 1)
                    error = ProviderError("This model is cooling down after provider throttling. No provider request was sent.", reason="PROVIDER_RATE_LIMIT",
                        retry_after_seconds=max(0.0, (datetime.fromisoformat(limited["retry_at"]) - datetime.now(UTC)).total_seconds()), provider=self.name, model=model)
                    raise error
                provider = self.selected(model)
                return await provider.complete(request) if tools is None else await provider.respond(request, tools, turns)
            except ProviderError as error:
                error.provider, error.model = self.name, model
                if error.reason != "PROVIDER_RATE_LIMIT":
                    raise
                self.cooldowns.note(self.key, model, error)
                candidates = [item for item in self.settings.llm_fallback_models if item != model and not self.cooldowns.get(self.key, item)]
                if not self.settings.llm_fallback_enabled or attempt or not candidates:
                    raise
                previous, model = model, candidates[0]
                self.selection.setdefault("role_models", {})[request.role] = model
                runtime = current_runtime.get()
                if runtime:
                    if runtime.llm_calls >= self.settings.forge_max_model_calls:
                        raise RuntimeStopped("Model call limit reached", "MODEL_CALL_LIMIT") from error
                    runtime.step()
                    runtime.llm_calls += 1
                    runtime.retry_count += 1
                    runtime.provider_events.append({"type": "configured_fallback", "provider": self.name, "from_model": previous, "model": model, "role": request.role})
        raise AssertionError("Unreachable provider selection state")

    async def complete(self, request: CompletionRequest) -> str:
        return str(await self.invoke(request))

    async def respond(self, request: CompletionRequest, tools: list[dict[str, Any]], turns: list[dict[str, Any]] | None = None) -> CompletionReply:
        result: CompletionReply = await self.invoke(request, tools, turns)
        return result
