import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import Settings
from app.execution.file_io import atomic_write
from app.schemas.domain import ChatRequest
from app.security.policy import SafetyViolation

Decision = Literal["allow", "ask", "deny"]
DEFAULT_CAPABILITIES: dict[str, Decision] = {
    "filesystem.read": "allow", "filesystem.write": "allow", "terminal.execute": "ask",
    "git.read": "allow", "git.write": "ask", "network": "ask", "package.install": "ask", "subagent": "allow",
}


class Preferences(BaseModel):
    instructions: str = Field(default="", max_length=16001)
    explanation_level: Literal["beginner", "intermediate", "advanced"] | None = None
    capabilities: dict[str, Decision] = Field(default_factory=dict)


class PreferenceStore:
    def __init__(self, settings: Settings):
        self.root = settings.data_directory / "preferences"

    def path(self, project_id: str | None) -> Path:
        key = project_id or "global"
        if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", key):
            raise SafetyViolation("Invalid preference scope")
        return self.root / f"{key}.json"

    def load(self, project_id: str | None = None) -> Preferences:
        path = self.path(project_id)
        if not path.exists():
            return Preferences()
        if path.is_symlink() or path.stat().st_size > 131072:
            raise SafetyViolation("Invalid preference file")
        return Preferences.model_validate_json(path.read_text(encoding="utf-8"))

    def effective(self, project_id: str) -> Preferences:
        global_settings, local = self.load(), self.load(project_id)
        return Preferences(instructions="\n".join(filter(None, [global_settings.instructions, local.instructions])),
            explanation_level=local.explanation_level or global_settings.explanation_level or "intermediate",
            capabilities={**DEFAULT_CAPABILITIES, **global_settings.capabilities, **local.capabilities})

    def save(self, settings: Preferences, project_id: str | None = None) -> Preferences:
        if len(settings.instructions) > 8000:
            raise SafetyViolation("Each instruction scope is limited to 8000 characters")
        if set(settings.capabilities) - DEFAULT_CAPABILITIES.keys():
            raise SafetyViolation("Unknown agent capability")
        atomic_write(self.path(project_id), json.dumps(settings.model_dump()))
        return settings


class PermissionPolicy:
    def __init__(self, settings: Settings, request: ChatRequest):
        self.preferences = PreferenceStore(settings).effective(request.project_id)
        self.approvals = set(request.approvals)
        self.read_only = request.mode in {"ask", "plan"}
        if request.allow_execution:
            self.approvals.add("terminal.execute")

    def decision(self, capability: str) -> Decision:
        if self.read_only and capability in {"filesystem.write", "terminal.execute", "git.write", "package.install", "network"}:
            return "deny"
        decision = self.preferences.capabilities.get(capability, "deny")
        return "allow" if decision == "ask" and capability in self.approvals else decision

    def require(self, capability: str) -> None:
        decision = self.decision(capability)
        if decision != "allow":
            raise CapabilityRequired(capability, decision)


class CapabilityRequired(SafetyViolation):
    def __init__(self, capability: str, decision: str):
        self.capability, self.decision = capability, decision
        super().__init__(f"{capability}: {'permission is required' if decision == 'ask' else 'denied by the agent permission policy'}")

    def result(self) -> dict[str, Any]:
        return {"status": "awaiting_approval" if self.decision == "ask" else "blocked", "capability": self.capability, "message": str(self)}
