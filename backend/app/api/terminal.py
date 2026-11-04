import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.routes import Projects
from app.execution.local import LocalExecutionEnvironment
from app.execution.terminal import TerminalManager
from app.schemas.workspace import CommandRequest, TerminalCreate, TerminalInput, TerminalResize
from app.security.policy import SafetyViolation

router = APIRouter()


def terminals(request: Request) -> TerminalManager:
    return request.app.state.terminals  # type: ignore[no-any-return]


Terminals = Annotated[TerminalManager, Depends(terminals)]


@router.post("/projects/{project_id}/terminal")
async def open_terminal(project_id: str, body: TerminalCreate, service: Projects, manager: Terminals) -> dict[str, str]:
    if not body.approved:
        raise SafetyViolation("Approve opening a local developer shell first")
    project = service.get(project_id)
    from pathlib import Path
    environment = LocalExecutionEnvironment(Path(project.path), agent=False, allow_execute=True)
    session = await manager.create(environment, project_id, body.cols, body.rows)
    return {"id": session.id, "status": "running"}


@router.get("/projects/{project_id}/terminal")
def list_terminals(project_id: str, service: Projects, manager: Terminals) -> list[dict[str, str]]:
    service.get(project_id)
    return [{"id": item.id, "status": "closed" if item.closed else "running"}
            for item in manager.sessions.values() if item.project_id == project_id]


@router.get("/projects/{project_id}/terminal/{session_id}/events")
async def terminal_events(project_id: str, session_id: str, service: Projects, manager: Terminals, request: Request, after: int = 0) -> StreamingResponse:
    service.get(project_id)
    session = manager.get(project_id, session_id)

    async def stream() -> AsyncIterator[str]:
        last = request.headers.get("last-event-id", "0")
        cursor = max(after, int(last) if last.isdigit() else 0)
        while True:
            for event in list(session.events):
                if event["seq"] > cursor:
                    cursor = event["seq"]
                    yield f"id: {event['seq']}\ndata: {json.dumps(event)}\n\n"
            if session.closed and cursor >= session.sequence:
                break
            await asyncio.sleep(0.05)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/projects/{project_id}/terminal/{session_id}/input")
async def terminal_input(project_id: str, session_id: str, body: TerminalInput, service: Projects, manager: Terminals) -> dict[str, str]:
    service.get(project_id)
    await manager.write(manager.get(project_id, session_id), body.data)
    return {"status": "sent"}


@router.post("/projects/{project_id}/terminal/{session_id}/resize")
async def terminal_resize(project_id: str, session_id: str, body: TerminalResize, service: Projects, manager: Terminals) -> dict[str, str]:
    service.get(project_id)
    session = manager.get(project_id, session_id)
    if not session.closed:
        await asyncio.to_thread(session.process.setwinsize, body.rows, body.cols)
    return {"status": "resized"}


@router.post("/projects/{project_id}/terminal/{session_id}/close")
async def terminal_close(project_id: str, session_id: str, service: Projects, manager: Terminals) -> dict[str, str]:
    service.get(project_id)
    await manager.close(manager.get(project_id, session_id))
    return {"status": "closed"}


@router.post("/projects/{project_id}/commands")
async def run_command(project_id: str, body: CommandRequest, service: Projects) -> dict[str, Any]:
    from pathlib import Path

    from app.execution.commands import CommandRunner
    project = service.get(project_id)
    result = await CommandRunner(Path(project.path), output_limit=service.settings.execution_output_bytes).run(
        body.argv, body.timeout, approved=body.approved)
    return {"argv": body.argv, "exit_code": result.exit_code, "stdout": result.stdout,
            "stderr": result.stderr, "timed_out": result.timed_out, "evidence": "VERIFIED"}
