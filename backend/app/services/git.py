import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import Settings
from app.execution.commands import CommandRunner
from app.execution.file_io import text_hash
from app.execution.local import LocalExecutionEnvironment
from app.schemas.domain import ProjectView
from app.schemas.workspace import GitAction
from app.security.paths import safe_target
from app.security.policy import SafetyViolation


class GitService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def run(self, root: Path, args: list[str], timeout: int = 30, *, network: bool = False) -> tuple[int, str, str]:
        hooks = self.settings.data_directory / "disabled-hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        argv = ["git", "-c", f"core.hooksPath={hooks}", "-c", "core.fsmonitor=false", "-c", "credential.helper="]
        if network:
            # Trust the user's installed helpers, never a helper injected by the opened repo.
            for scope in ("--system", "--global"):
                code, helpers, _ = await self.run(root, ["config", scope, "--get-all", "credential.helper"])
                if code == 0:
                    for helper in helpers.splitlines():
                        argv += ["-c", f"credential.helper={helper}"]
            argv += ["-c", "credential.interactive=false", "-c", "core.askPass=", "-c", "http.sslVerify=true",
                "-c", "protocol.allow=never", "-c", "protocol.https.allow=always", "-c", "http.followRedirects=false",
                "-c", "submodule.recurse=false"]
        argv += args
        result = await CommandRunner(root, output_limit=131072).run(argv, timeout, trusted_git=True)
        return result.exit_code, result.stdout, result.stderr

    async def status(self, project: ProjectView) -> dict[str, Any]:
        root = Path(project.path)
        code, output, error = await self.run(root, ["status", "--porcelain=v1", "-z", "--untracked-files=normal"])
        if code:
            return {"repository": False, "branch": None, "files": [], "error": error, "evidence": "VERIFIED"}
        _, branch, _ = await self.run(root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
        entries = output.split("\x00")
        files: list[dict[str, Any]] = []
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if len(entry) < 4:
                continue
            state, path = entry[:2], entry[3:].replace("\\", "/")
            if state[0] in {"R", "C"}:
                index += 1  # -z supplies the original path as a following field.
            files.append({"path": path, "status": state, "staged": state[0] not in {" ", "?"}})
        return {"repository": True, "branch": branch.strip() or "detached HEAD", "files": files[:500], "evidence": "VERIFIED"}

    async def diff(self, project: ProjectView, staged: bool = False) -> dict[str, Any]:
        args = ["diff", "--no-ext-diff", "--no-textconv", "--no-color"]
        if staged:
            args.append("--cached")
        code, output, error = await self.run(Path(project.path), args)
        return {"patch": output, "exit_code": code, "stderr": error, "staged": staged,
                "sha256": text_hash(output), "truncated": len(output.encode()) >= 131072, "evidence": "VERIFIED"}

    async def agent_diff(self, project: ProjectView, staged_only: bool = False) -> dict[str, Any]:
        """Filter paths before invoking Git: excluded tracked secrets never enter a model prompt."""
        source = LocalExecutionEnvironment(Path(project.path), self.settings.max_file_bytes)
        status = await self.status(project)
        paths: list[str] = []
        untracked: list[str] = []
        for item in status["files"]:
            if staged_only and not item["staged"]:
                continue
            path = item["path"]
            try:
                safe_target(Path(project.path), path)
                if source.ignore.match_file(path):
                    continue
                if item["status"] == "??":
                    content = source.read_file(path)
                    untracked.append(f"Untracked {path}:\n{content[:12000]}")
                else:
                    paths.append(path)
            except (OSError, SafetyViolation):
                continue
        patches = []
        for cached in ((True,) if staged_only else (False, True)):
            if paths:
                args = ["--literal-pathspecs", "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames"]
                if cached:
                    args.append("--cached")
                code, output, error = await self.run(Path(project.path), [*args, "--", *paths[:200]])
                if code:
                    raise SafetyViolation(error[:1000] or "Git diff failed")
                patches.append(("STAGED" if cached else "UNSTAGED") + "\n" + output)
        from app.security.redaction import redact_secrets
        combined = redact_secrets("\n".join([*patches, *untracked]))
        return {"patch": combined[:40000], "sha256": text_hash(combined), "truncated": len(combined) > 40000,
            "paths": paths, "untracked_count": len(untracked), "repository": status["repository"], "evidence": "VERIFIED"}

    async def action(self, project: ProjectView, body: GitAction) -> dict[str, Any]:
        root = Path(project.path)
        if body.action in {"fetch", "pull", "push"}:
            return await self.network_action(project, body)
        if body.action == "init":
            args = ["init"]
        elif body.action in {"stage", "unstage"}:
            if not body.paths:
                raise SafetyViolation("Select at least one file")
            for path in body.paths:
                safe_target(root, path)
            if body.action == "stage":
                args = ["--literal-pathspecs", "add", "--", *body.paths]
            else:
                code, _, _ = await self.run(root, ["rev-parse", "--verify", "HEAD"])
                args = (["--literal-pathspecs", "restore", "--staged", "--", *body.paths] if code == 0 else
                        ["--literal-pathspecs", "rm", "--cached", "--", *body.paths])
        elif body.action == "commit":
            from app.services.hooks import HookService
            await HookService(self.settings).enforce(project, "BeforeCommit", approved=body.approve_hooks)
            if not body.message.strip():
                raise SafetyViolation("A commit message is required")
            args = ["commit", "--no-gpg-sign", "-m", body.message]
        elif body.action == "abort_merge":
            if not body.confirmed:
                raise SafetyViolation("Explicit confirmation is required to abort a merge")
            args = ["merge", "--abort"]
        else:
            self.validate_branch(body.branch)
            if body.action == "switch" and (await self.status(project))["files"]:
                raise SafetyViolation("Save and commit or resolve working-tree changes before switching branches")
            args = ["switch", *(["-c"] if body.action == "branch" else []), body.branch]
        # rm --cached is a fixed unstage operation, never a working-tree deletion.
        if body.action == "unstage" and "rm" in args:
            code, output, error = await self._unstage_unborn(root, body.paths)
        else:
            code, output, error = await self.run(root, args)
        if code:
            raise SafetyViolation(error[:3000] or "Git operation failed")
        return {"status": "completed", "stdout": output, "git": await self.status(project), "evidence": "VERIFIED"}

    async def _unstage_unborn(self, root: Path, paths: list[str]) -> tuple[int, str, str]:
        # update-index removes entries from the index without deleting source files.
        return await self.run(root, ["--literal-pathspecs", "update-index", "--force-remove", "--", *paths])

    @staticmethod
    def validate_branch(branch: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}", branch) or ".." in branch or "//" in branch or any(p.startswith(".") or p.endswith((".", ".lock")) for p in branch.split("/")) or branch.endswith("/"):
            raise SafetyViolation("Invalid branch name")

    @staticmethod
    def validate_url(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or any(c.isspace() or ord(c) < 32 for c in url) or "\\" in url:
            raise SafetyViolation("Use a credential-free HTTPS repository URL; authenticate with an installed Git credential helper")
        return url

    async def clone(self, project: ProjectView, url: str, branch: str = "") -> None:
        self.validate_url(url)
        if branch:
            self.validate_branch(branch)
        code, _, _ = await self.run(Path(project.path), ["clone", "--no-recurse-submodules", *(["--branch", branch] if branch else []), "--", url, "."], timeout=180, network=True)
        if code:
            raise SafetyViolation("Clone failed. Check the HTTPS URL, network and Git credential helper authentication. No credentials are included in this diagnostic.")

    async def remotes(self, project: ProjectView) -> list[dict[str, str]]:
        root = Path(project.path)
        _, names, _ = await self.run(root, ["remote"])
        result = []
        for name in names.splitlines()[:30]:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", name):
                continue
            _, url, _ = await self.run(root, ["remote", "get-url", name])
            try:
                result.append({"name": name, "url": self.validate_url(url.strip())})
            except SafetyViolation:
                result.append({"name": name, "url": "Unsupported remote; use credential-free HTTPS"})
        return result

    async def network_target(self, project: ProjectView, remote: str, *, push: bool = False) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", remote):
            raise SafetyViolation("Invalid remote name")
        root = Path(project.path)
        code, urls, _ = await self.run(root, ["remote", "get-url", *(["--push"] if push else []), "--all", remote])
        if code or len(urls.splitlines()) != 1:
            raise SafetyViolation("Choose a remote with exactly one HTTPS destination")
        url = self.validate_url(urls.strip())
        # Pass the verified expanded URL directly; repository refspecs/push options are not used.
        status = await self.status(project)
        branch = status["branch"]
        if branch is None or branch == "detached HEAD":
            raise SafetyViolation("Switch to a named branch first")
        self.validate_branch(branch)
        if any("U" in f["status"] or f["status"] in {"AA", "DD"} for f in status["files"]):
            raise SafetyViolation("Resolve conflicted files before remote operations")
        _, head, _ = await self.run(root, ["rev-parse", "HEAD"])
        return {"remote": remote, "url": url, "branch": branch, "head": head.strip(), "uncommitted_files": len(status["files"]),
            "authentication": "Uses system/global Git credential helpers. No credentials are sent to the model."}

    async def network_action(self, project: ProjectView, body: GitAction) -> dict[str, Any]:
        target = await self.network_target(project, body.remote, push=body.action == "push")
        if not body.confirmed:
            raise SafetyViolation("Explicit confirmation of the remote operation is required")
        if body.branch != target["branch"]:
            raise SafetyViolation("Current branch changed; review and confirm the destination again")
        if body.action == "push" and (body.expected_url != target["url"] or body.expected_head != target["head"]):
            raise SafetyViolation("Remote destination or commit changed; review and confirm the push again")
        if body.action == "pull" and target["uncommitted_files"]:
            raise SafetyViolation("Commit or resolve local changes before pulling; local edits will not be overwritten")
        branch = target["branch"]
        if body.action == "push":
            args = ["-c", "push.followTags=false", "-c", "push.recurseSubmodules=no", "push", "--porcelain", "--no-verify", "--", target["url"], f"refs/heads/{branch}:refs/heads/{branch}"]
        elif body.action == "pull":
            args = ["pull", "--ff-only", "--no-rebase", "--no-recurse-submodules", "--", target["url"], f"refs/heads/{branch}"]
        else:
            args = ["fetch", "--no-tags", "--no-recurse-submodules", "--", target["url"], f"refs/heads/{branch}:refs/remotes/{body.remote}/{branch}"]
        code, _, _ = await self.run(Path(project.path), args, timeout=180, network=True)
        if code:
            raise SafetyViolation("Git remote operation failed. Check authentication, repository permission and branch divergence. Pull uses fast-forward only; no force push or local overwrite was attempted.")
        if body.action == "push":
            code, output, _ = await self.run(Path(project.path), ["ls-remote", "--exit-code", "--", target["url"], f"refs/heads/{branch}"], timeout=60, network=True)
            if code or output.split()[:1] != [target["head"]]:
                raise SafetyViolation("Push was sent, but the remote commit could not be verified. Refresh before retrying.")
        return {"status": "completed", "operation": body.action, "destination": target, "remote_verified": body.action == "push", "git": await self.status(project), "evidence": "VERIFIED"}

    async def details(self, project: ProjectView) -> dict[str, Any]:
        root = Path(project.path)
        _, output, _ = await self.run(root, ["for-each-ref", "--format=%(refname:short)", "refs/heads/"])
        _, log, _ = await self.run(root, ["log", "-20", "--format=%h%x09%s%x09%aI"])
        _, upstream, _ = await self.run(root, ["rev-parse", "--abbrev-ref", "@{upstream}"])
        _, counts, _ = await self.run(root, ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"])
        return {"branches": output.splitlines(), "remotes": await self.remotes(project), "history": log.splitlines(),
            "upstream": upstream.strip() or None, "ahead_behind": counts.split() if counts.strip() else None,
            "authentication": "Configure Git Credential Manager or gh auth setup-git outside Forge for private repositories.", "pull_request_creation": False}

    async def conflicts(self, project: ProjectView, path: str) -> dict[str, Any]:
        root = Path(project.path)
        safe_target(root, path)
        source = LocalExecutionEnvironment(root, self.settings.max_file_bytes, agent=False)
        source.read_file(path)  # Enforce text/path policy before exposing index blobs.
        versions = {}
        for stage, label in ((1, "base"), (2, "current"), (3, "incoming")):
            code, content, _ = await self.run(root, ["show", f":{stage}:{path}"])
            versions[label] = content if code == 0 else ""
        return {"path": path, **versions, "resolution": "Edit and save the working file, then stage it after reviewing the resolution."}
