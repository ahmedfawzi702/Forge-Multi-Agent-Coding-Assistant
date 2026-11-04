"""Extension boundary for future browser/app verification; no browser is claimed today."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol


@dataclass(frozen=True)
class VerificationEvidence:
    status: Literal["passed", "failed", "unavailable"]
    summary: str
    command: list[str] = field(default_factory=list)
    exit_code: int | None = None
    screenshot_paths: list[Path] = field(default_factory=list)
    observed_url: str | None = None


class ApplicationVerifier(Protocol):
    """An opt-in adapter must supply observations, never a model's claim of success."""

    async def verify(self, workspace: Path, url: str) -> VerificationEvidence: ...
