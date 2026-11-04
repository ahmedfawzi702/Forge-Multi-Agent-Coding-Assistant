"""Public lifecycle states; unfinished and unexecuted work never means failure."""
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


STAGES = ("UNDERSTAND", "CONTEXT", "PLAN", "IMPLEMENT", "VALIDATE", "SECURITY", "TEST", "REVIEW", "FINALIZE")
LIFECYCLE_FIELDS = ("task_status", "stage", "stage_states", "implementation_complete", "checkpoint_preserved",
    "staged_changes", "static_validation", "tests", "security", "review", "pause_reason", "retryable",
    "retry_after_seconds", "retry_at", "model_selection")


def not_run(reason: str = "Implementation incomplete") -> dict[str, Any]:
    return {"status": "not_run", "reason": reason, "summary": reason, "evidence": "NOT VERIFIED", "scope": "FINAL"}


def progress(files: list[dict[str, Any]]) -> dict[str, int]:
    staged = [item for item in files if not item.get("applied") and not item.get("rejected")]
    actual = [item for item in staged if not item.get("directory")]
    return {"files": len(actual), "directories": sum(bool(item.get("directory")) for item in staged),
        "files_created": sum(item.get("base_hash") is None and not item.get("delete") for item in actual),
        "files_modified": sum(item.get("base_hash") is not None and not item.get("delete") for item in actual),
        "files_deleted": sum(bool(item.get("delete")) for item in actual),
        "applied_files": sum(bool(item.get("applied")) and not item.get("directory") for item in files)}


def public_gate(report: dict[str, Any], kind: str, implementation_complete: bool) -> dict[str, Any]:
    if not implementation_complete:
        return {"status": "NOT_RUN", "reason": "Implementation incomplete", "scope": "FINAL"}
    status = report.get("status", "not_run")
    if kind == "review":
        occurred = "approved" in report and isinstance(report.get("score"), (int, float)) and report.get("verification") != "NOT VERIFIED"
        if not occurred:
            return {"status": "NOT_RUN", "reason": report.get("reason", "Final review has not completed"), "kind": "FINAL_REVIEW"}
        return {**report, "status": "APPROVED" if report["approved"] else "NOT_APPROVED", "kind": "FINAL_REVIEW"}
    if kind == "tests" and status == "failed" and report.get("exit_code") is None:
        status = "blocked"  # A preflight/integrity problem is not a failed pytest execution.
    mapped = {"passed": "PASSED", "failed": "FAILED", "not_run": "NOT_RUN", "partial": "PARTIAL",
        "blocked": "BLOCKED", "awaiting_approval": "BLOCKED", "not_found": "BLOCKED", "unsupported": "BLOCKED", "not_applicable": "NOT_APPLICABLE"}
    return {**report, "status": mapped.get(status, "NOT_RUN"), "scope": "FINAL"}


def task_status(status: str) -> TaskStatus:
    return {"running": TaskStatus.RUNNING, "pending": TaskStatus.PENDING, "paused": TaskStatus.PAUSED,
        "partial": TaskStatus.PAUSED, "blocked": TaskStatus.BLOCKED, "awaiting_approval": TaskStatus.BLOCKED,
        "failed": TaskStatus.FAILED, "cancelled": TaskStatus.CANCELLED}.get(status, TaskStatus.COMPLETED)
