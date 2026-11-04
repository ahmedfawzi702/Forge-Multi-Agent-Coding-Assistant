import httpx

from app.config import Settings
from app.llm.base import LLMProvider
from app.llm.providers.evidence import EvidenceProvider
from app.llm.providers.http import OllamaProvider, OpenAICompatibleProvider


def create_provider(settings: Settings, client: httpx.AsyncClient) -> LLMProvider:
    if settings.llm_provider == "ollama":
        return OllamaProvider(settings, client)
    if settings.llm_provider == "openai_compatible":
        return OpenAICompatibleProvider(settings, client)
    return EvidenceProvider()
