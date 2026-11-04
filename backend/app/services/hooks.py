"""Small, explicit local hooks. Project configuration never grants execution permission."""
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import Settings
from app.execution.commands import CommandRunner
from app.execution.file_io import atomic_write
from app.execution.local import LocalExecutionEnvironment
from app.schemas.domain import ProjectView
from app.security.command_guard import CommandGuard
from app.security.policy import SafetyViolation
from app.services.preferences import PermissionPolicy

HookEvent = Literal["AfterFileEdit", "BeforeToolExecution", "AfterToolExecution", "AfterAgentTask", "BeforeCommit"]


class Hook(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    event: HookEvent
    argv: list[str] = Field(min_length=1, max_length=60)
    timeout: int = Field(default=30, ge=1, le=120)


class HookConfig(BaseModel):
    hooks: list[Hook] = Field(default_factory=list, max_length=20)


class HookService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.data_directory / "hooks"

    def configuration(self, project: ProjectView) -> list[Hook]:
        source = LocalExecutionEnvironment(Path(project.path), 16384)
        try:
            text = source.read_file(".forge/hooks.json")
        except (FileNotFoundError, SafetyViolation):
            return []
        return HookConfig.model_validate_json(text).hooks

    def record_path(self, project: ProjectView, key: str) -> Path:
        return self.root / str(uuid.UUID(project.id)) / f"{uuid.UUID(key)}.json"

    def queue(self, project: ProjectView, event: HookEvent, workspace: Path | None = None) -> list[dict[str, Any]]:
        records = []
        for hook in self.configuration(project):
            if hook.event != event:
                continue
            key = str(uuid.uuid4())
            record = {"id": key, "project_id": project.id, "hook": hook.model_dump(), "status": "awaiting_approval",
                "workspace": str(workspace or Path(project.path)), "created_at": datetime.now(UTC).isoformat(), "evidence": "NOT VERIFIED"}
            atomic_write(self.record_path(project, key), json.dumps(record))
            records.append(record)
        return records

    def history(self, project: ProjectView) -> list[dict[str, Any]]:
        directory = self.root / str(uuid.UUID(project.id))
        records = []
        for path in directory.glob("*.json"):
            if path.is_symlink():
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
            records.append(record)
        return sorted(records, key=lambda item: str(item["created_at"]), reverse=True)[:100]

    async def run(self, project: ProjectView, key: str, *, approved: bool = False, policy: PermissionPolicy | None = None) -> dict[str, Any]:
        path = self.record_path(project, key)
        record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if record["status"] != "awaiting_approval":
            raise SafetyViolation("This hook already ran")
        if policy:
            policy.require("terminal.execute")
        elif not approved:
            raise SafetyViolation("Explicit hook execution permission is required")
        hook = Hook.model_validate(record["hook"])
        decision = CommandGuard().development(hook.argv)
        if decision.blocked:
            raise SafetyViolation(decision.reason)
        if decision.requires_user_approval and policy:
            policy.require("package.install")
            policy.require("network")
        root = Path(record["workspace"]).resolve(strict=True)
        if root != Path(project.path).resolve() and root.parent != (self.settings.data_directory / "workspaces").resolve():
            raise SafetyViolation("Invalid hook workspace")
        from app.graph.runtime import current_runtime
        runtime = current_runtime.get()
        if runtime:
            runtime.tool(f"hook:{hook.name}", "execute")
        result = await CommandRunner(root).run(hook.argv, hook.timeout, approved=True)
        record.update({"status": "passed" if result.exit_code == 0 and not result.timed_out else "failed", "exit_code": result.exit_code,
            "stdout": result.stdout, "stderr": result.stderr, "timed_out": result.timed_out, "evidence": "VERIFIED"})
        atomic_write(path, json.dumps(record))
        return record

    async def enforce(self, project: ProjectView, event: HookEvent, *, policy: PermissionPolicy | None = None,
                      approved: bool = False, workspace: Path | None = None) -> list[dict[str, Any]]:
        reports = []
        for record in self.queue(project, event, workspace):
            report = await self.run(project, record["id"], approved=approved, policy=policy)
            reports.append(report)
            if report["status"] != "passed":
                raise SafetyViolation(f"Hook {record['hook']['name']} failed; {event} did not pass")
        return reports
