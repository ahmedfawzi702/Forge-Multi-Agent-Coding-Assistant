import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.entities import AgentRun, RunCheckpoint
from app.security.policy import SafetyViolation


class RunCheckpointStore:
    def __init__(self, sessions: sessionmaker[Session], run_id: str):
        self.sessions, self.run_id = sessions, run_id

    def save(self, payload: dict[str, Any]) -> None:
        with self.sessions.begin() as session:
            existing = session.get(RunCheckpoint, self.run_id)
            if existing:
                existing.payload = copy.deepcopy(payload)
            else:
                session.add(RunCheckpoint(run_id=self.run_id, payload=copy.deepcopy(payload)))

    def load(self, project_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            run = session.get(AgentRun, self.run_id)
            record = session.get(RunCheckpoint, self.run_id)
            if run is None or run.project_id != project_id or record is None:
                raise SafetyViolation("No resumable checkpoint exists for this project/run")
            if run.status == "running":
                raise SafetyViolation("This task is still running; stop it before resuming")
            if run.status not in {"paused", "partial", "blocked", "failed", "awaiting_approval"}:
                raise SafetyViolation("This task is already complete; no continuation is needed")
            related = session.scalars(select(RunCheckpoint).join(AgentRun, AgentRun.id == RunCheckpoint.run_id).where(AgentRun.project_id == project_id))
            for candidate in related:
                same_root = candidate.payload.get("root_run_id", candidate.run_id) == record.payload.get("root_run_id", self.run_id)
                same_change = record.payload.get("change_id") is not None and candidate.payload.get("change_id") == record.payload.get("change_id")
                if (same_root or same_change) and candidate.payload.get("task_status") == "CANCELLED":
                    raise SafetyViolation("This task was cancelled; its staged changes are available for inspection only")
            return copy.deepcopy(record.payload)

    def claim(self, project_id: str, new_run_id: str) -> dict[str, Any]:
        with self.sessions.begin() as session:
            if session.bind is not None and session.bind.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            record = session.get(RunCheckpoint, self.run_id)
            owner = session.get(AgentRun, self.run_id)
            if record is None or owner is None or owner.project_id != project_id or owner.status not in {"paused", "partial", "blocked", "failed", "awaiting_approval"}:
                raise SafetyViolation("Checkpoint is unavailable or still running")
            change_id = record.payload.get("change_id")
            root_run_id = record.payload.get("root_run_id", self.run_id)
            related = list(session.scalars(select(RunCheckpoint).join(AgentRun, AgentRun.id == RunCheckpoint.run_id).where(AgentRun.project_id == project_id)))
            for candidate in related:
                same_lineage = candidate.payload.get("root_run_id", candidate.run_id) == root_run_id
                same_changes = change_id is not None and candidate.payload.get("change_id") == change_id
                if candidate.run_id == new_run_id or not (same_lineage or same_changes):
                    continue
                if candidate.payload.get("task_status") == "CANCELLED":
                    raise SafetyViolation("This task was cancelled")
                active_id = candidate.payload.get("active_run_id")
                active = session.get(AgentRun, active_id) if active_id else None
                if active is not None and active.id != new_run_id and active.status == "running":
                    raise SafetyViolation("Another continuation is already using this working ChangeSet")
            payload = copy.deepcopy(record.payload)
            record.payload = {**payload, "active_run_id": new_run_id}
            return payload
