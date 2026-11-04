from pathlib import Path

from app.llm.base import CompletionRequest, LLMProvider
from app.schemas.domain import ContextChunk, Intent, ProjectMap


class PlannerAgent:
    @staticmethod
    def steps(intents: list[Intent]) -> list[str]:
        steps = ["Inspect relevant source and dependencies"]
        if Intent.DEBUG in intents:
            steps.append("Rank root-cause hypotheses against source evidence")
        if any(i in intents for i in (Intent.CODE, Intent.EDIT, Intent.DEBUG, Intent.REFACTOR)):
            steps += ["Prepare the smallest patch and relevant regression tests", "Validate syntax and static diagnostics",
                      "Inspect security findings", "Run tests with explicit permission", "Independently review the patch",
                      "Present a ChangeSet for approval"]
        else:
            steps.append("Return an evidence-based result with remaining unknowns")
        return steps

    async def explain_plan(self, provider: LLMProvider, task: str,
                           context: list[ContextChunk], project_map: ProjectMap) -> str:
        prompt = (Path(__file__).parents[1] / "prompts" / "planner.md").read_text(encoding="utf-8")
        return await provider.complete(CompletionRequest(system=prompt, message=task, context=context,
            project_map=project_map, level="advanced", role="planner"))
