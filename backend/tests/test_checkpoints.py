from pathlib import Path

from fastapi.testclient import TestClient
from test_engineering import EngineeringProvider, setup_project


def test_checkpoint_restores_agent_files_and_preserves_later_manual_work(client: TestClient, project_dir: Path) -> None:
    client.app.state.chat.provider = EngineeringProvider()  # type: ignore[union-attr]
    project_id = setup_project(client, project_dir)
    original = (project_dir / "app/service.py").read_text()
    result = client.post("/chat", json={"project_id": project_id, "message": "Fix greet and add tests", "allow_execution": True}).json()
    change_id = result["change_id"]
    assert client.post(f"/changes/{change_id}/apply", json={}).status_code == 200
    checkpoint = client.get(f"/projects/{project_id}/checkpoints").json()[0]
    assert checkpoint["status"] == "applied"
    prefix = f"/projects/{project_id}"
    source = client.get(prefix + "/file", params={"path": "app/service.py"}).json()
    manual = client.post(prefix + "/files/write", json={"path": "app/service.py", "content": "# later manual edit\n", "base_hash": source["sha256"]})
    assert manual.status_code == 200
    blocked = client.post(prefix + f"/checkpoints/{checkpoint['id']}/restore")
    assert blocked.status_code == 403
    assert (project_dir / "app/service.py").read_text() == "# later manual edit\n"
    assert (project_dir / "tests/test_service.py").exists()
    # The developer deliberately returns the file to the agent's exact saved version.
    client.post(prefix + "/files/write", json={"path": "app/service.py", "content": source["content"], "base_hash": manual.json()["sha256"]})
    client.post(prefix + "/files/write", json={"path": "manual.py", "content": "manual_value = 42\n"})
    restored = client.post(prefix + f"/checkpoints/{checkpoint['id']}/restore")
    assert restored.status_code == 200, restored.text
    assert (project_dir / "app/service.py").read_text() == original
    assert not (project_dir / "tests/test_service.py").exists()
    assert (project_dir / "manual.py").exists()
    assert client.get(f"/changes/{change_id}").json()["status"] == "restored"
