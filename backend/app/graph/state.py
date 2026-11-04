from typing import Any, Literal

from typing_extensions import TypedDict

from app.schemas.domain import Evidence, Intent


class AgentState(TypedDict):
    task: str
    project_id: str
    project_path: str
    user_message: str
    selected_files: list[str]
    intent: Intent
    intents: list[Intent]
    workflow: str
    retrieved_context: list[Evidence]
    plan: list[str]
    changes: list[str]
    test_results: list[str]
    security_results: list[str]
    review_results: list[str]
    attempt: int
    status: Literal["running", "paused", "cancelled", "completed", "unsupported", "failed", "partial", "proposed", "awaiting_approval", "blocked"]
    answer: str
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    artifact: dict[str, Any] | None
    change_id: str | None
