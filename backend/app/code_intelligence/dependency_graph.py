import ast
import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, Protocol

from app.execution.local import LocalExecutionEnvironment
from app.schemas.domain import CodeSymbol, FileEntry
from app.security.policy import SafetyViolation


@dataclass(frozen=True)
class DependencyEdge:
    source: str
    target: str
    relationship: Literal["imports", "calls", "uses"]
    evidence_file: str
    evidence_line: int


class DependencyGraph(Protocol):
    """Extension interface for a persisted, fully resolved dependency graph."""

    def affected(self, symbol_id: str) -> list[DependencyEdge]: ...


def build_relationships(environment: LocalExecutionEnvironment, files: list[FileEntry],
                        symbols: list[CodeSymbol]) -> list[dict[str, str | int]]:
    paths = {file.path for file in files}
    definitions: dict[str, set[str]] = defaultdict(set)
    for symbol in symbols:
        definitions[symbol.name].add(symbol.file_path)
    edges: list[dict[str, str | int]] = []
    for file in files:
        if file.language not in {"python", "typescript", "javascript"}:
            continue
        try:
            source = environment.read_file(file.path)
        except (OSError, SafetyViolation):
            continue
        imports: list[tuple[str, int]] = []
        calls: list[tuple[str, int]] = []
        if file.language == "python":
            try:
                tree = ast.parse(source)
            except (SyntaxError, ValueError, RecursionError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend((alias.name.replace(".", "/"), node.lineno) for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    module = (node.module or "").replace(".", "/")
                    if node.level:
                        module = posixpath.normpath(posixpath.join(posixpath.dirname(file.path), *([".."] * (node.level - 1)), module))
                    imports.append((module, node.lineno))
                elif isinstance(node, ast.Call):
                    name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    if name:
                        calls.append((name, node.lineno))
        else:
            for line, text in enumerate(source.splitlines(), 1):
                match = re.search(r"\b(?:from\s+|import\s*)['\"]([^'\"]+)['\"]", text)
                if match:
                    module = match[1]
                    if module.startswith("."):
                        module = posixpath.normpath(posixpath.join(posixpath.dirname(file.path), module))
                    elif module.startswith("@/"):
                        module = module[2:]
                    imports.append((module, line))
        for module, line in imports:
            suffixes = [module + ending for ending in (".py", "/__init__.py", ".ts", ".tsx", ".js", "/index.ts", "/index.tsx")]
            candidates = [path for path in paths if any(path == suffix or path.endswith("/" + suffix) for suffix in suffixes)]
            if len(candidates) == 1:
                edges.append({"source": file.path, "target": candidates[0], "relationship": "imports", "line": line, "certainty": "VERIFIED"})
        for name, line in calls:
            called_files = definitions.get(name, set()) - {file.path}
            if len(called_files) == 1:
                edges.append({"source": file.path, "target": next(iter(called_files)), "relationship": "candidate_call", "symbol": name, "line": line, "certainty": "INFERENCE"})
        if len(edges) >= 10000:
            break
    return edges[:10000]
