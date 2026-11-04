import json
import os
import re
import tomllib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.execution.local import LocalExecutionEnvironment, is_link
from app.schemas.domain import CodeSymbol, FileEntry, ProjectMap
from app.security.policy import IGNORED_DIRECTORIES, SafetyViolation, is_sensitive

from .dependency_graph import build_relationships
from .parser import PythonASTParser
from .tree_parser import TreeSitterParser

LANGUAGES = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
    ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".json": "json", ".md": "markdown", ".toml": "toml",
    ".yaml": "yaml", ".yml": "yaml", ".css": "css", ".html": "html", ".txt": "text",
    ".sql": "sql", ".rs": "rust", ".go": "go", ".java": "java", ".sh": "shell",
    ".ini": "ini", ".cfg": "ini", ".xml": "xml", ".cs": "csharp", ".c": "c", ".cpp": "cpp",
}
TEXT_FILENAMES = {".gitignore", ".forgeignore", "Dockerfile", "Makefile", "LICENSE", "README", "NOTICE", "CHANGELOG", "AUTHORS", "CONTRIBUTING"}


class ProjectScanner:
    def __init__(self, settings: Settings):
        self.settings = settings

    def validate_root(self, raw: str) -> Path:
        supplied = Path(raw).expanduser()
        if not supplied.is_absolute():
            raise SafetyViolation("Open a project using an absolute directory path")
        if not supplied.is_dir() or is_link(supplied):
            raise SafetyViolation("Project must be an existing directory, not a link")
        root = supplied.resolve(strict=True)
        if not any(root.is_relative_to(p) for p in self.settings.workspace_roots):
            raise SafetyViolation("Project is outside WORKSPACE_ROOTS; update the backend .env")
        return root

    def scan(self, root: Path) -> ProjectMap:
        root = self.validate_root(str(root))
        environment = LocalExecutionEnvironment(root, self.settings.max_file_bytes)
        files: list[FileEntry] = []
        symbols: list[CodeSymbol] = []
        dependencies: set[str] = set()
        warnings: list[str] = []
        parser = PythonASTParser()
        skipped = 0
        directories: list[str] = []
        for current, dirs, names in os.walk(root, followlinks=False):
            base = Path(current)
            dirs[:] = sorted(d for d in dirs if d.lower() not in IGNORED_DIRECTORIES
                             and not d.startswith(".") and not is_link(base / d)
                             and not environment.ignore.match_file((base / d).relative_to(root).as_posix() + "/"))
            directories.extend((base / d).relative_to(root).as_posix() for d in dirs)
            for name in sorted(names):
                path = base / name
                relative = path.relative_to(root).as_posix()
                if (is_link(path) or is_sensitive(path) or environment.ignore.match_file(relative)
                        or (path.suffix.lower() not in LANGUAGES and name not in TEXT_FILENAMES)):
                    continue
                if len(files) >= self.settings.max_files:
                    warnings.append(f"Scan capped at {self.settings.max_files} files; narrow the project root for complete coverage.")
                    dirs.clear()
                    break
                try:
                    source = environment.read_file(relative)
                except (SafetyViolation, OSError):
                    skipped += 1
                    continue
                language = LANGUAGES.get(path.suffix.lower(), "text")
                files.append(FileEntry(path=relative, language=language, size=path.stat().st_size))
                if language == "python":
                    symbols.extend(parser.parse(relative, source))
                elif language in {"typescript", "javascript"}:
                    symbols.extend(TreeSitterParser().parse(relative, source))
                if name == "package.json":
                    try:
                        manifest = json.loads(source)
                        dependencies.update(manifest.get("dependencies", {}))
                        dependencies.update(manifest.get("devDependencies", {}))
                    except (ValueError, AttributeError, TypeError):
                        warnings.append(f"Could not parse {relative}")
                if name == "pyproject.toml":
                    try:
                        manifest = tomllib.loads(source)
                        dependencies.update(manifest.get("project", {}).get("dependencies", []))
                        for group in manifest.get("project", {}).get("optional-dependencies", {}).values():
                            dependencies.update(group)
                    except (ValueError, TypeError, AttributeError):
                        warnings.append(f"Could not parse {relative}")
                if name == "requirements.txt":
                    dependencies.update(line.strip() for line in source.splitlines()
                                        if line.strip() and not line.startswith(("#", "-")))
            if warnings and warnings[-1].startswith("Scan capped"):
                break
        counts = Counter(f.language for f in files)
        frameworks = [name for name in ("fastapi", "next", "react", "django", "flask", "pytest", "sqlalchemy")
                      if any(re.split(r"[\[<>=!~; ]", d.lower())[0] == name for d in dependencies)]
        entries = [f.path for f in files if Path(f.path).name in {"main.py", "app.py", "manage.py", "page.tsx", "index.ts", "index.js"}]
        if skipped:
            warnings.append(f"Skipped {skipped} unreadable, binary or oversized files.")
        if not files:
            warnings.append("Empty workspace. Create a file or ask Forge to build something.")
        return ProjectMap(
            language=[name for name, _ in counts.most_common()], framework=frameworks,
            entry_points=entries, dependencies=sorted(dependencies), files=files,
            important_directories=sorted({str(Path(f.path).parent).replace("\\", "/") for f in files})[:80],
            symbols=symbols,
            architecture_summary=f"Indexed {len(files)} text files and {len(symbols)} code symbols. "
                                 f"Manifest evidence: {', '.join(frameworks) or 'no recognized frameworks'}. "
                                 "Entry points are filename candidates, not verified runtime behavior.",
            warnings=warnings, scanned_at=datetime.now(UTC).isoformat(),
            testing_framework=[name for name in ("pytest", "jest", "vitest") if any(name in d.lower() for d in dependencies)],
            database_layer=[name for name in ("sqlalchemy", "prisma", "mongoose", "psycopg") if any(name in d.lower() for d in dependencies)],
            relationships=build_relationships(environment, files, symbols),
            directories=directories[:self.settings.max_files * 2],
        )
