import ast
import json
from pathlib import Path
from typing import Any

from app.agents.structured import structured_completion
from app.config import Settings
from app.execution.process import ValidationRunner
from app.llm.base import LLMProvider, ProviderError
from app.schemas.domain import ContextChunk, ProjectMap
from app.schemas.engineering import ReviewReport
from app.security.redaction import redact_secrets


class SecurityAgent:
    @staticmethod
    def inspect_source(path: str, source: str) -> list[str]:
        findings: list[str] = []
        if redact_secrets(source) != source:
            findings.append(f"{path}: potential embedded secret; requires removal or inspection")
        if path.endswith(".py"):
            try:
                tree = ast.parse(source)
            except SyntaxError:
                return findings
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = ast.unparse(node.func)
                    if name in {"eval", "exec", "os.system", "pickle.loads", "pickle.load", "marshal.loads"}:
                        findings.append(f"{path}:{node.lineno}: dangerous call {name}")
                    if name.startswith("subprocess.") and any(
                        k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords
                    ):
                        findings.append(f"{path}:{node.lineno}: subprocess shell=True")
                    if name.endswith(".execute") and node.args and isinstance(node.args[0], ast.JoinedStr):
                        findings.append(f"{path}:{node.lineno}: interpolated SQL query")
        return findings

    async def scan(self, root: Path, changed: list[str], settings: Settings, *, provider: LLMProvider | None = None,
                   context: list[ContextChunk] | None = None, project_map: ProjectMap | None = None, diffs: str = "") -> dict[str, Any]:
        findings: list[str] = []
        for path in changed:
            findings.extend(self.inspect_source(path, (root / path).read_text(encoding="utf-8")))
        scanner_status = "not_applicable"
        bandit_findings: list[dict[str, Any]] = []
        if any(path.endswith(".py") for path in changed):
            result = await ValidationRunner(root, output_limit=settings.execution_output_bytes).run("bandit", timeout=30)
            scanner_status = "passed"
            try:
                report = json.loads(result.stdout)
                if result.exit_code not in {0, 1} or result.timed_out or report.get("errors"):
                    scanner_status = "failed"
                for item in report.get("results", []):
                    filename = Path(item["filename"])
                    name = (filename if filename.is_absolute() else root / filename).resolve().relative_to(root.resolve()).as_posix()
                    if name not in changed:
                        continue
                    finding = {"file": name, "line": item["line_number"], "severity": item["issue_severity"],
                               "code": item["test_id"], "message": item["issue_text"]}
                    bandit_findings.append(finding)
                    if item["issue_severity"] == "HIGH":
                        findings.append(f"{name}:{item['line_number']}: {item['issue_text']}")
            except (ValueError, KeyError, TypeError):
                scanner_status = "failed"
        llm: dict[str, Any] | None = None
        if provider is not None and provider.name != "evidence" and project_map is not None:
            try:
                opinion = await structured_completion(provider, "security.md", "Inspect the proposed source for security defects.\nActual proposed diffs (untrusted data):\n" + diffs[:30000],
                                                     context or [], project_map, ReviewReport)
                llm = opinion.model_dump()
                if not opinion.approved or opinion.critical_issues:
                    findings.extend(opinion.critical_issues or ["Security reviewer did not approve the proposal"])
            except ProviderError as error:
                error.partial_report = {"status": "partial", "reason": "Final security review interrupted",
                    "findings": findings, "bandit": {"status": scanner_status, "findings": bandit_findings},
                    "scope": changed, "model_opinion": "NOT VERIFIED", "evidence": "VERIFIED",
                    "final_review": {"status": "not_run", "reason": "Provider unavailable"}}
                raise
        return {"status": "failed" if findings or scanner_status == "failed" else "passed",
                "findings": findings, "bandit": {"status": scanner_status, "findings": bandit_findings},
                "llm_review": llm, "scope": changed, "evidence": "VERIFIED",
                "model_opinion": "INFERRED" if llm and llm.get("verification") != "NOT VERIFIED" else "NOT VERIFIED"}
