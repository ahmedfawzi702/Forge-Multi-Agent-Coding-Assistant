"""Per-run, role-scoped tools. Agent edits and commands use a disposable snapshot."""
import asyncio
import copy
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings
from app.execution.commands import CommandRunner
from app.execution.file_io import atomic_write, text_hash
from app.execution.local import LocalExecutionEnvironment
from app.graph.inspection import inspection_snapshot
from app.graph.runtime import current_runtime
from app.llm.base import CompletionRequest, LLMProvider, ProviderError
from app.schemas.domain import ContextChunk, EditorDraft, Evidence, ProjectView
from app.schemas.engineering import CodeProposal, ImplementationProposal, ProposedFile
from app.security.command_guard import CommandGuard
from app.security.paths import safe_target
from app.security.policy import SafetyViolation
from app.security.redaction import redact_secrets
from app.services.git import GitService
from app.services.hooks import HookService
from app.services.preferences import CapabilityRequired, PermissionPolicy
from app.services.rules import RulesLoader
from app.services.selection import verify_selection


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Empty(Arguments):
    pass


class PathArgs(Arguments):
    path: str = Field(min_length=1, max_length=1024)


class DirectoryArgs(Arguments):
    path: str = Field(default=".", max_length=1024)


class ReadArgs(PathArgs):
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class WriteArgs(PathArgs):
    content: str = Field(max_length=262144)
    reason: str = Field(min_length=1, max_length=2000)


class PatchArgs(PathArgs):
    search: str = Field(min_length=1, max_length=30000)
    replace: str = Field(max_length=60000)
    reason: str = Field(min_length=1, max_length=2000)


class MoveArgs(PathArgs):
    destination: str = Field(min_length=1, max_length=1024)
    reason: str = Field(min_length=1, max_length=2000)


class SearchArgs(Arguments):
    query: str = Field(min_length=1, max_length=500)
    include: str = Field(default="", max_length=200)


class CommandArgs(Arguments):
    argv: list[str] = Field(min_length=1, max_length=60)
    timeout: int = Field(default=60, ge=1, le=180)


class DelegateArgs(Arguments):
    role: Literal["repository", "architecture", "tests"]
    task: str = Field(min_length=1, max_length=4000)


class ImplementationArgs(Arguments):
    summary: str = Field(min_length=1, max_length=4000)
    completed_steps: list[str] = Field(default_factory=list, max_length=64)
    pending_steps: list[str] = Field(default_factory=list, max_length=64)


READ_TOOLS: dict[str, tuple[type[Arguments], str]] = {
    "get_tree": (Empty, "List indexed workspace files and folders, including an empty project."),
    "list_directory": (DirectoryArgs, "List the immediate children of a workspace folder."),
    "read_file": (PathArgs, "Read a complete bounded UTF-8 file. Inspect existing files before editing."),
    "file_exists": (PathArgs, "Check whether a path exists in the staged workspace."),
    "get_file_metadata": (PathArgs, "Inspect a staged path's type, size and content hash."),
    "read_range": (ReadArgs, "Read numbered lines of a file. Partial reads do not authorize whole-file replacement."),
    "search_files": (SearchArgs, "Find workspace paths by substring; optional include glob."),
    "search_text": (SearchArgs, "Bounded task-local text search; use an include glob to narrow scope. Reports coverage and matching lines."),
    "search_symbols": (SearchArgs, "Search parsed repository symbols and their source locations."),
    "load_rules": (Empty, "Read applicable AGENTS.md, FORGE.md and .forge/rules/*.md instructions."),
    "git_status": (Empty, "Inspect current Git working tree status."),
    "git_diff": (Empty, "Read current staged and unstaged Git changes, filtered by agent file policy."),
}
EDIT_TOOLS: dict[str, tuple[type[Arguments], str]] = {
    "complete_implementation": (ImplementationArgs, "Explicitly finish the entire requested implementation. Call only when all required source and tests are staged and no work remains. This enables final gates; it does not claim tests passed."),
    "checkpoint_implementation": (ImplementationArgs, "Save completed implementation subtasks and pending work. Continue missing work without regenerating staged files; this does not enable final gates."),
    "create_file": (WriteArgs, "Create a new file in the staged workspace; never overwrites an existing file."),
    "write_file": (WriteArgs, "Write a complete staged file after reading all existing source."),
    "apply_patch": (PatchArgs, "Replace a unique, previously inspected exact block in a staged file."),
    "create_directory": (PathArgs, "Create a real empty directory in the staged workspace."),
    "delete": (PathArgs, "Propose deleting one fully inspected file; directories are not recursively deleted."),
    "move": (MoveArgs, "Propose moving or renaming one fully inspected file without overwriting another."),
    "rename_file": (MoveArgs, "Propose renaming a fully inspected file without overwriting another."),
    "move_file": (MoveArgs, "Propose moving a fully inspected file without overwriting another."),
    "delete_file": (PathArgs, "Propose deleting a fully inspected file."),
    "run_command": (CommandArgs, "Run a guarded development command in the staged workspace with explicit execution permission."),
    "delegate_analysis": (DelegateArgs, "Ask an isolated read-only repository, architecture or test specialist for evidence. Cannot approve code."),
}
SEARCH_TOOLS = {"search_text", "search_files", "search_symbols"}
CONTROL_TOOLS = {"complete_implementation", "checkpoint_implementation"}
WRITE_TOOLS = set(EDIT_TOOLS) - {"run_command", "delegate_analysis", *CONTROL_TOOLS}


class ToolRegistry:
    def __init__(self, project: ProjectView, settings: Settings, policy: PermissionPolicy,
                 context: list[ContextChunk], *, role: str = "explainer", provider: LLMProvider | None = None,
                 emit: Callable[[dict[str, Any]], None] | None = None, boundary: Callable[[], None] | None = None,
                 on_change: Callable[[], Awaitable[None]] | None = None):
        self.project, self.settings, self.policy = project, settings, policy
        self.root = Path(project.path)
        self.source = LocalExecutionEnvironment(self.root, settings.max_file_bytes)
        self.role, self.provider, self.emit = role, provider, emit or (lambda value: None)
        self.boundary = boundary or (lambda: None)
        self.on_change, self.runtime = on_change, current_runtime.get()
        self.specs = {**READ_TOOLS, **(EDIT_TOOLS if role == "coder" else {})}
        self.context = list(context)
        self.stage: Path | None = None
        self.reads: dict[str, str] = {}
        self.reasons: dict[str, str] = {}
        self.deleted: set[str] = set()
        self.directories: set[str] = set()
        self.calls = 0
        self.read_chars = 0
        self.delegations = 0
        self.phase = "OPEN"
        self.context_calls = 0
        self.context_reads = len({chunk.evidence.file for chunk in context})
        self.context_searches = 0
        self.revision = 0
        self.cache: dict[str, tuple[Any, dict[str, Any]]] = {}
        self.duplicates: dict[str, int] = {}
        self.force_progress = False
        self.baseline: dict[str, str] = {}
        self._ignore_stamp: Any = None
        self.content_cache: dict[str, tuple[Any, str]] = {}
        self.implementation_complete = False
        self.has_edits = False
        self.completed_steps: list[str] = []
        self.pending_steps: list[str] = []
        self.selection_guard: tuple[str, tuple[str, str]] | None = None
        for chunk in context:
            self.reads[chunk.evidence.file] = self.reads.get(chunk.evidence.file, "") + "\n" + "\n".join(line.partition(": ")[2] for line in chunk.content.splitlines())

    def definitions(self) -> list[dict[str, Any]]:
        allowed = set(self.specs)
        if self.phase == "CONTEXT":
            allowed &= READ_TOOLS.keys()
        elif self.phase == "IMPLEMENT":
            allowed &= WRITE_TOOLS | CONTROL_TOOLS | {"read_file", "read_range"}
            if self.force_progress:
                allowed &= WRITE_TOOLS | CONTROL_TOOLS
        return [{"type": "function", "function": {"name": name, "description": description,
                "parameters": schema.model_json_schema()}} for name, (schema, description) in self.specs.items() if name in allowed]

    async def snapshot(self) -> Path:
        if self.stage is None:
            self.stage = await asyncio.to_thread(inspection_snapshot, self.root, self.project.project_map, self.settings, self.baseline)
        return self.stage

    async def seed_drafts(self, drafts: list[EditorDraft]) -> None:
        for draft in drafts:
            path = self.check_path(draft.file)
            self.read(path)
            if text_hash(self.source.read_file(path)) != draft.base_hash:
                raise SafetyViolation("An editor draft is based on stale disk content; reload or save it before starting this task")
            atomic_write(safe_target(await self.snapshot(), path), draft.content)
            self.reads[path] = draft.content
            if self.role == "coder":
                self.reasons[path] = "Include the user's unsaved editor draft in the validated implementation"

    async def seed_previous(self, patches: list[dict[str, Any]]) -> None:
        if not patches:
            return
        stage = await self.snapshot()
        for patch in patches:
            path = self.check_path(patch["path"])
            if (self.root / path).is_file():
                self.read(path)
            target = safe_target(stage, path)
            if patch.get("directory"):
                target.mkdir(parents=True, exist_ok=True)
                self.directories.add(path)
            elif patch.get("delete"):
                target.unlink(missing_ok=True)
                self.deleted.add(path)
                self.reasons[path] = patch["reason"]
            else:
                atomic_write(target, patch["after"])
                self.reasons[path] = patch["reason"]

    def paths(self) -> list[str]:
        return sorted(p for p in ({f.path for f in self.project.project_map.files} | self.reasons.keys()) - self.deleted
            if not self.source.ignore.match_file(p))

    def check_path(self, path: str) -> str:
        path = path.replace("\\", "/")
        safe_target(self.root, path)
        if self.source.ignore.match_file(path):
            raise SafetyViolation("Path is excluded by the agent ignore policy")
        return path

    def read(self, path: str, start: int = 1, end: int | None = None) -> dict[str, Any]:
        self.policy.require("filesystem.read")
        path = self.check_path(path)
        if path in self.deleted:
            raise SafetyViolation("File is deleted in the staged proposal")
        original = self.source.read_file(path) if (self.root / path).exists() else None
        content = (original if self.stage is None and original is not None else
            LocalExecutionEnvironment(self.stage or self.root, self.settings.max_file_bytes).read_file(path))
        self.content_cache[path] = (self.stamp("read_file", {"path": path}), content)
        lines = content.splitlines()
        last = min(end or max(1, len(lines)), max(1, len(lines)))
        if start > last:
            raise SafetyViolation("Line range is outside the file")
        excerpt = "\n".join(f"{i}: {line}" for i, line in enumerate(lines[start - 1:last], start))
        if self.read_chars + len(excerpt) > 100000:
            raise SafetyViolation("Per-run source inspection budget reached; narrow or split the task")
        self.read_chars += len(excerpt)
        if start == 1 and last >= len(lines):
            self.reads[path] = content
            if original is not None:
                self.context = [chunk for chunk in self.context if chunk.evidence.file != path]
                self.context.append(ContextChunk(evidence=Evidence(file=path, start_line=1,
                    end_line=max(1, len(original.splitlines())), sha256=text_hash(original)),
                    content="\n".join(f"{i}: {line}" for i, line in enumerate(original.splitlines(), 1)),
                    total_lines=max(1, len(original.splitlines()))))
        else:
            self.reads[path] = self.reads.get(path, "") + "\n" + "\n".join(lines[start - 1:last])
        evidence = Evidence(file=path, start_line=start, end_line=last, sha256=text_hash(content))
        self.emit({"agent": self.role, "message": f"Inspected {path}:{start}–{last}", "type": "file_inspected", "evidence": evidence.model_dump()})
        return {"path": path, "content": redact_secrets(excerpt), "sha256": text_hash(content), "total_lines": len(lines),
            "applicable_rules": RulesLoader(self.root).load([path]), "evidence": "VERIFIED"}

    def inspected(self, path: str, content: str, *, whole: bool = True) -> None:
        seen = self.reads.get(path, "")
        if content and (content.replace("\r\n", "\n").strip() != seen.replace("\r\n", "\n").strip() if whole else content not in seen):
            raise SafetyViolation("Read the complete file before replacing/deleting it, or inspect the exact patch block")

    def stamp(self, name: str, args: dict[str, Any]) -> Any:
        def stat(path: Path) -> tuple[int, int, int] | None:
            try:
                info = path.stat()
                return info.st_mtime_ns, info.st_ctime_ns, info.st_size
            except OSError:
                return None
        policy_files = (stat(self.root / ".forgeignore"), stat(self.root / ".gitignore"))
        if self._ignore_stamp is not None and self._ignore_stamp != policy_files:
            self.source = LocalExecutionEnvironment(self.root, self.settings.max_file_bytes)
            self.cache.clear()
            self.content_cache.clear()
        self._ignore_stamp = policy_files
        if "path" in args and name in {"read_file", "read_range"}:
            path = self.check_path(args["path"])
            return self.revision, policy_files, stat((self.stage or self.root) / path)
        return self.revision, policy_files, tuple((path, stat((self.stage or self.root) / path)) for path in self.paths())

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.boundary()
        self.calls += 1
        if self.runtime:
            self.runtime.tool_requests += 1
            self.runtime.last_tool = name
        if name not in self.specs:
            if self.runtime:
                self.runtime.step()
                self.runtime.blocked_calls += 1
            return {"status": "blocked", "message": "Tool is unavailable to this specialist", "evidence": "VERIFIED"}
        try:
            args = self.specs[name][0].model_validate(arguments).model_dump()
            if name in READ_TOOLS:
                self.policy.require("filesystem.read")
                if name.startswith("git_"):
                    self.policy.require("git.read")
                key = name + json.dumps(args, sort_keys=True, ensure_ascii=False)
                stamp = self.stamp(name, args)
                cached = self.cache.get(key)
                if cached and cached[0] == stamp:
                    self.duplicates[key] = self.duplicates.get(key, 1) + 1
                    repeated = self.duplicates[key] >= 3
                    self.force_progress |= repeated
                    if self.runtime:
                        self.runtime.step()
                        self.runtime.cache_hits += 1
                        self.runtime.repeated_calls += int(repeated)
                    result = {**copy.deepcopy(cached[1]), "cached": True}
                    if repeated:
                        result.update({"signal": "REPEATED_TOOL_CALL", "next_action": "Context already inspected. Implement now or answer using the existing evidence."})
                    self.emit({"agent": self.role, "type": "tool_cached", "tool": name, "message": "REPEATED_TOOL_CALL: advancing workflow" if repeated else f"Reused {name} result"})
                    return result
                if (self.context_calls >= self.settings.forge_max_context_calls
                    or name in SEARCH_TOOLS and self.context_searches >= self.settings.forge_max_context_searches
                    or name in {"read_file", "read_range"} and self.context_reads >= self.settings.forge_max_context_file_reads
                    or self.phase == "IMPLEMENT" and (name not in {"read_file", "read_range"} or self.force_progress)):
                    self.force_progress = True
                    if self.runtime and "CONTEXT_BUDGET" not in self.runtime.budget_events:
                        self.runtime.budget_events.append("CONTEXT_BUDGET")
                    if self.runtime:
                        self.runtime.step()
                        self.runtime.blocked_calls += 1
                    return {"status": "stage_complete", "signal": "IMPLEMENT_NOW", "context_sufficient": True,
                        "reason": "CONTEXT_BUDGET",
                        "message": "Context budget reached. Reuse inspected source; proceed to implementation or the final answer."}
                self.context_calls += 1
                self.context_reads += int(name in {"read_file", "read_range"})
                self.context_searches += int(name in SEARCH_TOOLS)
            if self.runtime:
                category = "search" if name in SEARCH_TOOLS else "read" if name in READ_TOOLS else "execute" if name == "run_command" else "write" if name in WRITE_TOOLS else "control"
                self.runtime.tool(name, category)
            hooks = HookService(self.settings)
            has_before = any(hook.event == "BeforeToolExecution" for hook in hooks.configuration(self.project))
            before_hooks = await hooks.enforce(self.project, "BeforeToolExecution", policy=self.policy, workspace=await self.snapshot()) if has_before else []
            for report in before_hooks:
                self.emit({"agent": self.role, "message": "Before-tool hook verified", "type": "hook_completed", "artifact": {"type": "hook", "title": report["hook"]["name"], "status": report["status"], "data": report}})
            self.emit({"agent": self.role, "message": f"Using {name}", "type": "tool_started", "tool": name})
            result = await self.dispatch(name, args)
            if name in READ_TOOLS:
                self.cache[key] = (stamp, copy.deepcopy(result))
                self.duplicates[key] = 1
            if name in WRITE_TOOLS:
                self.revision += 1
                self.has_edits = True
                self.cache.clear()
                self.content_cache.clear()
                if self.on_change:
                    await self.on_change()
            if name in {"create_file", "write_file", "apply_patch", "move", "delete", "rename_file", "move_file", "delete_file"}:
                await hooks.enforce(self.project, "AfterFileEdit", policy=self.policy, workspace=self.stage)
            after_hooks = await hooks.enforce(self.project, "AfterToolExecution", policy=self.policy, workspace=self.stage)
            for report in after_hooks:
                self.emit({"agent": self.role, "message": "After-tool hook verified", "type": "hook_completed", "artifact": {"type": "hook", "title": report["hook"]["name"], "status": report["status"], "data": report}})
            self.emit({"agent": self.role, "message": f"{name} completed", "type": "tool_completed", "tool": name,
                "status": result.get("status", "completed"), "exit_code": result.get("exit_code")})
            return result
        except CapabilityRequired:
            raise
        except (SafetyViolation, OSError, ValueError, ValidationError) as error:
            if self.runtime:
                self.runtime.blocked_calls += 1
            message = str(error)[:1000] if isinstance(error, SafetyViolation) else "Invalid tool input or unavailable workspace file"
            self.emit({"agent": self.role, "message": message, "type": "tool_blocked", "tool": name})
            return {"status": "blocked", "message": message, "evidence": "VERIFIED"}

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        name = {"rename_file": "move", "move_file": "move", "delete_file": "delete"}.get(name, name)
        if name in CONTROL_TOOLS:
            self.policy.require("filesystem.write")
            if not (self.reasons or self.directories):
                raise SafetyViolation("Stage the requested implementation before completing or checkpointing it")
            self.completed_steps, self.pending_steps = args["completed_steps"], args["pending_steps"]
            if name == "complete_implementation":
                if self.pending_steps:
                    raise SafetyViolation("Implementation still has pending subtasks; checkpoint and continue them first")
                self.implementation_complete = True
                return {"status": "implementation_complete", "summary": args["summary"]}
            if self.on_change:
                await self.on_change()
            return {"status": "checkpoint_preserved", "completed_steps": self.completed_steps, "pending_steps": self.pending_steps}
        if name in READ_TOOLS:
            self.policy.require("filesystem.read")
        if name == "read_file":
            return self.read(args["path"])
        if name in {"file_exists", "get_file_metadata"}:
            path = self.check_path(args["path"])
            target = safe_target(self.stage or self.root, path)
            exists = target.exists() and path not in self.deleted
            return {"path": path, "exists": exists, "kind": "directory" if exists and target.is_dir() else "file" if exists else None,
                "size": target.stat().st_size if exists else None,
                "sha256": text_hash(LocalExecutionEnvironment(self.stage or self.root, self.settings.max_file_bytes).read_file(path)) if exists and target.is_file() else None,
                "workspace": "staged" if self.stage else "source", "evidence": "VERIFIED"}
        if name == "read_range":
            return self.read(args["path"], args["start_line"], args["end_line"])
        if name in {"get_tree", "list_directory"}:
            prefix = "" if args.get("path", ".") == "." else self.check_path(args["path"]).rstrip("/") + "/"
            paths = [p for p in [*self.paths(), *self.project.project_map.directories, *self.directories] if p.startswith(prefix)]
            return {"paths": sorted(set(prefix + p[len(prefix):].split("/")[0] if name == "list_directory" else p for p in paths))[:3000], "evidence": "VERIFIED"}
        if name in {"search_files", "search_text", "search_symbols"}:
            import fnmatch
            query = args["query"].casefold()
            paths = [p for p in self.paths() if not args["include"] or fnmatch.fnmatchcase(p, args["include"])]
            if name == "search_files":
                return {"paths": [p for p in paths if query in p.casefold()][:100], "evidence": "VERIFIED"}
            if name == "search_symbols":
                return {"symbols": [s.model_dump() for s in self.project.project_map.symbols if s.file_path in paths and query in s.name.casefold()][:100], "evidence": "VERIFIED"}
            matches = []
            paths.sort(key=lambda path: (-(10 * (query in path.casefold()) + sum(query in s.name.casefold() for s in self.project.project_map.symbols if s.file_path == path)), path))
            searched = []
            for path in paths[:self.settings.forge_max_context_file_reads]:
                stamp = self.stamp("read_file", {"path": path})
                cached_content = self.content_cache.get(path)
                if cached_content and cached_content[0] == stamp:
                    content = cached_content[1]
                else:
                    if self.context_reads >= self.settings.forge_max_context_file_reads:
                        break
                    content = LocalExecutionEnvironment(self.stage or self.root, self.settings.max_file_bytes).read_file(path)
                    self.content_cache[path] = (stamp, content)
                    self.context_reads += 1
                    if self.runtime:
                        self.runtime.read_calls += 1
                searched.append(path)
                for line, text in enumerate(content.splitlines(), 1):
                    if query in text.casefold():
                        matches.append({"file": path, "line": line, "text": redact_secrets(text[:500])})
                    if len(matches) >= 100:
                        return {"matches": matches, "searched_files": searched, "truncated": True, "evidence": "VERIFIED"}
            return {"matches": matches, "searched_files": searched, "truncated": len(searched) < len(paths), "evidence": "VERIFIED"}
        if name == "load_rules":
            return {"rules": RulesLoader(self.root).load(self.paths()), "evidence": "VERIFIED"}
        if name in {"git_diff", "git_status"}:
            self.policy.require("git.read")
            return await (GitService(self.settings).agent_diff(self.project) if name == "git_diff" else GitService(self.settings).status(self.project))
        if name == "delegate_analysis":
            self.policy.require("subagent")
            if self.provider is None or self.delegations >= self.settings.forge_max_delegations:
                raise SafetyViolation(f"The {self.settings.forge_max_delegations}-specialist delegation budget has been reached")
            self.delegations += 1
            delegate = ToolRegistry(self.project, self.settings, self.policy, self.context,
                role=args["role"], provider=None, emit=self.emit, boundary=self.boundary)
            findings = await run_tool_loop(self.provider, delegate, args["task"],
                "You are an independent read-only specialist. Inspect source, report findings with file locations, distinguish inference from verification. Do not approve changes.", max_rounds=self.settings.forge_subagent_rounds)
            return {"role": args["role"], "findings": findings, "evidence": "INFERRED"}
        if name == "run_command":
            self.policy.require("terminal.execute")
            if args["argv"][0].lower() == "git":
                raise SafetyViolation("Use git_status/git_diff for filtered inspection and the human Git panel for index/commit operations")
            decision = CommandGuard().development(args["argv"])
            if decision.blocked:
                raise SafetyViolation(decision.reason)
            if decision.requires_user_approval:
                self.policy.require("package.install")
                self.policy.require("network")
            stage = await self.snapshot()
            environment = LocalExecutionEnvironment(stage, self.settings.max_file_bytes)
            originals = {path: environment.read_file(path) for path in self.paths()}
            result = await CommandRunner(stage).run(args["argv"], args["timeout"], approved=True)
            for path, content in originals.items():
                try:
                    unchanged = environment.read_file(path) == content
                except (OSError, SafetyViolation):
                    unchanged = False
                if not unchanged:
                    atomic_write(safe_target(stage, path), content)
                    raise SafetyViolation("Command changed source outside editing tools; source restored and verification rejected")
            report = {"exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr,
                "timed_out": result.timed_out, "workspace": "staged", "evidence": "VERIFIED", "command": args["argv"]}
            self.emit({"agent": self.role, "message": f"Command exited {result.exit_code}", "type": "command_completed",
                "artifact": {"type": "command", "title": "Staged workspace command", "status": "passed" if result.exit_code == 0 and not result.timed_out else "failed", "data": report}})
            return report
        self.policy.require("filesystem.write")
        path = self.check_path(args["path"])
        stage = await self.snapshot()
        target = safe_target(stage, path)
        if name == "create_directory":
            target.mkdir(parents=True, exist_ok=True)
            self.directories.add(path)
            return {"status": "staged", "path": path, "evidence": "VERIFIED"}
        exists = target.exists() and path not in self.deleted
        before = LocalExecutionEnvironment(stage, self.settings.max_file_bytes).read_file(path) if exists else ""
        if name == "create_file" and exists:
            raise SafetyViolation("File exists; inspect it and use write_file or apply_patch")
        if name in {"move", "delete"}:
            if self.selection_guard and self.selection_guard[0] == path:
                raise SafetyViolation("A selected-code task cannot delete or move the selected file")
            if not exists:
                raise SafetyViolation("File does not exist")
            self.inspected(path, before)
            if name == "move":
                destination = self.check_path(args["destination"])
                if safe_target(stage, destination).exists():
                    raise SafetyViolation("Move destination exists")
                atomic_write(safe_target(stage, destination), before)
                self.reasons[destination] = args["reason"]
            target.unlink()
            self.deleted.add(path)
            self.reasons[path] = args.get("reason", "Delete inspected file")
            if not (self.root / path).exists():
                self.reasons.pop(path, None)
        else:
            if name == "apply_patch":
                self.inspected(path, args["search"], whole=False)
                if before.count(args["search"]) != 1:
                    raise SafetyViolation("Patch must match a unique exact source block")
                after = before.replace(args["search"], args["replace"], 1)
                # Preserve original complete source as evidence for final staging.
                if path not in self.reasons:
                    self.read(path)
            else:
                self.inspected(path, before)
                after = args["content"]
            if len(after.encode()) > self.settings.max_file_bytes or "\x00" in after:
                raise SafetyViolation("Only bounded UTF-8 text edits are supported")
            if self.selection_guard and self.selection_guard[0] == path:
                verify_selection(after, self.selection_guard[1])
            atomic_write(target, after)
            if LocalExecutionEnvironment(stage, self.settings.max_file_bytes).read_file(path) != after:
                raise SafetyViolation("Staged write verification failed")
            self.reasons[path] = args["reason"]
            self.deleted.discard(path)
            self.reads[path] = after
        return {"status": "staged", "path": path, "evidence": "VERIFIED"}

    def proposal(self, summary: str) -> CodeProposal:
        files = [ProposedFile(path=path, content=None if path in self.deleted else
            LocalExecutionEnvironment(self.stage or self.root, self.settings.max_file_bytes).read_file(path),
            delete=path in self.deleted, reason=reason) for path, reason in self.reasons.items()]
        if not files and not self.directories:
            raise ProviderError("The implementation stage produced no file changes. Its source context and plan are preserved for continuation.")
        return CodeProposal(summary=summary[:4000], files=files, directories=sorted(self.directories))

    async def submit_proposal(self, proposal: CodeProposal) -> None:
        """A single structured implementation submission uses the same real edit tools."""
        for item in proposal.files:
            args: dict[str, Any]
            if item.delete:
                name, args = "delete", {"path": item.path}
            elif item.search is not None and item.replace is not None:
                name, args = "apply_patch", {"path": item.path, "search": item.search, "replace": item.replace, "reason": item.reason}
            else:
                name = "write_file" if safe_target(self.stage or self.root, item.path).exists() else "create_file"
                args = {"path": item.path, "content": item.content, "reason": item.reason}
            result = await self.execute(name, args)
            if result.get("status") != "staged":
                raise SafetyViolation(f"{item.path}: {result.get('message', 'Edit could not be staged')}")
        for directory in proposal.directories:
            result = await self.execute("create_directory", {"path": directory})
            if result.get("status") != "staged":
                raise SafetyViolation(str(result.get("message", "Directory could not be staged")))
        self.pending_steps = proposal.pending_steps
        self.implementation_complete = proposal.implementation_complete and not proposal.pending_steps


async def run_tool_loop(provider: LLMProvider, registry: ToolRegistry, task: str, system: str,
                        *, max_rounds: int | None = None, require_edit: bool = False) -> str:
    from app.agents.structured import structured_completion
    from app.graph.task_profile import TaskProfile
    profile = TaskProfile.classify(task, registry.project.project_map)
    request = CompletionRequest(system=system, message=task, context=registry.context,
        project_map=registry.project.project_map, level="advanced", role=registry.role)
    turns: list[dict[str, Any]] = []
    coding = registry.role == "coder"
    registry.phase = "IMPLEMENT" if coding and (registry.context or profile.empty_workspace or profile.standalone_create or registry.reasons) else "CONTEXT"
    rounds = max_rounds or (registry.settings.forge_implementation_rounds if coding else registry.settings.forge_readonly_rounds)
    if registry.runtime:
        registry.runtime.transition(registry.phase, registry.role)
    no_progress = 0
    initial_revision = registry.revision
    def has_implementation() -> bool:
        return bool(registry.reasons or registry.directories) and (not require_edit or registry.revision > initial_revision)

    async def implement_now() -> str:
        registry.phase = "IMPLEMENT"
        if registry.runtime:
            registry.runtime.transition("IMPLEMENT", registry.role)
        registry.emit({"agent": registry.role, "type": "stage_transition", "message": "IMPLEMENT_NOW: submitting a concrete patch from the inspected context"})
        registry.emit({"agent": "coder", "type": "edit_recovery", "message": "No executable edit received; requesting one schema-validated implementation submission"})
        try:
            proposal = await structured_completion(provider, "coder.md", task +
                "\nImplementation is required now. Repository inspection is finished. Submit concrete files or exact inspected-block replacements, with tests when requested. An empty files list is invalid. Do not request more searches or ask the user to paste source.",
                registry.context, registry.project.project_map, ImplementationProposal, attempts=1)
        except ProviderError as error:
            if error.reason in {"PROVIDER_RATE_LIMIT", "PROVIDER_UNAVAILABLE", "PROVIDER_AUTH", "PROVIDER_CREDITS", "PROVIDER_CONFIGURATION"}:
                raise
            raise ProviderError("No executable editing action was returned after one structured recovery. Expected concrete files with content or exact search/replace patches. Existing progress is preserved.",
                reason="MODEL_OUTPUT_INCOMPLETE", retryable=True) from error
        revision_before = registry.revision
        await registry.submit_proposal(proposal)
        if registry.revision == revision_before:
            raise ProviderError("The model submitted no new edits for the required implementation or repair. The working files, feedback and plan are preserved; resume to retry this stage.")
        if not registry.implementation_complete:
            from app.graph.runtime import RuntimeStopped
            raise RuntimeStopped("Implementation checkpoint saved with pending work", "IMPLEMENTATION_CHECKPOINT")
        return proposal.summary

    for round_index in range(rounds):
        registry.boundary()
        if coding and registry.phase == "CONTEXT" and (round_index >= registry.settings.forge_context_rounds or registry.force_progress):
            registry.phase = "IMPLEMENT"
            if registry.runtime:
                registry.runtime.transition("IMPLEMENT", registry.role)
            request = CompletionRequest(system=system + "\nCONTEXT IS SUFFICIENT. Implement now. Validation/tests are handled by the next workflow stage.",
                message=task, context=registry.context, project_map=registry.project.project_map, level="advanced", role=registry.role)
            no_progress = 0
        if coding and registry.phase == "IMPLEMENT" and no_progress >= 2:
            if has_implementation():
                from app.graph.runtime import RuntimeStopped
                raise RuntimeStopped("Implementation has not been declared complete; staged work is preserved", "MODEL_CALL_LIMIT")
            return await implement_now()
        reply = await provider.respond(request, registry.definitions(), turns)
        registry.boundary()
        registry.emit({"agent": registry.role, "message": "Model response received", "type": "model_usage",
            "usage": reply.usage, "model": reply.model, "finish_reason": reply.finish_reason})
        if not reply.tool_calls:
            if coding and not has_implementation():
                return await implement_now()
            if coding:
                turns.append({"role": "assistant", "content": reply.content})
                turns.append({"role": "user", "content": "If all implementation subtasks are complete, call complete_implementation now. Otherwise continue editing the missing work or save an implementation checkpoint. A prose summary does not enable final gates."})
                no_progress += 1
                continue
            return reply.content
        turns.append({"role": "assistant", "content": None, "tool_calls": [call.wire() for call in reply.tool_calls]})
        revision_before_round = registry.revision
        for call in reply.tool_calls:
            result: dict[str, Any]
            if coding and call.name == "run_command":
                registry.force_progress = True
                result = {"status": "stage_complete", "signal": "IMPLEMENT_NOW", "message": "Finish the implementation with complete_implementation first. Tests run in the next stage."}
            else:
                result = await registry.execute(call.name, call.arguments)
            if result.get("status") == "implementation_complete":
                if require_edit and registry.revision == initial_revision:
                    registry.implementation_complete = False
                    return await implement_now()
                return str(result["summary"])
            if coding and profile.standalone_create and registry.revision > initial_revision and registry.reasons:
                registry.implementation_complete = True
                return "Created the requested standalone file in the working ChangeSet."
            result["model_rounds_remaining"] = rounds - round_index - 1
            result["current_stage"] = registry.phase
            if registry.force_progress:
                result["next_action"] = "Implement now using the supplied evidence."
            def safe_value(value: Any) -> Any:
                if isinstance(value, str):
                    return redact_secrets(value)
                if isinstance(value, dict):
                    return {key: safe_value(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [safe_value(item) for item in value]
                return value
            safe_result = safe_value(result)
            encoded = json.dumps(safe_result, ensure_ascii=False)
            if len(encoded) > 32000:
                encoded = json.dumps({"truncated": True, "status": result.get("status"), "path": result.get("path"),
                    "content": str(safe_result.get("content", safe_result))[:28000], "message": "Output truncated; request a distinct bounded range if needed."})
            turns.append({"role": "tool", "tool_call_id": call.id, "name": call.name,
                "content": encoded})
        if coding and registry.phase == "IMPLEMENT":
            no_progress = 0 if registry.revision > revision_before_round else no_progress + 1
    if registry.role == "coder" and has_implementation():
        from app.graph.runtime import RuntimeStopped
        raise RuntimeStopped("Implementation model-round allowance reached; final gates have not run", "MODEL_CALL_LIMIT")
    if coding:
        return await implement_now()
    # A read specialist has no reason to loop after its inspection allowance. It
    # must now answer from observed evidence, with no more tool definitions.
    return await provider.complete(CompletionRequest(system=system + "\nInspection is complete. Return your final evidence-based answer now. State missing evidence explicitly; do not request more tools.",
        message=task, context=registry.context, project_map=registry.project.project_map, level="advanced", role=registry.role,
        auxiliary_context="Bounded inspection results:\n" + json.dumps([turn for turn in turns if turn["role"] == "tool"], ensure_ascii=False)[-30000:]))
