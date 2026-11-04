import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.agents.reviewer import ReviewerAgent
from app.agents.tester import TesterAgent
from app.execution.local import LocalExecutionEnvironment
from app.llm.output import MALFORMED_RESPONSE, completion_problem, public_result
from app.models.entities import AgentRun, ChangeSet, Conversation, Message, RunCheckpoint
from app.schemas.domain import ChatRequest, ChatResponse, ProjectOpen, ProjectView
from app.schemas.engineering import ApplyAction, ProjectImport, ResumeAction, ValidationAction
from app.schemas.lifecycle import progress
from app.security.policy import SafetyViolation
from app.services.chat import ChatService
from app.services.lifecycle_views import proposal_view, task_view
from app.services.projects import ProjectService
from app.services.proposals import ChangeService, digest, proposal_context

router = APIRouter()


def projects(request: Request) -> ProjectService:
    return request.app.state.projects  # type: ignore[no-any-return]


def chat(request: Request) -> ChatService:
    return request.app.state.chat  # type: ignore[no-any-return]


Projects = Annotated[ProjectService, Depends(projects)]
Chat = Annotated[ChatService, Depends(chat)]


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {"status": "ok", "version": "0.3.0", "phase": 3,
            "provider": settings.llm_provider, "model": settings.llm_model or None,
            "model_configured": bool(settings.llm_model),
            "automatic_model_fallback": settings.llm_fallback_enabled,
            "capabilities": ["open_project", "import_project", "scan", "safe_read", "ask", "plan", "explain",
                             "review", "debug", "security_review", "propose_changes", "approved_apply", "approved_pytest", "activity_stream",
                             "manual_edit", "new_project", "terminal", "git", "checkpoints", "search", "native_tools",
                             "rules", "permissions", "hooks", "steering", "editable_plans"],
            "read_only": False, "execution_requires_approval": True}


@router.get("/models")
def models(service: Chat) -> dict[str, Any]:
    from app.llm.resilience import RunProvider, configured_models
    provider = RunProvider(service.provider, service.settings, service.cooldowns)
    return {"provider": provider.name, "automatic_fallback": service.settings.llm_fallback_enabled,
        "models": [{"model": model, "status": "rate_limited" if service.cooldowns.get(provider.key, model) else "available",
            "retry_at": (service.cooldowns.get(provider.key, model) or {}).get("retry_at")} for model in configured_models(service.settings)]}


@router.get("/projects")
def list_projects(service: Projects) -> list[dict[str, str]]:
    return service.list()


@router.post("/projects", response_model=ProjectView)
@router.post("/projects/open", response_model=ProjectView)
def open_project(body: ProjectOpen, service: Projects) -> ProjectView:
    return service.open(body.path)


@router.post("/projects/import", response_model=ProjectView)
def import_project(body: ProjectImport, service: Projects) -> ProjectView:
    return service.import_project(body)


@router.post("/projects/{project_id}/refresh", response_model=ProjectView)
def refresh_project(project_id: str, service: Projects) -> ProjectView:
    return service.refresh(project_id)


@router.get("/projects/{project_id}", response_model=ProjectView)
def get_project(project_id: str, service: Projects) -> ProjectView:
    return service.get(project_id)


@router.get("/projects/{project_id}/files")
def files(project_id: str, service: Projects) -> Any:
    return service.get(project_id).project_map.files


@router.get("/projects/{project_id}/map")
def project_map(project_id: str, service: Projects) -> Any:
    return service.get(project_id).project_map


@router.get("/projects/{project_id}/file")
def read_file(project_id: str, service: Projects, path: str = Query(min_length=1, max_length=4096)) -> dict[str, str]:
    project = service.get(project_id)
    content = LocalExecutionEnvironment(Path(project.path), service.settings.max_file_bytes, agent=False).read_file(path)
    return {"path": path, "content": content, "sha256": digest(content)}


@router.get("/projects/{project_id}/conversations")
def conversations(project_id: str, service: Projects) -> list[dict[str, str]]:
    service.get(project_id)
    with service.sessions() as session:
        return [{"id": c.id, "title": c.title} for c in session.scalars(select(Conversation).where(
            Conversation.project_id == project_id).order_by(Conversation.created_at.desc()).limit(30))]


@router.get("/projects/{project_id}/conversations/{conversation_id}")
def conversation_messages(project_id: str, conversation_id: str, service: Projects) -> list[dict[str, Any]]:
    service.get(project_id)
    with service.sessions() as session:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.project_id != project_id:
            raise HTTPException(404, "Conversation not found for this project")
        runs = list(session.scalars(select(AgentRun).where(AgentRun.conversation_id == conversation_id).order_by(AgentRun.created_at.desc())))
        messages = []
        for message in session.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)):
            run = next((r for r in runs if r.result and r.created_at <= message.created_at and r.result.get("answer") == message.content), None) if message.role == "assistant" else None
            checkpoint = session.get(RunCheckpoint, run.id) if run else None
            result = task_view(public_result(run.result), checkpoint.payload if checkpoint else None) if run else None
            messages.append({"role": message.role, "content": result["answer"] if result else MALFORMED_RESPONSE if message.role == "assistant" and completion_problem(message.content) else message.content, "result": result})
        return messages


@router.post("/chat", response_model=ChatResponse)
@router.post("/agent/run", response_model=ChatResponse)
async def run_chat(body: ChatRequest, service: Chat) -> ChatResponse:
    prepared = await asyncio.to_thread(service.prepare, body)
    result: ChatResponse | None = None
    async for event in service.events(body, prepared):
        if event.type == "result":
            result = ChatResponse.model_validate(event.data)
    if result is not None:
        return result
    raise HTTPException(500, "Agent run ended without a result")


@router.post("/code/explain", response_model=ChatResponse)
async def explain(body: ChatRequest, service: Chat) -> ChatResponse:
    return await run_chat(body.model_copy(update={"mode": "explain"}), service)


@router.post("/code/review", response_model=ChatResponse)
async def review(body: ChatRequest, service: Chat) -> ChatResponse:
    return await run_chat(body.model_copy(update={"mode": "review"}), service)


@router.post("/code/debug", response_model=ChatResponse)
async def debug(body: ChatRequest, service: Chat) -> ChatResponse:
    return await run_chat(body.model_copy(update={"mode": "debug"}), service)


@router.post("/code/test", response_model=ChatResponse)
async def test(body: ChatRequest, service: Chat) -> ChatResponse:
    return await run_chat(body.model_copy(update={"mode": "test"}), service)


@router.post("/chat/stream")
async def stream_chat(body: ChatRequest, service: Chat) -> StreamingResponse:
    prepared = await asyncio.to_thread(service.prepare, body)

    async def stream() -> AsyncIterator[str]:
        async for event in service.events(body, prepared):
            yield f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


@router.get("/runs/{run_id}")
def get_run(run_id: str, service: Projects) -> dict[str, Any]:
    with service.sessions() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise HTTPException(404, "Run not found")
        service.get(run.project_id)
        safe_result = public_result(run.result)
        checkpoint = session.get(RunCheckpoint, run_id)
        malformed = safe_result is not run.result
        result = task_view(safe_result, checkpoint.payload if checkpoint else None)
        events = []
        for event in run.events:
            if event["type"] == "result":
                event = {**event, "data": result or task_view(public_result(event.get("data")), checkpoint.payload if checkpoint else None),
                         "message": "failed" if malformed else event.get("message", "")}
            elif malformed and event["type"] in {"task_completed", "done"}:
                event = {**event, "type": "task_failed" if event["type"] == "task_completed" else "done",
                         "message": "Failed", "status": "failed"}
            elif result and result.get("status") == "paused" and event["type"] == "task_completed":
                event = {**event, "type": "task_paused", "status": "paused", "message": "Paused"}
            elif result and result.get("status") == "cancelled" and event["type"] in {"task_completed", "task_paused"}:
                event = {**event, "type": "task_cancelled", "status": "cancelled", "message": "Cancelled"}
            events.append(event)
        counts = progress(checkpoint.payload.get("engineering", {}).get("files", [])) if checkpoint else {}
        return {"id": run.id, "status": "failed" if malformed else (result or {}).get("status", run.status), "intent": run.intent,
                "events": events, "result": result,
                "diagnostics": (result or {}).get("diagnostics") or (checkpoint.payload.get("diagnostics", {}) if checkpoint else {}),
                "checkpoint": {"stage": checkpoint.payload.get("next_stage"),
                    **counts, "task_status": (result or {}).get("task_status", checkpoint.payload.get("task_status")),
                    "implementation_complete": (result or {}).get("implementation_complete", False),
                    "stage_states": (result or {}).get("stage_states", checkpoint.payload.get("stage_states", {})),
                    "retry_at": checkpoint.payload.get("retry_at"), "model_selection": checkpoint.payload.get("model_selection", {}),
                    "plan": checkpoint.payload.get("plan", []), "updated_at": checkpoint.updated_at.isoformat()} if checkpoint else None}


@router.get("/runs/{run_id}/diagnostics")
def run_diagnostics(run_id: str, service: Projects) -> dict[str, Any]:
    run = get_run(run_id, service)
    return {"diagnostics": run["diagnostics"], "checkpoint": run["checkpoint"]}


@router.post("/runs/{run_id}/resume", response_model=ChatResponse)
async def resume_run(run_id: str, service: Chat, body: ResumeAction | None = None) -> ChatResponse:
    with service.sessions() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise HTTPException(404, "Run not found")
        project_id = run.project_id
    return await run_chat(ChatRequest(project_id=project_id, resume_run_id=run_id, message="Continue the preserved task",
        allow_execution=bool(body and body.allow_execution), model=body.model if body else None), service)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, service: Chat) -> dict[str, Any]:
    with service.sessions.begin() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise HTTPException(404, "Run not found")
        service.projects.get(run.project_id)
        if run.status in {"completed", "proposed", "cancelled"}:
            raise SafetyViolation("Only an unfinished task can be cancelled")
        control = service.controls.get(run_id)
        if control:
            control.cancelled, control.stopped = True, True
            checkpoint = session.get(RunCheckpoint, run_id)
            if checkpoint:
                checkpoint.payload = {**checkpoint.payload, "task_status": "CANCELLED", "retryable": False}
            return {"status": "cancelling", "task_status": "CANCELLED"}
        run.status = "cancelled"
        if run.result:
            message = session.scalar(select(Message).where(Message.conversation_id == run.conversation_id,
                Message.role == "assistant", Message.content == run.result.get("answer")).order_by(Message.created_at.desc()))
            run.result = {**run.result, "status": "cancelled", "task_status": "CANCELLED", "resumable": False,
                "retryable": False, "answer": "Task cancelled. Its staged files remain available for inspection."}
            if message:
                message.content = run.result["answer"]
        checkpoint = session.get(RunCheckpoint, run_id)
        if checkpoint:
            checkpoint.payload = {**checkpoint.payload, "task_status": "CANCELLED", "retryable": False}
        return {"status": "cancelled", "task_status": "CANCELLED"}


@router.post("/runs/{run_id}/steer")
def steer_run(run_id: str, body: dict[str, str], service: Chat) -> dict[str, Any]:
    control = service.controls.get(run_id)
    message = body.get("message", "").strip()
    if control is None:
        raise HTTPException(409, "The task is no longer running")
    if not message or len(message) > 4000:
        raise HTTPException(422, "An update of 1–4000 characters is required")
    control.steer(message)
    return {"status": "queued", "message": "Update will be incorporated at the next safe boundary"}


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: str, service: Chat) -> dict[str, str]:
    control = service.controls.get(run_id)
    if control:
        control.stopped = True
    return {"status": "stopping" if control else "finished"}


@router.get("/runs/{run_id}/events")
def run_events(run_id: str, service: Projects) -> StreamingResponse:
    run = get_run(run_id, service)
    # Finite persisted replay. Live activity uses POST /chat/stream.
    frames = [f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in run["events"]]
    return StreamingResponse(iter(frames), media_type="text/event-stream")


@router.get("/changes/{change_id}")
def get_change(change_id: str, service: Projects) -> dict[str, Any]:
    with service.sessions() as session:
        change = session.get(ChangeSet, change_id)
        if change is None:
            raise HTTPException(404, "ChangeSet not found")
        service.get(change.project_id)
        checkpoint = session.scalar(select(RunCheckpoint).where(RunCheckpoint.payload["change_id"].as_string() == change_id).order_by(RunCheckpoint.updated_at.desc()))
        proposal = proposal_view(change.proposal, checkpoint.payload if checkpoint else None)
        return {"id": change.id, "status": change.status,
                "proposal": {k: v for k, v in proposal.items() if k != "stage_path"},
                "can_apply": change.status in {"proposed", "partially_applied"} and ChangeService.eligible(proposal)}


@router.post("/changes/{change_id}/apply")
def apply_change(change_id: str, body: ApplyAction, service: Projects) -> dict[str, Any]:
    with service.sessions() as session:
        record = session.get(ChangeSet, change_id)
        if record is None:
            raise HTTPException(404, "ChangeSet not found")
        project = service.get(record.project_id)
    ChangeService(service.sessions, service.settings).apply(change_id, project, body)
    service.refresh(project.id)
    return get_change(change_id, service)


@router.post("/changes/{change_id}/reject")
async def reject_change(change_id: str, service: Projects, chat_service: Chat, body: ApplyAction | None = None) -> dict[str, Any]:
    import copy

    from app.graph.engineering import EngineeringSession
    from app.schemas.domain import ContextChunk, Evidence
    from app.schemas.engineering import CodeProposal, ProposedFile
    from app.services.proposals import stage_proposal
    with service.sessions.begin() as session:
        record = session.get(ChangeSet, change_id)
        if record is None:
            raise HTTPException(404, "ChangeSet not found")
        project = service.get(record.project_id)
        if record.status not in {"proposed", "partially_applied"}:
            raise SafetyViolation("Only unapplied files can be rejected")
        proposal = copy.deepcopy(record.proposal)
        selected = set(body.files) if body and body.files is not None else {p["path"] for p in proposal["files"] if not p["applied"]}
        if not selected or selected - {p["path"] for p in proposal["files"] if not p["applied"]}:
            raise SafetyViolation("Select unapplied proposal files")
        for patch in proposal["files"]:
            if patch["path"] in selected:
                patch["rejected"] = True
        active = [p for p in proposal["files"] if not p["applied"] and not p.get("rejected")]
        version = record.proposal
    if active:
        # Rebuild and independently validate the remaining subset. Reports for the
        # original all-file proposal cannot certify a different patch combination.
        context = [ContextChunk(evidence=Evidence(file=p["path"], start_line=1, end_line=max(1, len(p["before"].splitlines())),
            sha256=digest(p["before"])), content="\n".join(f"{i}: {line}" for i, line in enumerate(p["before"].splitlines(), 1)),
            total_lines=max(1, len(p["before"].splitlines()))) for p in active if p["base_hash"] is not None]
        for patch in active:
            if patch["base_hash"] is not None and digest(LocalExecutionEnvironment(Path(project.path)).read_file(patch["path"])) != patch["base_hash"]:
                raise SafetyViolation("A remaining source file changed; regenerate this proposal")
        reduced = CodeProposal(summary=proposal["summary"], files=[ProposedFile(path=p["path"], content=p["after"],
            reason=p["reason"], delete=p.get("delete", False)) for p in active if not p.get("directory")],
            directories=[p["path"] for p in active if p.get("directory")])
        stage, patches, baseline = await asyncio.to_thread(stage_proposal, project, reduced, context, service.settings)
        engineering = EngineeringSession(project, ChatRequest(project_id=project.id, message="Review the remaining subset after per-file rejection. " + proposal["summary"],
            allow_execution=bool(body and getattr(body, "allow_execution", False))), chat_service.provider, service.settings, None)
        engineering.stage, engineering.patches, engineering.baseline = stage, patches, baseline
        engineering.implementation_complete = proposal.get("implementation_complete", True)
        engineering.context = proposal_context(stage, patches)
        await engineering.validate_static()
        await engineering.validate_security()
        await engineering.validate_tests()
        await engineering.validate_review()
        proposal.update({"stage_path": str(stage), "baseline": baseline, "static": engineering.static, "security": engineering.security,
            "tests": engineering.tests, "review": engineering.review})
    with service.sessions.begin() as session:
        record = session.get(ChangeSet, change_id)
        if record is None or record.proposal != version:
            raise SafetyViolation("ChangeSet changed during validation; retry")
        record.proposal = proposal
        record.status = ("partially_applied" if any(p["applied"] for p in proposal["files"]) else "proposed") if active else ("applied" if any(p["applied"] for p in proposal["files"]) else "rejected")
    return get_change(change_id, service)


@router.post("/changes/{change_id}/validate")
async def validate_change(change_id: str, body: ValidationAction, service: Projects, chat_service: Chat) -> dict[str, Any]:
    if not body.allow_execution:
        raise SafetyViolation("Explicit local test execution permission is required")
    with service.sessions() as session:
        record = session.get(ChangeSet, change_id)
        if record is None:
            raise HTTPException(404, "ChangeSet not found")
        if record.status != "proposed":
            raise SafetyViolation("Validation requires an unapplied proposal")
        project = service.get(record.project_id)
        proposal = record.proposal
        if not proposal.get("implementation_complete", True):
            raise SafetyViolation("Implementation is incomplete; resume the task before running final validation")
        checkpoint = session.scalar(select(RunCheckpoint).where(RunCheckpoint.payload["change_id"].as_string() == change_id).order_by(RunCheckpoint.updated_at.desc()))
        checkpoint_id = checkpoint.run_id if checkpoint and checkpoint.payload.get("next_stage") in {"TEST", "REVIEW", "SECURITY", "VALIDATE"} else None
    if checkpoint_id:
        await run_chat(ChatRequest(project_id=project.id, resume_run_id=checkpoint_id,
            message="Continue the saved validation stage with local test execution approved", allow_execution=True), chat_service)
        return get_change(change_id, service)
    from app.services.preferences import PermissionPolicy
    PermissionPolicy(service.settings, ChatRequest(project_id=project.id, message="Validate proposal", allow_execution=True)).require("terminal.execute")
    stage = Path(proposal["stage_path"]).resolve(strict=True)
    if stage.parent != (service.settings.data_directory / "workspaces").resolve():
        raise SafetyViolation("Invalid validation workspace")
    if proposal["static"].get("status") != "passed" or proposal["security"].get("status") != "passed":
        raise SafetyViolation("Static and security gates must pass before tests can run")
    active = [p for p in proposal["files"] if not p.get("rejected")]
    removed = {p["path"] for p in active if p.get("delete") or p.get("directory")}
    paths = list(({f.path for f in project.project_map.files} | {p["path"] for p in active}) - removed)
    expected = {k: v for k, v in {**proposal.get("baseline", {}), **{p["path"]: digest(p["after"]) for p in active}}.items() if k not in removed}
    report = await TesterAgent().run(stage, paths, service.settings, True, expected_hashes=expected)
    review = proposal["review"]
    if report.status == "passed" and not review.get("approved"):
        task = "Independently review this proposed change after approved local test execution.\n"
        task += "Validation reports:\n" + json.dumps({"static": proposal["static"], "security": proposal["security"], "tests": report.model_dump()})[:20000]
        task += "\nDiffs:\n" + "\n".join(p["diff"] for p in active)[:30000]
        updated = await ReviewerAgent(chat_service.provider).review(task, proposal_context(stage, active), project.project_map)
        review = updated.model_dump()
    with service.sessions.begin() as session:
        record = session.get(ChangeSet, change_id)
        if record is not None and record.status == "proposed":
            record.proposal = {**record.proposal, "tests": report.model_dump(), "review": review, "in_progress": False}
    return get_change(change_id, service)
