from app.agents.structured import structured_completion
from app.llm.base import LLMProvider
from app.schemas.domain import ContextChunk, ProjectMap
from app.schemas.engineering import CodeProposal, ImplementationProposal


class CoderAgent:
    """Proposes source content only; has no write or approval capability."""

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def propose(self, task: str, context: list[ContextChunk], project_map: ProjectMap) -> CodeProposal:
        return await structured_completion(self.provider, "coder.md", task, context, project_map, ImplementationProposal)
