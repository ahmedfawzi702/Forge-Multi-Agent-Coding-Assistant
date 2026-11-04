from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "sample"
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_text(
        'from app.service import greet\n\ndef main(name: str) -> str:\n    """Entry point."""\n    return greet(name)\n', encoding="utf-8")
    (root / "app" / "service.py").write_text(
        'def greet(name: str) -> str:\n    """Say hello."""\n    return f"Hello {name}"\n', encoding="utf-8")
    (root / "README.md").write_text("# Example\nA small greeting service.\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "sample"\ndependencies = ["fastapi>=0.115", "pytest>=8"]\n', encoding="utf-8")
    return root


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, workspace_roots=[tmp_path], state_directory=tmp_path / "managed", database_url=f"sqlite:///{tmp_path / 'test.db'}", llm_provider="evidence")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
