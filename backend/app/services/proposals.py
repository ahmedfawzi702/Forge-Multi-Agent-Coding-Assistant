import ast
import copy
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.code_intelligence.repository_scanner import LANGUAGES, TEXT_FILENAMES
from app.code_intelligence.tree_parser import syntax_tree
from app.config import Settings
from app.execution.file_io import workspace_lock
from app.execution.local import LocalExecutionEnvironment
from app.execution.process import ValidationRunner
from app.models.entities import AgentRun, ChangeSet, RunCheckpoint
from app.schemas.domain import ContextChunk, Evidence, ProjectView
from app.schemas.engineering import ApplyAction, CodeProposal
from app.security.paths import safe_target
from app.security.policy import SafetyViolation
from app.security.redaction import redact_secrets
from app.security.risk_classifier import RiskClassifier
from app.services.changes import proposed_diff
from app.services.checkpoints import CheckpointStore


def digest(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def inspected_text(context: list[ContextChunk], path: str) -> str:
    return "\n".join(line.partition(": ")[2] for chunk in context if chunk.evidence.file == path
                     for line in chunk.content.splitlines())


def stage_proposal(project: ProjectView, proposal: CodeProposal, context: list[ContextChunk],
                   settings: Settings, approved_draft: tuple[str, str] | None = None,
                   existing_stage: Path | None = None, existing_baseline: dict[str, str] | None = None) -> tuple[Path, list[dict[str, Any]], dict[str, str]]:
    root = Path(project.path)
    source = LocalExecutionEnvironment(root, settings.max_file_bytes)
    stage = existing_stage or settings.data_directory / "workspaces" / str(uuid.uuid4())
    if existing_stage and (stage.resolve().parent != (settings.data_directory / "workspaces").resolve() or not stage.is_dir()):
        raise SafetyViolation("Invalid working ChangeSet workspace")
    stage.mkdir(parents=True, exist_ok=True)
    total = 0
    baseline: dict[str, str] = dict(existing_baseline or {})
    # Copy only indexed text, never environment files, links, binaries or ignored files.
    for entry in ([] if existing_stage else project.project_map.files):
        content = source.read_file(entry.path)
        baseline[entry.path] = digest(content)
        total += len(content.encode())
        if total > 20 * 1024 * 1024:
            raise SafetyViolation("Validation snapshot exceeds 20 MB")
        target = safe_target(stage, entry.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
    patches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for proposed in proposal.files:
        path = proposed.path.replace("\\", "/")
        target = safe_target(root, path)
        safe_target(stage, path)
        if path.casefold() in seen or Path(path).suffix.lower() not in LANGUAGES and Path(path).name not in TEXT_FILENAMES:
            raise SafetyViolation("Duplicate or unsupported proposal path")
        seen.add(path.casefold())
        if source.ignore.match_file(path):
            raise SafetyViolation("Cannot modify ignored files")
        exists = target.exists()
        before = source.read_file(path) if exists else ""
        if exists:
            visible = inspected_text(context, path)
            verified_draft = approved_draft is not None and approved_draft[0] == path and approved_draft[1] == digest(before)
            if approved_draft is not None and not verified_draft:
                raise SafetyViolation("Editor source changed on disk; reload before proposing this draft")
            if not visible and not verified_draft and before:
                raise SafetyViolation(f"{path} was not inspected; refusing an uninformed edit")
            if proposed.delete:
                if before.replace("\r\n", "\n").strip() != visible.strip():
                    raise SafetyViolation("Deleting a file requires complete inspected source")
                after = ""
            elif proposed.search is not None and proposed.replace is not None:
                search = proposed.search.replace("\r\n", "\n")
                normalized = before.replace("\r\n", "\n")
                if not search or normalized.count(search) != 1 or search not in visible:
                    raise SafetyViolation(f"{path}: replacement must match a unique inspected source block")
                after = normalized.replace(search, proposed.replace.replace("\r\n", "\n"), 1)
                if "\r\n" in before:
                    after = after.replace("\n", "\r\n")
            elif proposed.content is not None and (not before or verified_draft or before.replace("\r\n", "\n").strip() == visible.strip()):
                after = proposed.content
            else:
                raise SafetyViolation(f"{path}: use an exact replacement or inspect the complete file")
        else:
            if proposed.delete:
                raise SafetyViolation("Cannot delete a missing file")
            if proposed.content is None:
                raise SafetyViolation(f"{path}: new files require complete content")
            after = proposed.content
        if len(after.encode()) > settings.max_file_bytes or "\x00" in after:
            raise SafetyViolation("Proposed file exceeds text/size policy")
        if before == after and not proposed.delete and exists:
            continue
        decision = RiskClassifier().classify("delete" if proposed.delete else "write", path)
        patch = proposed_diff(path, before, after)
        patches.append({"path": path, "before": before, "after": after,
                        "base_hash": digest(before) if exists else None, "reason": proposed.reason,
                        "diff": patch, "risk": decision.risk.value, "applied": False, "delete": proposed.delete,
                        "additions": sum(line.startswith("+") and not line.startswith("+++") for line in patch.splitlines()),
                        "deletions": sum(line.startswith("-") and not line.startswith("---") for line in patch.splitlines())})
        destination = safe_target(stage, path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if proposed.delete:
            destination.unlink(missing_ok=True)
        else:
            destination.write_text(after, encoding="utf-8", newline="")
    for path in proposal.directories:
        target = safe_target(root, path)
        destination = safe_target(stage, path)
        if destination.is_dir() and any(destination.iterdir()):
            continue
        if target.exists():
            if not target.is_dir():
                raise SafetyViolation("Directory path already exists as a file")
            continue
        if source.ignore.match_file(path + "/") or path.casefold() in seen:
            raise SafetyViolation("Ignored or duplicate directory")
        seen.add(path.casefold())
        destination.mkdir(parents=True, exist_ok=True)
        patches.append({"path": path, "before": "", "after": "", "base_hash": None, "directory": True,
            "reason": "Create empty directory", "diff": f"Create directory {path}/", "risk": "LOW", "applied": False,
            "additions": 0, "deletions": 0})
    if not patches:
        raise SafetyViolation("The proposal contained no changes")
    return stage, patches, baseline


def proposal_context(stage: Path, patches: list[dict[str, Any]]) -> list[ContextChunk]:
    result: list[ContextChunk] = []
    budget = 60000
    for patch in patches:
        if patch.get("delete") or patch.get("directory"):
            continue
        source = redact_secrets(patch["after"])
        numbered: list[str] = []
        for line, text in enumerate(source.splitlines(), 1):
            chunk = f"{line}: {text}"
            if len(chunk) > budget:
                break
            numbered.append(chunk)
            budget -= len(chunk) + 1
        if len(numbered) < len(source.splitlines()):
            raise SafetyViolation("Proposal exceeds independent review context budget; split the task")
        result.append(ContextChunk(evidence=Evidence(file=patch["path"], start_line=1,
            end_line=max(1, len(numbered)), sha256=digest(patch["after"])), content="\n".join(numbered), total_lines=max(1, len(numbered))))
    return result


async def static_validation(stage: Path, patches: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[str] = []
    unsupported: list[str] = []
    for patch in patches:
        if patch.get("delete") or patch.get("directory"):
            continue
        path = patch["path"]
        try:
            if path.endswith(".py"):
                ast.parse(patch["after"], filename=path)
            elif path.endswith(".json"):
                json.loads(patch["after"])
            elif path.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")):
                if syntax_tree(path, patch["after"]).has_error:
                    issues.append(f"{path}: Tree-sitter reports invalid syntax")
            elif path.endswith(".toml"):
                import tomllib
                tomllib.loads(patch["after"])
            elif not path.endswith((".md", ".txt", ".css", ".html", ".ini", ".cfg")) and Path(path).name not in {".gitignore", ".forgeignore", "LICENSE", "README", "NOTICE", "CHANGELOG", "AUTHORS", "CONTRIBUTING"}:
                unsupported.append(path)
        except (SyntaxError, ValueError) as error:
            issues.append(f"{path}: {type(error).__name__}")
    output = ""
    if any(p["path"].endswith(".py") for p in patches):
        result = await ValidationRunner(stage).run("ruff", timeout=30)
        output = result.stdout + result.stderr
        if result.exit_code != 0 or result.timed_out:
            issues.append("Ruff static diagnostics failed")
    return {"status": "failed" if issues else "needs_review" if unsupported else "passed",
            "issues": issues, "unsupported_files": unsupported, "output": output, "evidence": "VERIFIED",
            "scope": "Python AST/Ruff, JSON/TOML parsing and JavaScript/TypeScript Tree-sitter; other text is not syntax-verified"}


class ChangeService:
    def __init__(self, sessions: sessionmaker[Session], settings: Settings):
        self.sessions = sessions
        self.settings = settings

    def save(self, project_id: str, proposal: dict[str, Any]) -> str:
        with self.sessions.begin() as session:
            record = ChangeSet(project_id=project_id, proposal=proposal)
            session.add(record)
            session.flush()
            return record.id

    @staticmethod
    def eligible(proposal: dict[str, Any]) -> bool:
        return (not proposal.get("in_progress") and proposal.get("implementation_complete", True) and proposal.get("static", {}).get("status") == "passed"
                and proposal.get("security", {}).get("status") == "passed"
                and proposal.get("tests", {}).get("status") in {"passed", "not_applicable"}
                and proposal.get("review", {}).get("approved") is True
                and not proposal.get("review", {}).get("critical_issues"))

    def update(self, change_id: str, project_id: str, proposal: dict[str, Any]) -> None:
        with self.sessions.begin() as session:
            record = session.get(ChangeSet, change_id)
            if record is None or record.project_id != project_id or record.status != "proposed":
                raise SafetyViolation("Working ChangeSet is no longer editable")
            record.proposal = copy.deepcopy(proposal)

    def apply(self, change_id: str, project: ProjectView, action: ApplyAction) -> dict[str, Any]:
        with workspace_lock(Path(project.path)), self.sessions.begin() as session:
            if session.bind is not None and session.bind.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            checkpoint = session.scalar(select(RunCheckpoint).where(RunCheckpoint.payload["change_id"].as_string() == change_id).order_by(RunCheckpoint.updated_at.desc()))
            if checkpoint and (checkpoint.payload.get("task_status") == "CANCELLED" or not checkpoint.payload.get("engineering", {}).get("implementation_complete", checkpoint.payload.get("next_stage") != "IMPLEMENT")):
                raise SafetyViolation("Implementation is incomplete or cancelled; staged source cannot be applied")
            record = session.scalar(select(ChangeSet).where(ChangeSet.id == change_id).with_for_update())
            if record is None or record.project_id != project.id or record.status not in {"proposed", "partially_applied"}:
                raise SafetyViolation("ChangeSet cannot be applied")
            proposal = copy.deepcopy(record.proposal)
            if not self.eligible(proposal):
                raise SafetyViolation("Static, security, test and independent review gates must pass before application")
            selected = set(action.files) if action.files is not None else {p["path"] for p in proposal["files"]}
            patches = [p for p in proposal["files"] if p["path"] in selected and not p["applied"] and not p.get("rejected")]
            if not patches or selected - {p["path"] for p in proposal["files"]}:
                raise SafetyViolation("No applicable files selected")
            root = Path(project.path)
            environment = LocalExecutionEnvironment(root, self.settings.max_file_bytes)
            deleted = {p["path"] for p in proposal["files"] if p["applied"] and p.get("delete")}
            applied_hashes = {p["path"]: digest(p["after"]) for p in proposal["files"] if p["applied"]}
            for path, source_hash in proposal.get("baseline", {}).items():
                if path in deleted:
                    if safe_target(root, path).exists():
                        raise SafetyViolation("A previously deleted file was recreated; regenerate the ChangeSet")
                    continue
                try:
                    current_hash = digest(environment.read_file(path))
                except (OSError, SafetyViolation) as error:
                    raise SafetyViolation("An inspected source dependency changed; regenerate the ChangeSet") from error
                if current_hash != applied_hashes.get(path, source_hash):
                    raise SafetyViolation("An inspected source dependency changed; regenerate the ChangeSet")
            for patch in patches:
                target = safe_target(root, patch["path"])
                if patch["risk"] in {"HIGH", "CRITICAL"} and not action.approve_high_risk:
                    raise SafetyViolation("High-risk source edits require separate explicit approval")
                if patch["risk"] == "CRITICAL":
                    raise SafetyViolation("Critical-risk edits cannot be applied")
                if patch["base_hash"] is None:
                    if target.exists():
                        raise SafetyViolation("A new file now exists; regenerate the ChangeSet")
                elif not target.exists() or digest(environment.read_file(patch["path"])) != patch["base_hash"]:
                    raise SafetyViolation("Source changed since inspection; regenerate the ChangeSet")
            applied: list[dict[str, Any]] = []
            checkpoints = CheckpointStore(self.settings)
            run = session.get(AgentRun, proposal["run_id"]) if proposal.get("run_id") else None
            checkpoint_id = checkpoints.create(project, change_id, patches, {
                "task_id": proposal.get("run_id"), "conversation_id": run.conversation_id if run else None,
                "summary": proposal.get("summary"),
                "validation": {key: proposal.get(key, {}) for key in ("static", "tests", "security", "review")}})
            try:
                for patch in patches:
                    target = safe_target(root, patch["path"])
                    if patch.get("directory"):
                        target.mkdir(parents=True)
                    elif patch.get("delete"):
                        target.unlink()
                    else:
                        self._atomic_write(target, patch["after"])
                    applied.append(patch)
            except Exception:
                for patch in reversed(applied):
                    target = safe_target(root, patch["path"])
                    if patch["base_hash"] is None:
                        if patch.get("directory"):
                            target.rmdir()
                        else:
                            target.unlink()
                    else:
                        self._atomic_write(target, patch["before"])
                checkpoints.status(project, checkpoint_id, "failed")
                raise
            for patch in patches:
                patch["applied"] = True
            record.status = "applied" if all(p["applied"] or p.get("rejected") for p in proposal["files"]) else "partially_applied"
            record.proposal = {**proposal, "files": proposal["files"]}
            record.proposal = {**record.proposal, "checkpoint_ids": [*proposal.get("checkpoint_ids", []), checkpoint_id]}
            checkpoints.status(project, checkpoint_id, "applied")
            return {"id": record.id, "status": record.status, "proposal": record.proposal}

    @staticmethod
    def _atomic_write(target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".forge-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                stream.write(content)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
