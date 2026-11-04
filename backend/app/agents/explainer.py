from pathlib import Path

from app.llm.base import CompletionRequest, LLMProvider
from app.schemas.domain import ContextChunk, ProjectMap


class ExplainerAgent:
    def __init__(self, provider: LLMProvider):
        self.provider = provider
        self.prompt = (Path(__file__).parents[1] / "prompts" / "explainer.md").read_text(encoding="utf-8")

    async def explain(self, message: str, level: str, project_map: ProjectMap,
                      context: list[ContextChunk], history: list[dict[str, str]]) -> str:
        return await self.provider.complete(CompletionRequest(
            system=self.prompt, message=message, level=level, project_map=project_map,
            context=context, history=history, role="explainer",
        ))
