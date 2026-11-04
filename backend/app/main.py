import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select

from app.api.body_limit import BodyLimitMiddleware
from app.api.git import router as git_router
from app.api.hooks import router as hooks_router
from app.api.preferences import router as preferences_router
from app.api.routes import router
from app.api.terminal import router as terminal_router
from app.api.workspace import router as workspace_router
from app.config import Settings
from app.db.session import Base, create_database
from app.execution.terminal import TerminalManager
from app.llm.factory import create_provider
from app.models.entities import AgentRun, Message, RunCheckpoint
from app.security.policy import SafetyViolation
from app.services.chat import ChatService
from app.services.projects import ProjectNotFound, ProjectService
from app.services.workspace_files import WorkspaceFiles


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"level": record.levelname, "logger": record.name,
                           "message": record.getMessage(),
                           "run_id": getattr(record, "run_id", None),
                           "error_type": getattr(record, "error_type", None)})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine, sessions = create_database(settings.resolved_database_url)
        Base.metadata.create_all(engine)
        # A restart interrupts work; an available checkpoint makes it resumable.
        with sessions.begin() as session:
            for run in session.scalars(select(AgentRun).where(AgentRun.status == "running")):
                checkpoint = session.get(RunCheckpoint, run.id)
                if checkpoint:
                    from app.services.lifecycle_views import interrupted_view
                    run.result = interrupted_view(run.id, run.conversation_id, checkpoint.payload)
                    cancelled = checkpoint.payload.get("task_status") == "CANCELLED"
                    run.status = "cancelled" if cancelled else "paused"
                    if cancelled:
                        run.result.update(status="cancelled", task_status="CANCELLED", resumable=False, retryable=False,
                            answer="Task cancelled. Its staged source remains available for inspection.")
                    checkpoint.payload = {**checkpoint.payload, "task_status": "CANCELLED" if cancelled else "PAUSED", "pause_reason": "USER_CANCELLED" if cancelled else "TASK_INTERRUPTED"}
                    session.add(Message(conversation_id=run.conversation_id, role="assistant", content=run.result["answer"]))
                else:
                    run.status = "failed"
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
            provider = create_provider(settings, client)
            app.state.settings = settings
            app.state.projects = ProjectService(settings, sessions)
            app.state.files = WorkspaceFiles(settings)
            app.state.terminals = TerminalManager()
            app.state.chat = ChatService(settings, sessions, app.state.projects, provider)
            yield
            await app.state.terminals.shutdown()
        engine.dispose()

    app = FastAPI(title="Forge Coding IDE", version="0.3.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    app.add_middleware(BodyLimitMiddleware, limit=settings.max_request_bytes)

    @app.middleware("http")
    async def local_browser_boundary(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        origin = request.headers.get("origin")
        same_origin = str(request.base_url).rstrip("/")
        if origin and origin not in [*settings.cors_origins, same_origin]:
            return JSONResponse({"detail": "Browser origin is not allowed"}, status_code=403)
        host = request.url.hostname
        if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            return JSONResponse({"detail": "Local hosts only"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(SafetyViolation)
    async def safety_error(request: Request, error: SafetyViolation) -> JSONResponse:
        return JSONResponse({"detail": str(error), "blocked": True}, status_code=403)

    @app.exception_handler(ProjectNotFound)
    async def missing_project(request: Request, error: ProjectNotFound) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(FileNotFoundError)
    async def missing_file(request: Request, error: FileNotFoundError) -> JSONResponse:
        return JSONResponse({"detail": "File or directory no longer exists; refresh the project"}, status_code=404)

    app.include_router(router)
    app.include_router(workspace_router)
    app.include_router(terminal_router)
    app.include_router(git_router)
    app.include_router(preferences_router)
    app.include_router(hooks_router)
    return app


handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.getLogger("app").addHandler(handler)
logging.getLogger("app").setLevel(logging.INFO)
app = create_app()
