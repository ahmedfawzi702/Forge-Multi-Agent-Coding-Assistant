from pathlib import Path

from app.code_intelligence.repository_scanner import ProjectScanner
from app.code_intelligence.retriever import CodeRetriever
from app.code_intelligence.tree_parser import TreeSitterParser, syntax_tree
from app.config import Settings


def test_typescript_symbols_and_invalid_syntax() -> None:
    source = "export function greet(name: string) { return name; }\nexport const twice = (n: number) => n * 2;\nclass Service { run() { return greet('x'); } }\n"
    symbols = TreeSitterParser().parse("src/service.ts", source)
    assert {"greet", "twice", "Service", "run"} <= {s.name for s in symbols}
    assert next(s for s in symbols if s.name == "greet").start_line == 1
    assert syntax_tree("broken.ts", "function () { ???").has_error


def test_resolved_imports_call_candidates_and_exact_lookup(project_dir: Path, settings: Settings) -> None:
    (project_dir / "src").mkdir()
    (project_dir / "src" / "service.ts").write_text("export function authenticate_user() { return true; }\n")
    (project_dir / "src" / "index.ts").write_text("import { authenticate_user } from './service';\nauthenticate_user();\n")
    project_map = ProjectScanner(settings).scan(project_dir)
    edge = next(e for e in project_map.relationships if e["source"] == "src/index.ts")
    assert edge["target"] == "src/service.ts"
    assert edge["certainty"] == "VERIFIED"
    assert any(e["relationship"] == "candidate_call" and e["certainty"] == "INFERENCE" for e in project_map.relationships)
    chunks = CodeRetriever().retrieve(project_dir, project_map, "Where is authenticate_user used?", [], 6000, settings.max_file_bytes)
    assert chunks[0].evidence.file == "src/service.ts"
    assert "src/index.ts" in {c.evidence.file for c in chunks}
