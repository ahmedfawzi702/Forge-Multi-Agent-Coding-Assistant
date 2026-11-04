from pathlib import Path

import httpx
import pytest

from app.code_intelligence.repository_scanner import ProjectScanner
from app.config import Settings
from app.llm.base import CompletionRequest, ProviderError
from app.llm.providers.http import OllamaProvider, OpenAICompatibleProvider


@pytest.mark.parametrize("provider_name", ["ollama", "openai_compatible"])
async def test_provider_adapter_sends_context_and_extracts_answer(project_dir: Path, settings: Settings, provider_name: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert b"UNTRUSTED PROJECT DATA" in request.content
        assert b"hidden-password" not in request.content
        if provider_name == "ollama":
            assert request.url.path == "/api/chat"
            return httpx.Response(200, json={"message": {"content": "Grounded answer"}})
        assert request.headers["Authorization"] == "Bearer testing-only"
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": "Grounded answer"}}]})

    configured = settings.model_copy(update={"llm_model": "configured-model", "llm_api_key": "testing-only",
        "llm_base_url": "http://provider" + ("/v1" if provider_name == "openai_compatible" else "")})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OllamaProvider(configured, client) if provider_name == "ollama" else OpenAICompatibleProvider(configured, client)
        answer = await provider.complete(CompletionRequest(system="Explain safely", message='password = "hidden-password"',
            context=[], project_map=ProjectScanner(settings).scan(project_dir), level="beginner"))
    assert answer == "Grounded answer"


async def test_http_errors_do_not_expose_provider_body(project_dir: Path, settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="credential-sensitive-response")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OllamaProvider(settings.model_copy(update={"llm_model": "configured"}), client)
        with pytest.raises(ProviderError) as caught:
            await provider.complete(CompletionRequest(system="", message="Hi", context=[],
                project_map=ProjectScanner(settings).scan(project_dir), level="intermediate"))
        assert "credential-sensitive-response" not in str(caught.value)
