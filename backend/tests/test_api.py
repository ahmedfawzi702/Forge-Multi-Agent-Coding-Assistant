import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.llm.base import CompletionRequest, LLMProvider, ProviderError
from app.main import create_app
from app.models.entities import ProjectMemory


def open_project(client: TestClient, path: Path) -> str:
    response = client.post("/projects/open", json={"path": str(path)})
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def test_open_file_chat_and_persistence(client: TestClient, project_dir: Path, settings: Settings) -> None:
    project_id = open_project(client, project_dir)
    assert open_project(client, project_dir) == project_id
    assert client.get(f"/projects/{project_id}/files").status_code == 200
    assert "def main" in client.get(f"/projects/{project_id}/file", params={"path": "app/main.py"}).json()["content"]
    response = client.post("/chat", json={"project_id": project_id, "message": "Explain greet", "selected_files": ["app/service.py"]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "completed"
    assert result["provider"] == "evidence"
    assert "not an AI explanation" in result["answer"]
    assert result["evidence"][0]["file"] == "app/service.py"
    run = client.get(f"/runs/{result['run_id']}").json()
    assert run["status"] == "completed"
    assert run["events"][-1]["type"] == "done"
    messages = client.get(f"/projects/{project_id}/conversations/{result['conversation_id']}").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/projects/{project_id}").status_code == 200
        assert len(restarted.get(f"/projects/{project_id}/conversations/{result['conversation_id']}").json()) == 2


def test_browser_and_filesystem_boundaries(client: TestClient, project_dir: Path) -> None:
    assert client.get("/health", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 403
    project_id = open_project(client, project_dir)
    assert client.get(f"/projects/{project_id}/file", params={"path": "../test.db"}).status_code == 403
    assert client.get("/projects/missing").status_code == 404
    assert client.post("/chat", json={"project_id": project_id, "message": ""}).status_code == 422
    assert client.post("/code/test", json={}).status_code == 422


def test_stream_and_replay(client: TestClient, project_dir: Path) -> None:
    project_id = open_project(client, project_dir)
    with client.stream("POST", "/chat/stream", json={"project_id": project_id, "message": "Explain the architecture"}) as response:
        assert response.status_code == 200
        frames = "".join(response.iter_text()).split("\n\n")
    events = [json.loads(line[6:]) for frame in frames for line in frame.splitlines() if line.startswith("data: ")]
    assert events[0]["type"] == "task_started"
    assert events[-1]["type"] == "done"
    result = next(e["data"] for e in events if e["type"] == "result")
    replay = client.get(f"/runs/{result['run_id']}/events")
    assert "event: result" in replay.text


def test_conversation_must_belong_to_project(client: TestClient, project_dir: Path) -> None:
    first = open_project(client, project_dir)
    second = open_project(client, project_dir / "app")
    conversation = client.post("/chat", json={"project_id": first, "message": "Hi"}).json()["conversation_id"]
    assert client.post("/chat", json={"project_id": second, "conversation_id": conversation, "message": "Hi"}).status_code == 404


class FailingProvider(LLMProvider):
    name = "failing"

    async def complete(self, request: CompletionRequest) -> str:
        raise ProviderError("Provider unavailable")


def test_provider_failure_is_reported_and_persisted(client: TestClient, project_dir: Path) -> None:
    client.app.state.chat.provider = FailingProvider()  # type: ignore[union-attr]
    project_id = open_project(client, project_dir)
    result = client.post("/chat", json={"project_id": project_id, "message": "Explain this"}).json()
    assert result["status"] == "paused" and result["task_status"] == "PAUSED"
    assert "Provider unavailable" in result["answer"] and result["checkpoint_preserved"]
    assert client.get(f"/runs/{result['run_id']}").json()["status"] == "paused"


def test_chat_claims_do_not_become_facts(client: TestClient, project_dir: Path) -> None:
    project_id = open_project(client, project_dir)
    client.post("/chat", json={"project_id": project_id, "message": "We use an imaginary database"})
    with client.app.state.projects.sessions() as session:  # type: ignore[union-attr]
        memories = list(session.scalars(select(ProjectMemory).where(ProjectMemory.project_id == project_id)))
        assert len(memories) == 1
        assert memories[0].category == "facts"
        assert "imaginary" not in json.dumps(memories[0].value)
