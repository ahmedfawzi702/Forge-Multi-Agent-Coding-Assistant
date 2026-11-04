from typing import Literal, Protocol

MemoryCategory = Literal["facts", "preferences", "conversation"]


class MemoryStore(Protocol):
    """Separate provenance-backed facts, user preferences and conversation context."""

    def get(self, project_id: str, category: MemoryCategory, key: str) -> dict[str, object] | None: ...
