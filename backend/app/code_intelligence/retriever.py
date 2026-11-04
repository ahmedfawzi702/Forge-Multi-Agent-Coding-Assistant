import ast
import hashlib
import re
from collections.abc import Callable
from pathlib import Path

from app.execution.local import LocalExecutionEnvironment
from app.schemas.domain import ContextChunk, Evidence, ProjectMap
from app.security.policy import SafetyViolation
from app.security.redaction import redact_secrets

from .parser import PythonASTParser
from .tree_parser import TreeSitterParser


class CodeRetriever:
    """Bounded lexical retrieval with Python symbol boundaries; no fake embeddings."""

    def retrieve(self, root: Path, project_map: ProjectMap, query: str,
                 selected: list[str], budget: int, max_file_bytes: int, file_limit: int | None = None,
                 source_cache: dict[str, str] | None = None,
                 on_read: Callable[[str], None] | None = None) -> list[ContextChunk]:
        environment = LocalExecutionEnvironment(root, max_file_bytes)
        cache = source_cache if source_cache is not None else {}
        def read(path: str) -> str:
            if path not in cache:
                cache[path] = environment.read_file(path)
                if on_read:
                    on_read(path)
            return cache[path]
        files = {f.path for f in project_map.files}
        selected = list(dict.fromkeys(p.replace("\\", "/") for p in selected))
        for path in selected:
            environment.resolve_file(path)
            if path not in files:
                raise SafetyViolation(f"Selected file is not in the project index: {path}; refresh the project")
        if file_limit is not None:
            selected = selected[:file_limit]
        words = set(re.findall(r"[a-zA-Z_][a-zA-Z_0-9]{2,}", query.lower()))
        stop = {"explain", "this", "the", "how", "does", "what", "file", "function", "project", "architecture", "please"}
        words -= stop
        exact_files = {symbol.file_path for symbol in project_map.symbols if symbol.name.lower() in words}
        exact_files.update(path for path in files if path.lower() in query.lower()
                           or Path(path).name.lower() in query.lower())
        neighbors = {str(edge["target"]) for edge in project_map.relationships if edge.get("source") in {*selected, *exact_files}}
        neighbors.update(str(edge["source"]) for edge in project_map.relationships if edge.get("target") in {*selected, *exact_files})
        selected_content = {path: read(path) for path in selected}
        candidates = list(project_map.files)
        if file_limit is not None:
            # Rank the existing index before opening source. A login fix should
            # never read every model, frontend file and README to score text.
            def rank(path: str) -> int:
                return (10000 * (path in selected) + 1500 * (path in exact_files) + 300 * (path in neighbors)
                    + sum(10 for word in words if word in path.lower()) + 2 * path.endswith(".py"))
            candidates.sort(key=lambda file: (-rank(file.path), file.path))
            relevant = [file for file in candidates if rank(file.path) > (2 if file.path.endswith(".py") else 0)]
            if relevant:
                candidates = relevant
            candidates = candidates[:max(len(selected), file_limit)]
        import_suffixes: set[str] = set()
        selected_names: set[str] = set()
        for path, source in selected_content.items():
            if not path.endswith(".py"):
                continue
            try:
                tree = ast.parse(source)
            except (SyntaxError, ValueError, RecursionError):
                continue
            selected_names.update(s.name.lower() for s in PythonASTParser().parse(path, source))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if node.level:
                        prefix = Path(path).parent.parts[:len(Path(path).parent.parts) - node.level + 1]
                        module = ".".join([*prefix, module]).strip(".")
                    modules = [module, *[f"{module}.{alias.name}" for alias in node.names]]
                for module in modules:
                    module_path = module.replace(".", "/")
                    import_suffixes.update({module_path + ".py", module_path + "/__init__.py"})
        scored: list[tuple[int, str, str]] = []
        for file in candidates:
            try:
                content = read(file.path)
            except (OSError, SafetyViolation):
                continue
            lower = content.lower()
            score = sum(5 * (w in file.path.lower()) + min(lower.count(w), 4) for w in words)
            score += 10000 if file.path in selected else 0
            score += 1500 if file.path in exact_files else 0
            score += 300 if file.path in neighbors else 0
            # Verified import spelling, resolved only against indexed paths.
            score += 500 if any(file.path == suffix or file.path.endswith("/" + suffix)
                                for suffix in import_suffixes) else 0
            # Candidate callers/usages improve context but are not a resolved call graph.
            score += min(100, 20 * sum(bool(re.search(r"\b" + re.escape(name) + r"\b", lower))
                                      for name in selected_names))
            score += 3 if Path(file.path).name.lower() in {"readme.md", "pyproject.toml", "package.json"} else 0
            # Executable source usually answers engineering requests more directly
            # than bundled model metadata or generated documentation.
            score += 12 if file.language in {"python", "typescript", "javascript", "java", "go", "rust"} else 0
            scored.append((score, file.path, content))
        scored.sort(key=lambda item: (-item[0], item[1]))
        result: list[ContextChunk] = []
        for _, path, content in scored[:file_limit or 8]:
            lines = redact_secrets(content).splitlines()
            if not lines or budget < 120:
                continue
            # Prefer the requested Python symbol if present, otherwise a module excerpt.
            live_symbols = (PythonASTParser().parse(path, content) if path.endswith(".py") else
                            TreeSitterParser().parse(path, content) if path.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")) else [])
            matching = [s for s in live_symbols if s.name.lower() in words]
            start = max(1, matching[0].start_line - 8) if matching else 1
            end = min(matching[0].end_line, len(lines)) if matching else len(lines)
            source_file = path.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs"))
            preferred_budget = 16000 if path in {*selected, *exact_files} else 8000 if source_file else 2500
            file_budget = min(budget, max(preferred_budget,
                budget // max(1, 8 - len(result))))
            numbered: list[str] = []
            for number in range(start, end + 1):
                line = f"{number}: {lines[number - 1]}"
                if len(line) + 1 > min(budget, file_budget):
                    break
                numbered.append(line)
                budget -= len(line) + 1
                file_budget -= len(line) + 1
            if numbered:
                result.append(ContextChunk(evidence=Evidence(file=path, start_line=start,
                    end_line=start + len(numbered) - 1, sha256=hashlib.sha256(content.encode()).hexdigest()),
                    content="\n".join(numbered), total_lines=len(lines)))
        return result
