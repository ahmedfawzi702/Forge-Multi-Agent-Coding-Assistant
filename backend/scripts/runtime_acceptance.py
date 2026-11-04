"""Live-provider acceptance runs in isolated state; never applies generated changes.

Run from backend: ../.venv/Scripts/python.exe scripts/runtime_acceptance.py
Results contain public diagnostics and validation reports, never credentials.
"""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def main() -> None:
    directory = Path(__file__).resolve().parents[2] / ".data" / "runtime-acceptance" / datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    directory.mkdir(parents=True)
    settings = Settings().model_copy(update={
        "state_directory": directory, "database_url": f"sqlite:///{(directory / 'acceptance.db').as_posix()}",
        "workspace_roots": [directory],
    })
    summary = {"provider": settings.llm_provider, "model": settings.llm_model, "scenarios": []}
    print(f"Live acceptance state: {directory}", flush=True)
    with TestClient(create_app(settings)) as client:
        def execute(name: str, message: str, files: dict[str, str] | None = None, **extra: object) -> dict:
            project = client.post("/projects/new", json={"name": name}).json()
            for path, content in (files or {}).items():
                response = client.post(f"/projects/{project['id']}/files/write", json={"path": path, "content": content})
                response.raise_for_status()
            print(f"Starting {name}", flush=True)
            response = client.post("/chat", json={"project_id": project["id"], "message": message, "allow_execution": True, **extra})
            response.raise_for_status()
            result = response.json()
            record = {"scenario": name, "project_id": project["id"], "result": result,
                "run": client.get(f"/runs/{result['run_id']}").json()}
            if result.get("change_id"):
                record["change"] = client.get(f"/changes/{result['change_id']}").json()
            (directory / f"{name}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            item = {"scenario": name, "status": result["status"], "run_id": result["run_id"],
                "diagnostics": result["diagnostics"], "resumable": result.get("resumable"), "change_id": result.get("change_id")}
            summary["scenarios"].append(item)
            (directory / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            print(json.dumps(item), flush=True)
            return record

        execute("01-hello", "Create hello.py that prints Hello World.")
        execute("02-fastapi", "Create a FastAPI app with a /health endpoint and one pytest test. The endpoint returns {\"status\": \"ok\"}. Use app.py and test_app.py. FastAPI, httpx and pytest are already installed. Fix any errors you discover.")
        fixtures = {"login.py": 'def normalize_username(username: str) -> str:\n    return username.strip().lower()[:-1]\n',
            "test_login.py": 'from login import normalize_username\n\n\ndef test_login_username():\n    assert normalize_username(" Alice ") == "alice"\n'}
        fixtures.update({f"unrelated/module_{n:03}.py": f"def unrelated_{n}():\n    return {n}\n" for n in range(40)})
        execute("03-login", "Fix the bug in login. Username normalization should strip whitespace and lowercase without losing characters. Run the existing regression test.", fixtures)
        execute("04-explain", "Explain this function.", {"math_utils.py": "def clamp(value: float, lower: float, upper: float) -> float:\n    return max(lower, min(value, upper))\n"}, mode="ask", selected_files=["math_utils.py"])
        # A deliberately tiny last-resort limit exercises recovery with a real model.
        client.app.state.chat.settings = settings.model_copy(update={"forge_max_tool_calls": 3})
        record = execute("05-jwt", "Implement JWT authentication in this new FastAPI project. Use Python standard-library HMAC SHA-256 signing, expiry and signature verification, reject invalid/expired tokens, use an injected secret with no hardcoded production fallback. Add auth.py, app.py and pytest regression tests for valid, tampered and expired tokens. Use a test-only secret in tests. FastAPI, httpx and pytest are installed. Do not install packages.")
        result = record["result"]
        if result.get("resumable"):
            client.app.state.chat.settings = settings
            print("Resuming JWT from saved checkpoint", flush=True)
            response = client.post(f"/runs/{result['run_id']}/resume", json={"allow_execution": True})
            response.raise_for_status()
            resumed = response.json()
            resumed_record = {"result": resumed, "run": client.get(f"/runs/{resumed['run_id']}").json()}
            if resumed.get("change_id"):
                resumed_record["change"] = client.get(f"/changes/{resumed['change_id']}").json()
            (directory / "05-jwt-resumed.json").write_text(json.dumps(resumed_record, indent=2), encoding="utf-8")
            summary["jwt_resume"] = {"status": resumed["status"], "diagnostics": resumed["diagnostics"], "change_id": resumed.get("change_id"), "resumable": resumed.get("resumable")}
            (directory / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            print(json.dumps(summary["jwt_resume"]), flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--resume":
        directory = Path(sys.argv[2]).resolve(strict=True)
        settings = Settings().model_copy(update={"state_directory": directory,
            "database_url": f"sqlite:///{(directory / 'acceptance.db').as_posix()}", "workspace_roots": [directory]})
        with TestClient(create_app(settings)) as client:
            response = client.post(f"/runs/{sys.argv[3]}/resume", json={"allow_execution": True})
            response.raise_for_status()
            result = response.json()
            record = {"result": result, "run": client.get(f"/runs/{result['run_id']}").json()}
            if result.get("change_id"):
                record["change"] = client.get(f"/changes/{result['change_id']}").json()
            (directory / "05-jwt-final-resume.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            print(json.dumps({key: result.get(key) for key in ["status", "run_id", "change_id", "diagnostics", "resumable"]}), flush=True)
    else:
        main()
