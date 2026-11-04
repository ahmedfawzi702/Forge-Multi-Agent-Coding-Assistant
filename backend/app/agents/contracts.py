from abc import ABC, abstractmethod
from typing import Any


class FutureAgent(ABC):
    """Extension contract for optional agents outside the implemented core workflow."""

    @abstractmethod
    async def run(self, context_refs: list[str]) -> dict[str, Any]: ...
