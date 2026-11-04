from pathlib import Path

import pytest

from app.code_intelligence.parser import PythonASTParser
from app.code_intelligence.repository_scanner import ProjectScanner
from app.code_intelligence.retriever import CodeRetriever
from app.config import Settings
from app.security.policy import SafetyViolation


def test_scan_symbols_manifests_and_exclusions(project_dir: Path, settings: Settings) -> None:
    (project_dir / ".env").write_text("PASSWORD=private")
    (project_dir / ".gitignore").write_text("ignored/\n")
    for directory in ("node_modules", ".git", "ignored"):
        (project_dir / directory).mkdir()
        (project_dir / directory / "hidden.py").write_text("SECRET = 'x'")
    (project_dir / "binary.py").write_bytes(b"\x00binary")
    project_map = ProjectScanner(settings).scan(project_dir)
    paths = {f.path for f in project_map.files}
    assert "app/main.py" in paths
    assert ".env" not in paths
    assert not any("hidden.py" in path for path in paths)
    assert "fastapi" in project_map.framework
    assert any(s.name == "greet" and s.start_line == 1 and s.end_line == 3 for s in project_map.symbols)
    assert project_map.warnings


def test_scan_cap_and_bad_manifests(project_dir: Path, settings: Settings) -> None:
    (project_dir / "package.json").write_text("invalid json")
    project_map = ProjectScanner(settings.model_copy(update={"max_files": 2})).scan(project_dir)
    assert len(project_map.files) == 2
    assert any("capped" in warning for warning in project_map.warnings)


def test_workspace_roots_are_enforced(project_dir: Path, settings: Settings) -> None:
    scanner = ProjectScanner(settings.model_copy(update={"workspace_roots": [project_dir / "app"]}))
    with pytest.raises(SafetyViolation):
        scanner.validate_root(str(project_dir))
    with pytest.raises(SafetyViolation):
        scanner.validate_root("relative/project")


def test_retrieval_is_bounded_grounded_and_redacted(project_dir: Path, settings: Settings) -> None:
    (project_dir / "app" / "service.py").write_text('api_key = "super-private-value"\n\ndef greet(name):\n    return name\n')
    project_map = ProjectScanner(settings).scan(project_dir)
    chunks = CodeRetriever().retrieve(project_dir, project_map, "Explain greet", ["app/service.py"], 2000, settings.max_file_bytes)
    assert chunks[0].evidence.file == "app/service.py"
    assert "super-private-value" not in "".join(c.content for c in chunks)
    assert "[REDACTED]" in chunks[0].content
    assert len(chunks[0].evidence.sha256) == 64
    assert sum(len(c.content) for c in chunks) <= 2000


def test_changed_file_does_not_use_stale_symbol_bounds(project_dir: Path, settings: Settings) -> None:
    project_map = ProjectScanner(settings).scan(project_dir)
    (project_dir / "app" / "main.py").write_text("# replaced\n")
    chunks = CodeRetriever().retrieve(project_dir, project_map, "main", ["app/main.py"], 2000, settings.max_file_bytes)
    assert chunks[0].evidence.end_line == 1


def test_selected_file_must_be_indexed(project_dir: Path, settings: Settings) -> None:
    project_map = ProjectScanner(settings).scan(project_dir)
    (project_dir / "new.py").write_text("value = 1")
    with pytest.raises(SafetyViolation):
        CodeRetriever().retrieve(project_dir, project_map, "explain", ["new.py"], 2000, settings.max_file_bytes)


def test_multiline_secret_redaction_keeps_source_lines(project_dir: Path, settings: Settings) -> None:
    source = "# embedded key\nKEY = '''-----BEGIN PRIVATE KEY-----\nprivate-body-123\n-----END PRIVATE KEY-----'''\n\ndef greet():\n    return 'ok'\n"
    (project_dir / "app" / "service.py").write_text(source)
    project_map = ProjectScanner(settings).scan(project_dir)
    chunks = CodeRetriever().retrieve(project_dir, project_map, "greet", ["app/service.py"], 2000, settings.max_file_bytes)
    assert "private-body-123" not in chunks[0].content
    assert "6: def greet():" in chunks[0].content


def test_imports_and_candidate_callers_are_retrieved(project_dir: Path, settings: Settings) -> None:
    for number in range(12):
        (project_dir / f"aaa_{number}.py").write_text("# unrelated\n")
    project_map = ProjectScanner(settings).scan(project_dir)
    chunks = CodeRetriever().retrieve(project_dir, project_map, "Explain this file",
        ["app/main.py"], settings.context_char_budget, settings.max_file_bytes)
    assert chunks[0].evidence.file == "app/main.py"
    assert chunks[1].evidence.file == "app/service.py"
    callers = CodeRetriever().retrieve(project_dir, project_map, "Explain this function",
        ["app/service.py"], settings.context_char_budget, settings.max_file_bytes)
    assert "app/main.py" in {c.evidence.file for c in callers}


def test_nested_functions_are_not_class_methods() -> None:
    symbols = PythonASTParser().parse("sample.py", "def outer():\n    def inner():\n        pass\n\nclass Service:\n    def run(self):\n        pass\n")
    assert next(s for s in symbols if s.name == "inner").type == "function"
    assert next(s for s in symbols if s.name == "run").type == "method"
