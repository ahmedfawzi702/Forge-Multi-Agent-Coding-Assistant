from app.agents.explainer import ExplainerAgent
from app.llm.base import LLMProvider
from app.schemas.domain import ContextChunk, ProjectMap


class CodebaseAnalyzer:
    async def analyze(self, provider: LLMProvider, task: str, context: list[ContextChunk],
                      project_map: ProjectMap, level: str) -> str:
        task += "\nExplain the architecture from inspected evidence. Cover entry points, stack, testing and database boundaries. Mark unverified relationships as inference."
        return await ExplainerAgent(provider).explain(task, level, project_map, context, [])
