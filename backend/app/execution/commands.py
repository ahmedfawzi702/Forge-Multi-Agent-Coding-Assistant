import asyncio
import os
import re
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path

from app.execution.base import ExecutionResult
from app.execution.process import ValidationRunner
from app.security.command_guard import CommandGuard
from app.security.policy import SafetyViolation
from app.security.redaction import redact_secrets


def command_environment(*, manual: bool = False) -> dict[str, str]:
    names = {name.lower() for name in ("SystemRoot", "SystemDrive", "WINDIR", "TEMP", "TMP", "PATH", "PATHEXT", "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "LANG", "PROGRAMDATA", "ALLUSERSPROFILE", "ProgramFiles", "ProgramFiles(x86)", "COMSPEC", "PSModulePath")}
    env = {key: value for key, value in os.environ.items() if (manual or key.lower() in names)
           and not re.search(r"(?:API_KEY|TOKEN|SECRET|PASSWORD)", key, re.I)}
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", os.defpath)
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "TERM": "xterm-256color",
                "NoDefaultCurrentDirectoryInExePath": "1"})
    if not manual:
        env.update({"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "NO_COLOR": "1"})
    return env


class CommandRunner:
    def __init__(self, root: Path, *, output_limit: int = 65536):
        self.root = root.resolve(strict=True)
        self.output_limit = output_limit

    async def run(self, argv: list[str], timeout: int = 60, *, approved: bool = False, trusted_git: bool = False,
                  input_text: str | None = None) -> ExecutionResult:
        if trusted_git:
            # Only GitService's fixed operations use this path. Commit messages and
            # literal filenames are data, not agent shell syntax.
            if not argv or argv[0] != "git" or any("\x00" in arg for arg in argv):
                raise SafetyViolation("Invalid internal Git command")
        else:
            decision = CommandGuard().development(argv)
            if decision.blocked or decision.requires_user_approval and not approved:
                raise SafetyViolation(decision.reason)
        env = command_environment()
        if trusted_git:
            env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "GIT_ASKPASS": "", "SSH_ASKPASS": ""})
        name = argv[0].lower()
        if name in {"python", "python3", "py"}:
            command = [sys.executable, *argv[1:]]
        elif name in {"pytest", "ruff", "mypy", "bandit", "pip"}:
            command = [sys.executable, "-m", name, *argv[1:]]
        else:
            executable = shutil.which(name, path=env["PATH"])
            if not executable:
                raise SafetyViolation(f"{name} is not installed or not available on PATH")
            command = [executable, *argv[1:]]
            if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
                powershell = str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")
                literal = "& " + " ".join("'" + arg.replace("'", "''") + "'" for arg in command)
                command = [powershell, "-NoProfile", "-NonInteractive", "-Command", literal]
        process = await asyncio.create_subprocess_exec(*command, cwd=self.root, env=env,
            stdin=asyncio.subprocess.PIPE if input_text is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0,
            start_new_session=os.name != "nt")
        job = None
        if os.name == "nt":
            from app.execution.windows_job import WindowsJob
            try:
                job = WindowsJob(process.pid)
            except OSError:
                process.kill()
                await process.wait()
                raise SafetyViolation("Could not establish process-tree cleanup") from None

        async def drain(stream: asyncio.StreamReader | None) -> str:
            data = bytearray()
            if stream:
                while chunk := await stream.read(4096):
                    data.extend(chunk[:max(0, self.output_limit - len(data))])
            return redact_secrets(data.decode("utf-8", errors="replace"))

        out, err = asyncio.create_task(drain(process.stdout)), asyncio.create_task(drain(process.stderr))
        async def feed() -> None:
            if process.stdin and input_text is not None:
                process.stdin.write(input_text.encode("utf-8"))
                try:
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                process.stdin.close()
        feeding = asyncio.create_task(feed())
        timed_out = False
        try:
            await asyncio.wait_for(process.wait(), timeout=min(max(timeout, 1), 300))
        except (TimeoutError, asyncio.CancelledError) as error:
            timed_out = isinstance(error, TimeoutError)
            if job:
                job.close()
            await ValidationRunner._kill_tree(process)
            if not timed_out:
                await asyncio.gather(out, err, return_exceptions=True)
                raise
        finally:
            feeding.cancel()
            await asyncio.gather(feeding, return_exceptions=True)
            if job:
                job.close()
            elif os.name != "nt":
                await ValidationRunner._kill_tree(process)
        stdout, stderr = await asyncio.gather(out, err)
        return ExecutionResult(process.returncode if process.returncode is not None else -1, stdout, stderr, timed_out)
