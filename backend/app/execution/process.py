import asyncio
import os
import signal
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Literal

from app.execution.base import ExecutionResult
from app.security.command_guard import CommandGuard
from app.security.paths import safe_target
from app.security.policy import SafetyViolation
from app.security.redaction import redact_secrets


class ValidationRunner:
    """Small trusted-tool runner. It is NOT an OS sandbox for project tests."""

    def __init__(self, root: Path, *, allow_tests: bool = False, output_limit: int = 65536):
        self.root = root.resolve(strict=True)
        self.allow_tests = allow_tests
        self.output_limit = output_limit

    async def run(self, tool: Literal["pytest", "ruff", "bandit"], targets: list[str] | None = None,
                  timeout: int = 60) -> ExecutionResult:
        if tool == "pytest":
            if not self.allow_tests:
                raise SafetyViolation("Local tests require explicit execution permission")
            targets = targets or []
            for target in targets:
                if not safe_target(self.root, target).is_file():
                    raise SafetyViolation("Test target must be an existing project file")
            argv = ["python", "-I", "-m", "pytest", "-q", "--maxfail=3", "-o", "pythonpath=.", *targets]
        elif tool == "ruff":
            argv = ["python", "-I", "-m", "ruff", "check", "--isolated", "--select", "E9,F63,F7,F82", "."]
        else:
            argv = ["python", "-I", "-m", "bandit", "-r", ".", "-f", "json", "-q"]
        decision = CommandGuard().inspect(argv, allow_tools=True)
        if decision.blocked:
            raise SafetyViolation(decision.reason)
        from app.graph.runtime import current_runtime
        runtime = current_runtime.get()
        if runtime:
            runtime.tool(tool, "test" if tool == "pytest" else "execute")
        system_root = os.environ.get("SystemRoot", "C:\\Windows")
        environment = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "TEMP", "TMP") if name in os.environ}
        environment.update({"PATH": str(Path(sys.executable).parent) + os.pathsep + str(Path(system_root) / "System32"),
                            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1"})
        # Only fixed isolated validation modules reach this subprocess call.
        process = await asyncio.create_subprocess_exec(
            sys.executable, *argv[1:], cwd=self.root, env=environment,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        job = None
        if os.name == "nt":
            from app.execution.windows_job import WindowsJob
            try:
                job = WindowsJob(process.pid)
            except OSError:
                process.kill()
                await process.wait()
                raise SafetyViolation("Validation could not establish process-tree containment") from None

        async def drain(stream: asyncio.StreamReader | None) -> str:
            captured = bytearray()
            if stream:
                while chunk := await stream.read(4096):
                    remaining = max(0, self.output_limit - len(captured))
                    captured.extend(chunk[:remaining])
            return redact_secrets(captured.decode("utf-8", errors="replace"))

        stdout = asyncio.create_task(drain(process.stdout))
        stderr = asyncio.create_task(drain(process.stderr))
        timed_out = False
        try:
            await asyncio.wait_for(process.wait(), timeout=min(max(timeout, 1), 180))
        except (TimeoutError, asyncio.CancelledError) as error:
            timed_out = isinstance(error, TimeoutError)
            if job is not None:
                job.close()
            await self._kill_tree(process)
            if not timed_out:
                await asyncio.gather(stdout, stderr, return_exceptions=True)
                raise
        finally:
            if job is not None:
                job.close()
            if process.returncode is None:
                await self._kill_tree(process)
        out, err = await asyncio.gather(stdout, stderr)
        return ExecutionResult(process.returncode if process.returncode is not None else -1,
                               out, err, timed_out)

    @staticmethod
    async def _kill_tree(process: asyncio.subprocess.Process) -> None:
        if os.name == "nt":
            if process.returncode is not None:
                return
            executable = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "taskkill.exe"
            killer = await asyncio.create_subprocess_exec(str(executable), "/PID", str(process.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await killer.wait()
        else:
            try:
                os.killpg(process.pid, getattr(signal, "SIGKILL", 9))  # type: ignore[attr-defined]
            except ProcessLookupError:
                pass
        await process.wait()
