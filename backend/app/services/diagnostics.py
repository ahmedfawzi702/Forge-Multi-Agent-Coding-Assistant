import ast
import json
from pathlib import Path
from typing import Any

from app.code_intelligence.tree_parser import syntax_tree
from app.config import Settings
from app.execution.commands import CommandRunner
from app.execution.local import LocalExecutionEnvironment
from app.schemas.domain import ProjectView
from app.security.policy import SafetyViolation


class DiagnosticsService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def inspect(self, project: ProjectView) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        source = LocalExecutionEnvironment(Path(project.path), self.settings.max_file_bytes)
        for file in project.project_map.files:
            try:
                text = source.read_file(file.path)
                if file.path.endswith(".py"):
                    ast.parse(text, filename=file.path)
                elif file.path.endswith(".json"):
                    json.loads(text)
                elif file.path.endswith((".ts", ".tsx", ".js", ".jsx")) and syntax_tree(file.path, text).has_error:
                    result.append({"file": file.path, "line": 1, "column": 1, "severity": "error", "message": "Tree-sitter reports invalid syntax", "source": "syntax"})
            except (SyntaxError, json.JSONDecodeError) as error:
                result.append({"file": file.path, "line": error.lineno or 1,
                    "column": getattr(error, "offset", None) or getattr(error, "colno", None) or 1,
                    "severity": "error", "message": error.msg, "source": "syntax"})
            except (SafetyViolation, OSError):
                continue
            if len(result) >= 200:
                break
        return result

    async def format(self, project: ProjectView | None, path: str, content: str) -> str:
        if len(content.encode()) > self.settings.max_file_bytes:
            raise SafetyViolation("Draft exceeds the formatting limit")
        if path.endswith(".py"):
            root = Path(project.path) if project else self.settings.data_directory
            root.mkdir(parents=True, exist_ok=True)
            result = await CommandRunner(root, output_limit=self.settings.max_file_bytes).run(
                ["ruff", "format", "--isolated", "--stdin-filename", "source.py", "-"], timeout=15, input_text=content)
            if result.exit_code or result.timed_out:
                raise SafetyViolation(result.stderr[:2000] or "Ruff formatting failed")
            return result.stdout
        if path.endswith(".json"):
            try:
                return json.dumps(json.loads(content), indent=2, ensure_ascii=False) + "\n"
            except ValueError as error:
                raise SafetyViolation("Fix JSON syntax before formatting") from error
        raise SafetyViolation("Use the editor's language formatter for this file type")
