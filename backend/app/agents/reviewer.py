from app.agents.structured import structured_completion
from app.llm.base import LLMProvider
from app.schemas.domain import ContextChunk, ProjectMap
from app.schemas.engineering import ReviewReport


class ReviewerAgent:
    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def review(self, task: str, context: list[ContextChunk], project_map: ProjectMap) -> ReviewReport:
        report = await structured_completion(self.provider, "reviewer.md", task, context, project_map, ReviewReport)
        if report.critical_issues:
            report.approved = False
        return report
