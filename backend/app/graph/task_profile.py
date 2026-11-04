import re
from dataclasses import dataclass
from typing import Any

from app.schemas.domain import ProjectMap


@dataclass(frozen=True)
class TaskProfile:
    complexity: str
    targets: list[str]
    empty_workspace: bool
    standalone_create: bool

    @classmethod
    def classify(cls, message: str, project: ProjectMap) -> "TaskProfile":
        targets = list(dict.fromkeys(re.findall(r"(?<![\w/])([\w./-]+\.(?:py|tsx?|jsx?|md|json|txt))\b", message)))
        lower = message.lower()
        standalone = bool(len(targets) == 1 and re.search(r"\b(?:create|write|add)\b", lower)
            and re.search(r"\bprint(?:s)?\b", lower) and not re.search(r"\b(?:api|fastapi|auth|endpoint|database|framework|tests?|multiple)\b", lower)
            and targets[0] not in {file.path for file in project.files})
        complexity = ("TRIVIAL" if standalone else "LARGE" if re.search(r"\b(?:jwt|oauth|authentication|entire project)\b", lower)
            else "MEDIUM" if re.search(r"\b(?:fastapi|sqlalchemy|multiple files|database|project structure)\b", lower) else "SMALL")
        return cls(complexity, targets, not project.files, standalone)

    def context_result(self, files: list[str]) -> dict[str, Any]:
        sufficient = self.empty_workspace or self.standalone_create or bool(files)
        return {"sufficient": sufficient, "relevant_files": files,
            "missing_information": [] if sufficient else ["Locate the task's implementation and tests"],
            "reason": "Empty workspace: implement immediately" if self.empty_workspace else "Task-local source supplied" if sufficient else "Limited additional inspection allowed",
            "complexity": self.complexity}
