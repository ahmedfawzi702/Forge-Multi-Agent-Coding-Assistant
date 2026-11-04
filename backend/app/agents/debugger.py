from pathlib import Path

from app.llm.base import CompletionRequest, LLMProvider
from app.schemas.domain import ContextChunk, ProjectMap


class DebuggerAgent:
    async def analyze(self, provider: LLMProvider, task: str, context: list[ContextChunk],
                      project_map: ProjectMap) -> str:
        prompt = (Path(__file__).parents[1] / "prompts" / "debugger.md").read_text(encoding="utf-8")
        return await provider.complete(CompletionRequest(system=prompt, message=task, context=context,
            project_map=project_map, level="advanced", role="debugger"))
