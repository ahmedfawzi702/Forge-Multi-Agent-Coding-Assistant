from pathlib import Path

from fastapi.testclient import TestClient

from app.execution.local import LocalExecutionEnvironment
from app.security.policy import SafetyViolation


def test_empty_project_manual_create_save_move_trash_restore(client: TestClient) -> None:
    result = client.post("/projects/new", json={"name": "Empty demo", "template": "empty"})
    assert result.status_code == 200, result.text
    project = result.json()
    root = Path(project["path"])
    assert list(root.iterdir()) == []
    assert project["source_kind"] == "managed"
    prefix = f"/projects/{project['id']}"
    assert client.post(prefix + "/folders", json={"path": "src/empty"}).status_code == 200
    tree = client.get(prefix + "/tree").json()
    assert {"path": "src/empty", "kind": "directory"} in tree
    first = client.post(prefix + "/files/write", json={"path": "src/hello.py", "content": 'print("Hello")\n'})
    assert first.status_code == 200, first.text
    base = first.json()["sha256"]
    assert (root / "src/hello.py").read_text() == 'print("Hello")\n'
    assert client.post(prefix + "/files/write", json={"path": "src/hello.py", "content": "overwrite"}).status_code == 403
    saved = client.post(prefix + "/files/write", json={"path": "src/hello.py", "content": 'print("World")\n', "base_hash": base})
    assert saved.status_code == 200
    assert client.get(prefix + "/search", params={"q": "World", "include": "*.py"}).json()["hits"][0]["line"] == 1
    moved = client.post(prefix + "/files/move", json={"path": "src/hello.py", "destination": "hello.py"})
    assert moved.status_code == 200
    assert not (root / "src/hello.py").exists()
    trashed = client.post(prefix + "/files/trash", json={"path": "hello.py"}).json()
    assert not (root / "hello.py").exists()
    assert client.post(prefix + f"/trash/{trashed['trash_id']}/restore").status_code == 200
    assert (root / "hello.py").exists()
    assert client.post(prefix + "/refresh").json()["source_kind"] == "managed"


def test_workspace_creation_and_mutation_cannot_escape_roots(client: TestClient, project_dir: Path) -> None:
    project = client.post("/projects/new", json={"name": "local-new", "location": str(project_dir)}).json()
    assert Path(project["path"]) == project_dir / "local-new"
    prefix = f"/projects/{project['id']}"
    for path in ("../outside.py", ".env", "C:/outside.py", "con.py", ".git/config"):
        response = client.post(prefix + "/files/write", json={"path": path, "content": "bad"})
        assert response.status_code == 403, path
    assert client.post("/projects/new", json={"name": "../escape"}).status_code == 403
    assert client.post("/projects/new", json={"name": "bad", "location": str(project_dir.parent.parent)}).status_code == 403


def test_forgeignore_blocks_agent_access_but_not_manual_editor(client: TestClient, project_dir: Path) -> None:
    (project_dir / ".forgeignore").write_text("private_notes.py\n")
    (project_dir / "private_notes.py").write_text("value = 42\n", newline="")
    project = client.post("/projects/open", json={"path": str(project_dir)}).json()
    assert "private_notes.py" not in {entry["path"] for entry in project["project_map"]["files"]}
    manual = client.get(f"/projects/{project['id']}/file", params={"path": "private_notes.py"})
    assert manual.json()["content"] == "value = 42\n"
    try:
        LocalExecutionEnvironment(project_dir).read_file("private_notes.py")
    except SafetyViolation:
        pass
    else:
        raise AssertionError("Agent read bypassed .forgeignore")
