from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas.domain import ProjectView
from app.schemas.engineering import CodeProposal
from app.security.policy import SafetyViolation
from app.services.proposals import stage_proposal


def test_new_paths_and_uninspected_overwrites_are_rejected(client: TestClient, project_dir: Path, settings: Settings) -> None:
    project = ProjectView.model_validate(client.post("/projects/open", json={"path": str(project_dir)}).json())
    proposal = CodeProposal(summary="Unsafe rewrite", files=[{"path": "app/main.py", "content": "pass\n", "reason": "rewrite"}])
    with pytest.raises(SafetyViolation, match="not inspected"):
        stage_proposal(project, proposal, [], settings)
    for path in (".env", "../outside.py", ".git/config.py", "app/private.pem"):
        proposal = CodeProposal(summary="Unsafe target", files=[{"path": path, "content": "value=1\n", "reason": "unsafe"}])
        with pytest.raises(SafetyViolation):
            stage_proposal(project, proposal, [], settings)


def test_request_body_limit_is_enforced(settings: Settings) -> None:
    with TestClient(create_app(settings.model_copy(update={"max_request_bytes": 2048}))) as client:
        response = client.post("/projects/import", content=b"x" * 4096, headers={"Content-Type": "application/json"})
        assert response.status_code == 413
