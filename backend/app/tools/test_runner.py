from typing import Protocol

from app.execution.base import ExecutionResult


class TestRunner(Protocol):
    """Ecosystem adapter seam. No project test execution is enabled yet."""

    def detect(self, files: list[str]) -> bool: ...
    async def run(self) -> ExecutionResult: ...
