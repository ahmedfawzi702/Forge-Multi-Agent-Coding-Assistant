from pathlib import Path
from typing import Protocol

from app.schemas.domain import ProjectMap


class ProjectIndexer(Protocol):
    """Adapter for a later incremental, semantic index."""

    async def index(self, project_id: str, root: Path) -> ProjectMap: ...
