import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.graph.runtime import RunRuntime
from app.graph.workflow import workflow_events
from app.llm.base import LLMProvider, ProviderError
from app.llm.output import completion_problem
from app.llm.resilience import ModelCooldowns, RunProvider, configured_models
from app.models.entities import AgentRun, Conversation, Message
from app.schemas.domain import (
    AgentEvent,
    ChatRequest,
    ChatResponse,
    Evidence,
    Intent,
    ProjectView,
    ToolResult,
)
from app.schemas.lifecycle import LIFECYCLE_FIELDS, task_status
from app.security.policy import SafetyViolation
from app.security.redaction import redact_secrets
from app.services.hooks import HookService
from app.services.preferences import CapabilityRequired, PermissionPolicy
from app.services.projects import ProjectNotFound, ProjectService
from app.services.proposals import ChangeService
from app.services.run_checkpoints import RunCheckpointStore
from app.services.run_control import RunControl, SteeringUpdate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedRun:
    run_id: str
    conversation_id: str
    project: ProjectView
    history: list[dict[str, str]]
    request: ChatRequest | None = None


class ChatService:
    def __init__(self, settings: Settings, sessions: sessionmaker[Session],
                 projects: ProjectService, provider: LLMProvider):
        self.settings = settings
        self.sessions = sessions
        self.projects = projects
        self.provider = provider
        self.controls: dict[str, RunControl] = {}
        self.cooldowns = ModelCooldowns()
        from datetime import UTC, datetime

        from app.models.entities import RunCheckpoint
        with sessions() as session:
            for record in session.scalars(select(RunCheckpoint).where(RunCheckpoint.payload["pause_reason"].as_string() == "PROVIDER_RATE_LIMIT")):
                saved = record.payload
                selection = saved.get("model_selection", {})
                key, model, retry_at = selection.get("provider_identity"), selection.get("active_model"), saved.get("retry_at")
                if key and model and retry_at and datetime.fromisoformat(retry_at) > datetime.now(UTC):
                    existing = self.cooldowns.get(key, model)
                    if existing is None or retry_at > existing["retry_at"]:
                        self.cooldowns.entries[(key, model)] = {"retry_at": retry_at}

    async def controlled_workflow(self, request: ChatRequest, prepared: PreparedRun, runtime: RunRuntime) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        control = RunControl(request.project_id)
        self.controls[prepared.run_id] = control
        checkpoints = RunCheckpointStore(self.sessions, prepared.run_id)
        try:
            resume = RunCheckpointStore(self.sessions, request.resume_run_id).claim(request.project_id, prepared.run_id) if request.resume_run_id else None
            root_run_id = resume.get("root_run_id", request.resume_run_id) if resume else prepared.run_id
            provider = RunProvider(self.provider, self.settings, self.cooldowns, (resume or {}).get("model_selection"), request.model)
            def save_checkpoint(payload: dict[str, Any]) -> None:
                checkpoints.save({**payload, "root_run_id": root_run_id, "task_id": root_run_id, "run_id": prepared.run_id,
                    "model_selection": provider.selection})
            while True:
                try:
                    async for item in workflow_events(request, Path(prepared.project.path), prepared.project.project_map,
                        provider, self.settings, prepared.history, ChangeService(self.sessions, self.settings), control.boundary,
                        checkpoint=save_checkpoint, resume_state=resume, runtime=runtime, model_selection=provider.selection):
                        yield item
                    break
                except SteeringUpdate as update:
                    steering = "\n".join(update.messages)
                    request = request.model_copy(update={"message": (request.message + "\nUser update (takes precedence):\n" + steering)[-12000:]})
                    resume = None
                    root_run_id = prepared.run_id
                    with self.sessions.begin() as session:
                        session.add(Message(conversation_id=prepared.conversation_id, role="user", content=redact_secrets(steering)))
                    yield "_restart", {"message": "User update incorporated; discarded staged edits and replanning safely"}
        finally:
            self.controls.pop(prepared.run_id, None)

    async def bounded_workflow(self, request: ChatRequest, prepared: PreparedRun, runtime: RunRuntime) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        try:
            async with asyncio.timeout(self.settings.agent_timeout_seconds):
                PermissionPolicy(self.settings, request).require("filesystem.read")
                async for item in self.controlled_workflow(request, prepared, runtime):
                    yield item
        except TimeoutError as error:
            raise ProviderError("The agent task reached its total time limit. Its working checkpoint is preserved; resume to continue.") from error

    def prepare(self, request: ChatRequest) -> PreparedRun:
        if request.resume_run_id:
            saved = RunCheckpointStore(self.sessions, request.resume_run_id).load(request.project_id)
            selected_model = request.model or saved.get("model_selection", {}).get("model", self.settings.llm_model)
            if request.model and request.model not in configured_models(self.settings):
                raise SafetyViolation("Choose a model from the configured model list")
            # Retry-After applies to this provider/model, never the entire runtime.
            limited_model = saved.get("model_selection", {}).get("active_model", selected_model)
            if (not request.model or request.model == limited_model) and saved.get("retry_at"):
                from datetime import UTC, datetime
                if datetime.fromisoformat(saved["retry_at"]) > datetime.now(UTC) and not self.settings.llm_fallback_enabled:
                    raise SafetyViolation("This model is still cooling down. Resume after Retry-After or switch to another configured model.")
            if selected_model:
                probe = RunProvider(self.provider, self.settings, self.cooldowns, saved.get("model_selection"), request.model)
                limited = self.cooldowns.get(probe.key, str(selected_model))
                if limited and not self.settings.llm_fallback_enabled:
                    raise SafetyViolation("This model is still cooling down; no provider request was sent")
            with self.sessions() as session:
                parent = session.get(AgentRun, request.resume_run_id)
                if parent is None:
                    raise SafetyViolation("Resume task not found")
                conversation_id = parent.conversation_id
                if saved.get("change_id"):
                    from app.models.entities import ChangeSet
                    change = session.get(ChangeSet, saved["change_id"])
                    if change is None or change.status != "proposed":
                        raise SafetyViolation("Applied or rejected changes cannot be resumed")
            request = ChatRequest.model_validate({**saved["request"], "conversation_id": conversation_id,
                "resume_run_id": request.resume_run_id, "allow_execution": request.allow_execution, "approvals": request.approvals, "model": request.model})
        project = self.projects.get(request.project_id)
        with self.sessions.begin() as session:
            if request.conversation_id:
                conversation = session.get(Conversation, request.conversation_id)
                if conversation is None or conversation.project_id != request.project_id:
                    raise ProjectNotFound("Conversation not found for this project")
            else:
                conversation = Conversation(project_id=request.project_id, title=redact_secrets(request.message[:100]))
                session.add(conversation)
                session.flush()
            recent = list(session.scalars(select(Message).where(
                Message.conversation_id == conversation.id).order_by(Message.created_at.desc()).limit(6)))
            history = [{"role": m.role, "content": redact_secrets(m.content[:1500])} for m in reversed(recent)
                       if m.role != "assistant" or not completion_problem(m.content)]
            session.add(Message(conversation_id=conversation.id, role="user", content=redact_secrets(request.message)))
            run = AgentRun(project_id=project.id, conversation_id=conversation.id, status="running")
            session.add(run)
            session.flush()
            return PreparedRun(run.id, conversation.id, project, history, request)

    def save_event(self, run_id: str, event: AgentEvent) -> None:
        with self.sessions.begin() as session:
            run = session.get(AgentRun, run_id)
            if run is not None:
                run.events = [*run.events, event.model_dump(mode="json")]

    def finish(self, prepared: PreparedRun, result: ChatResponse) -> None:
        with self.sessions.begin() as session:
            run = session.get(AgentRun, prepared.run_id)
            if run is not None:
                run.status = result.status
                run.intent = result.intent.value
                run.result = result.model_dump(mode="json")
                session.add(Message(conversation_id=prepared.conversation_id, role="assistant", content=result.answer))

    async def events(self, request: ChatRequest, prepared: PreparedRun) -> AsyncIterator[AgentEvent]:
        request = prepared.request or request
        runtime = RunRuntime(self.settings, run_id=prepared.run_id)
        intent = Intent.ASK
        intents: list[Intent] = []
        evidence: list[Evidence] = []
        artifacts: list[ToolResult] = []
        change_id: str | None = None
        answer = ""
        status: Any = "failed"
        confidence: Any = "LOW"
        lifecycle: dict[str, Any] = {}

        async def record(event: AgentEvent) -> AgentEvent:
            await asyncio.to_thread(self.save_event, prepared.run_id, event)
            return event

        try:
            yield await record(AgentEvent(type="task_started", message="Analyzing request", agent="orchestrator",
                                         status="running", data={"run_id": prepared.run_id, "conversation_id": prepared.conversation_id}))
            async for node, values in self.bounded_workflow(request, prepared, runtime):
                if node == "_restart":
                    evidence, artifacts, change_id = [], [], None
                    yield await record(AgentEvent(type="task_restarted", message=values["message"], agent="orchestrator", status="running"))
                    continue
                if node == "orchestrator":
                    intent = values["intent"]
                    intents = values["intents"]
                    yield await record(AgentEvent(type="agent_status", message="Request understood; inspecting relevant code",
                        agent="orchestrator", status="completed", data={"intents": [i.value for i in intents], "workflow": values["workflow"]}))
                elif node == "retrieve":
                    evidence = values["retrieved_context"]
                if node == "_status":
                    if values.get("evidence"):
                        item = Evidence.model_validate(values["evidence"])
                        if item not in evidence:
                            evidence.append(item)
                    trace_artifact = values.get("artifact")
                    if trace_artifact:
                        artifacts.append(ToolResult.model_validate(trace_artifact))
                        if trace_artifact.get("data", {}).get("change_id"):
                            change_id = trace_artifact["data"]["change_id"]
                    yield await record(AgentEvent(type=values.get("type", "agent_status"), message=values["message"],
                        agent=values["agent"], status=values.get("status", "running"),
                        data=trace_artifact or {k: v for k, v in values.items() if k not in {"agent", "message", "type"}}))
                    continue
                artifact = values.get("artifact")
                if artifact:
                    tool = ToolResult.model_validate(artifact)
                    artifacts.append(tool)
                    event_type = {"context": "context_retrieved", "plan": "plan_created", "changes": "code_change_created",
                                  "tests": "test_result", "security": "security_result", "review": "review_result"}.get(tool.type, "tool_result")
                    yield await record(AgentEvent(type=event_type, message=tool.title, agent=node,
                                                  status=tool.status, data=tool.model_dump(mode="json")))
                if values.get("change_id"):
                    change_id = values["change_id"]
                if "answer" in values:
                    answer, status, confidence = values["answer"], values["status"], values["confidence"]
                    lifecycle = {key: values[key] for key in LIFECYCLE_FIELDS if key in values}
            if completion_problem(answer):
                from app.llm.output import MALFORMED_RESPONSE
                raise ProviderError(MALFORMED_RESPONSE)
        except asyncio.CancelledError:
            from app.models.entities import RunCheckpoint
            with self.sessions() as session:
                checkpoint = session.get(RunCheckpoint, prepared.run_id)
                payload = checkpoint.payload if checkpoint else {}
                lifecycle = {key: payload[key] for key in LIFECYCLE_FIELDS if key in payload}
                change_id = payload.get("change_id", change_id)
            lifecycle.update(task_status="PAUSED", stage=runtime.current_stage, checkpoint_preserved=checkpoint is not None)
            result = ChatResponse(run_id=prepared.run_id, conversation_id=prepared.conversation_id,
                intent=intent, status="paused", **lifecycle,
                answer="Task paused. Its working checkpoint is preserved for continuation.",
                evidence=evidence, confidence="LOW", provider=self.provider.name, change_id=change_id,
                diagnostics=runtime.diagnostics(), resumable=checkpoint is not None)
            self.finish(prepared, result)
            raise
        except CapabilityRequired as error:
            status, confidence, answer = error.result()["status"], "HIGH", str(error)
            artifact = ToolResult(type="permission", title="Agent capability permission", status=status, data=error.result())
            artifacts.append(artifact)
            yield await record(AgentEvent(type="permission_required", message=answer, data=artifact.model_dump()))
        except (ProviderError, SafetyViolation, OSError) as error:
            status, confidence = "paused" if isinstance(error, ProviderError) and error.retryable else "failed", "LOW"
            answer = str(error) if isinstance(error, (ProviderError, SafetyViolation)) else "Project files changed or became unreadable; refresh the project."
            yield await record(AgentEvent(type="agent_status" if status == "paused" else "error", message=answer, status=status))
        except Exception as error:
            status, confidence = "failed", "LOW"
            logger.error("agent_run_failed", extra={"run_id": prepared.run_id, "error_type": type(error).__name__})
            answer = "The run could not complete. Check the backend logs and refresh the project."
            yield await record(AgentEvent(type="error", message=answer))
        with self.sessions() as session:
            from app.models.entities import RunCheckpoint
            saved_checkpoint = session.get(RunCheckpoint, prepared.run_id)
            can_resume = saved_checkpoint is not None and status in {"paused", "partial", "awaiting_approval", "blocked", "failed"}
            if saved_checkpoint and not lifecycle:
                lifecycle = {key: saved_checkpoint.payload[key] for key in LIFECYCLE_FIELDS if key in saved_checkpoint.payload}
        lifecycle["task_status"] = task_status(status).value
        lifecycle["checkpoint_preserved"] = saved_checkpoint is not None
        lifecycle.pop("resumable", None)
        result = ChatResponse(run_id=prepared.run_id, conversation_id=prepared.conversation_id,
                              intent=intent, status=status, answer=answer, evidence=evidence,
                              confidence=confidence, provider=self.provider.name,
                              intents=intents, artifacts=artifacts, change_id=change_id,
                              diagnostics=runtime.diagnostics(), resumable=can_resume, **lifecycle)
        try:
            pending_hooks = HookService(self.settings).queue(prepared.project, "AfterAgentTask") if status in {"completed", "proposed"} else []
            if pending_hooks:
                result.artifacts.append(ToolResult(type="hooks", title="After-task hooks pending approval", status="awaiting_approval",
                    data={"hook_ids": [hook["id"] for hook in pending_hooks], "evidence": "NOT VERIFIED"}))
        except (ValueError, OSError, SafetyViolation):
            result.artifacts.append(ToolResult(type="hooks", title="Project hook configuration is invalid", status="blocked"))
        await asyncio.to_thread(self.finish, prepared, result)
        yield await record(AgentEvent(type="result", message=result.status, data=result.model_dump(mode="json")))
        terminal_event = {"failed": "task_failed", "paused": "task_paused", "cancelled": "task_cancelled", "blocked": "task_blocked", "awaiting_approval": "task_blocked"}.get(status, "task_completed")
        yield await record(AgentEvent(type=terminal_event, message="Completed" if status == "completed" else status.capitalize(), status=status))
        yield await record(AgentEvent(type="done", message="Completed" if status == "completed" else status.capitalize()))
