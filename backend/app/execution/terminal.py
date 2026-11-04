import asyncio
import importlib
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.execution.commands import command_environment
from app.execution.local import LocalExecutionEnvironment
from app.security.policy import SafetyViolation


@dataclass
class TerminalSession:
    id: str
    project_id: str
    process: Any
    root: Path
    job: Any = None
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=128))
    sequence: int = 0
    closed: bool = False
    created: float = field(default_factory=time.monotonic)
    task: asyncio.Task[None] | None = None

    def emit(self, kind: str, data: str) -> None:
        self.sequence += 1
        self.events.append({"seq": self.sequence, "type": kind, "data": data})


class TerminalManager:
    """Human PTYs. Agents never receive input access to these sessions."""

    def __init__(self) -> None:
        self.sessions: dict[str, TerminalSession] = {}

    async def create(self, environment: LocalExecutionEnvironment, project_id: str, cols: int, rows: int) -> TerminalSession:
        if not environment.allow_execute:
            raise SafetyViolation("Opening a developer terminal requires explicit permission")
        if sum(not item.closed for item in self.sessions.values()) >= 8:
            raise SafetyViolation("Close an existing terminal before opening another")
        if os.name == "nt":
            implementation = importlib.import_module("winpty").PtyProcess
            executable = str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32/cmd.exe")
            argv = [executable, "/d"]
        else:
            implementation = importlib.import_module("ptyprocess").PtyProcessUnicode
            argv = ["/bin/bash", "--noprofile", "--norc"]
        process = await asyncio.to_thread(implementation.spawn, argv, cwd=str(environment.root),
            env=command_environment(manual=True), dimensions=(rows, cols))
        session = TerminalSession(str(uuid.uuid4()), project_id, process, environment.root)
        if os.name == "nt":
            from app.execution.windows_job import WindowsJob
            try:
                session.job = WindowsJob(process.pid)
            except OSError:
                await asyncio.to_thread(process.close, True)
                raise SafetyViolation("Could not establish terminal process-tree cleanup") from None
        self.sessions[session.id] = session
        session.task = asyncio.create_task(self._read(session))
        return session

    async def _read(self, session: TerminalSession) -> None:
        try:
            while not session.closed:
                remaining = max(0.1, 7200 - (time.monotonic() - session.created))
                data = await asyncio.wait_for(asyncio.to_thread(session.process.read, 4096), timeout=remaining)
                if data:
                    session.emit("output", str(data))
                if time.monotonic() - session.created > 7200:
                    session.emit("output", "\r\nTerminal reached its two-hour session limit.\r\n")
                    break
        except (EOFError, OSError, RuntimeError, TimeoutError):
            pass
        finally:
            session.closed = True
            session.emit("exit", "Terminal closed")
            if session.job:
                session.job.close()
            try:
                await asyncio.to_thread(session.process.close, True)
            except (OSError, RuntimeError):
                pass

    def get(self, project_id: str, session_id: str) -> TerminalSession:
        item = self.sessions.get(session_id)
        if item is None or item.project_id != project_id:
            raise SafetyViolation("Terminal does not belong to this workspace")
        return item

    async def write(self, session: TerminalSession, data: str) -> None:
        if session.closed:
            raise SafetyViolation("Terminal is closed")
        await asyncio.to_thread(session.process.write, data)

    async def close(self, session: TerminalSession) -> None:
        if session.job:
            session.job.close()
        session.closed = True
        try:
            await asyncio.to_thread(session.process.close, True)
        except (OSError, RuntimeError):
            pass
        if session.task:
            try:
                await asyncio.wait_for(asyncio.shield(session.task), timeout=2)
            except TimeoutError:
                session.task.cancel()

    async def shutdown(self) -> None:
        await asyncio.gather(*(self.close(item) for item in self.sessions.values()), return_exceptions=True)
