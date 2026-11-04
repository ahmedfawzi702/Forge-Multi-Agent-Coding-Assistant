"""Upgrade historical checkpoint presentation without discarding its evidence."""
import copy
from typing import Any

from app.llm.base import ProviderError
from app.schemas.lifecycle import STAGES, not_run, progress, public_gate, task_status


def proposal_view(proposal: dict[str, Any], checkpoint: dict[str, Any] | None = None) -> dict[str, Any]:
    result = copy.deepcopy(proposal)
    complete = result.get("implementation_complete", not checkpoint or checkpoint.get("next_stage") not in {"IMPLEMENT"})
    result["implementation_complete"] = complete
    result["staged_changes"] = progress(result.get("files", []))
    if not complete:
        result["previous_validation"] = {key: result.get(key, {}) for key in ("static", "tests", "security", "review")}
        result.update({key: not_run() for key in ("static", "tests", "security", "review")})
        result["in_progress"] = True
    return result


def task_view(result: dict[str, Any] | None, checkpoint: dict[str, Any] | None) -> dict[str, Any] | None:
    if not result:
        return result
    if result.get("task_status") and "implementation_complete" in result:
        return result
    value = copy.deepcopy(result)
    status = "paused" if value.get("status") == "partial" else value.get("status", "failed")
    stage = (checkpoint or {}).get("next_stage", value.get("diagnostics", {}).get("current_stage", "FINALIZE"))
    proposal = proposal_view((checkpoint or {}).get("engineering", {}), checkpoint)
    complete = proposal["implementation_complete"]
    states = dict.fromkeys(STAGES, "NOT_STARTED")
    states[stage] = "PAUSED" if status == "paused" else task_status(status).value
    value.update(status=status, task_status=task_status(status).value, stage=stage, stage_states=states,
        checkpoint_preserved=checkpoint is not None, implementation_complete=complete,
        staged_changes=proposal["staged_changes"],
        static_validation=public_gate(proposal.get("static", {}), "static", complete),
        tests=public_gate(proposal.get("tests", {}), "tests", complete),
        security=public_gate(proposal.get("security", {}), "security", complete),
        review=public_gate(proposal.get("review", {}), "review", complete))
    if status == "paused":
        error = ProviderError(value.get("answer", "").split("\n\n", 1)[0])
        value.update({key: item for key, item in error.metadata().items() if key not in {"provider", "model", "retry_at", "retry_after_seconds"}})
        value["answer"] = f"Task paused safely. Stage: {stage}. Reason: {value['pause_reason']}. Checkpoint preserved.\n\nStaged files: {value['staged_changes']['files']}. Staged directories: {value['staged_changes']['directories']}. Applied files: {value['staged_changes']['applied_files']}.\n\nTests: {value['tests']['status']}. Security: {value['security']['status']}. Review: {value['review']['status']}. Resume when available."
    if not complete:
        for artifact in value.get("artifacts", []):
            if artifact.get("type") in {"static", "tests", "security", "review"}:
                artifact.update(status="not_run", data=not_run())
    return value


def interrupted_view(run_id: str, conversation_id: str, checkpoint: dict[str, Any]) -> dict[str, Any]:
    from app.schemas.lifecycle import LIFECYCLE_FIELDS
    data = checkpoint.get("engineering", {})
    complete = data.get("implementation_complete", checkpoint.get("next_stage") != "IMPLEMENT")
    stage = checkpoint.get("next_stage", "IMPLEMENT")
    states = {**dict.fromkeys(STAGES, "NOT_STARTED"), **checkpoint.get("stage_states", {}), stage: "PAUSED"}
    lifecycle = {key: checkpoint[key] for key in LIFECYCLE_FIELDS if key in checkpoint}
    lifecycle.update(task_status="PAUSED", stage=stage, stage_states=states, implementation_complete=complete,
        checkpoint_preserved=True, pause_reason="TASK_INTERRUPTED", retryable=True, retry_at=None,
        staged_changes=progress(data.get("files", [])),
        static_validation=public_gate(data.get("static", {}), "static", complete),
        tests=public_gate(data.get("tests", {}), "tests", complete),
        security=public_gate(data.get("security", {}), "security", complete),
        review=public_gate(data.get("review", {}), "review", complete))
    return {"run_id": run_id, "conversation_id": conversation_id, "intent": "CODE", "status": "paused",
        "answer": "Task paused after the backend restarted. Checkpoint and staged source are preserved. Resume from " + stage + ".",
        "evidence": [], "confidence": "LOW", "provider": checkpoint.get("model_selection", {}).get("provider", "unknown"),
        "change_id": checkpoint.get("change_id"), "resumable": True, "diagnostics": checkpoint.get("diagnostics", {}), **lifecycle}
