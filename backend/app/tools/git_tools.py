from typing import Protocol


class GitTools(Protocol):
    """Future read-only Git adapter; no implementation executes in Phase 1."""

    async def status(self) -> str: ...
    async def diff(self) -> str: ...
