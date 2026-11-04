import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents.orchestrator import Orchestrator
from app.code_intelligence.repository_scanner import ProjectScanner
from app.code_intelligence.retriever import CodeRetriever
from app.config import Settings
from app.llm.base import CompletionRequest, LLMProvider, ProviderError
from app.llm.output import MALFORMED_RESPONSE, completion_problem
from app.llm.providers.http import OpenAICompatibleProvider, messages
from app.models.entities import AgentRun, Message
from app.schemas.domain import ChatRequest

BAD = '{"content": "Cannot run commands", "custom_data": {"message": "Tool execution is disabled in this environment."}}\n<EOS_TOKEN>We need to inspect the repository.'


@pytest.mark.parametrize("task", [
    "make it work with arabic and english language only",
    "Please restrict the supported languages to Arabic and English",
    "Could you update the language selection?",
    "Limit the app to two languages",
])
def test_natural_language_change_requests_are_not_explanations(task: str) -> None:
    assert Orchestrator().route(task, "auto").workflow == "modify"
    assert Orchestrator().route(task, "ask").read_only
    assert Orchestrator().route(task, "plan").workflow == "plan"
    assert Orchestrator().route("Explain how to restrict the supported languages", "auto").workflow == "explain"


async def test_invalid_completion_retries_once_without_exposing_or_reprompting_bad_text(project_dir: Path, settings: Settings) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 2:
            assert b"EOS_TOKEN" not in request.content
            assert b"previous completion had an invalid format" in request.content
        return httpx.Response(200, json={"choices": [{"message": {"content": BAD if calls == 1 else "Arabic and English support is configured in the supplied source."}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(settings.model_copy(update={"llm_model": "test", "llm_base_url": "http://provider"}), client)
        answer = await provider.complete(CompletionRequest(system="Explain", message="Explain language selection",
            context=[], project_map=ProjectScanner(settings).scan(project_dir), level="intermediate"))
    assert calls == 2
    assert "Arabic and English" in answer
    assert "custom_data" not in answer


async def test_persistent_malformed_response_fails_closed(project_dir: Path, settings: Settings) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": BAD}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(settings.model_copy(update={"llm_model": "test", "llm_base_url": "http://provider"}), client)
        with pytest.raises(ProviderError, match="malformed response"):
            await provider.complete(CompletionRequest(system="Explain", message="Hi", context=[],
                project_map=ProjectScanner(settings).scan(project_dir), level="intermediate"))
    assert calls == 2


def test_guard_allows_quoted_protocol_examples_and_structured_code() -> None:
    assert completion_problem("A documented token is `<EOS_TOKEN>`.\n```json\n" + BAD + "\n```") is None
    assert completion_problem(json.dumps({"summary": "Use a literal", "files": [{"content": BAD}]}), structured=True) is None
    assert completion_problem("<think>Private deliberation</think>Answer")
    assert completion_problem(BAD)


def test_context_reports_inventory_and_full_source_without_language_ambiguity(project_dir: Path, settings: Settings) -> None:
    source = "# model source\n" + "# A moderately long implementation detail\n" * 178 + "def translate():\n    return 'Arabic and English'\n"
    (project_dir / "model_handler.py").write_text(source)
    project_map = ProjectScanner(settings).scan(project_dir)
    context = CodeRetriever().retrieve(project_dir, project_map, "Explain model_handler.py", [], 24000, settings.max_file_bytes)
    chunk = next(c for c in context if c.evidence.file == "model_handler.py")
    assert chunk.total_lines == len(source.splitlines())
    assert chunk.evidence.end_line == chunk.total_lines
    payload = messages(CompletionRequest(system="Explain", message="Explain model_handler.py", context=context,
        project_map=project_map, level="intermediate", history=[{"role": "assistant", "content": BAD}]))
    data = json.loads(payload[1]["content"].partition("UNTRUSTED PROJECT DATA:\n")[2])
    assert data["manifest_facts"]["programming_languages"]
    assert "languages" not in data["manifest_facts"]
    assert "app/service.py" in data["indexed_files"]
    assert data["source_excerpts"][0]["coverage"] == "complete file"
    assert not data["previous_conversation"]


def test_legacy_corrupt_history_and_event_replay_are_safe(client: TestClient, project_dir: Path) -> None:
    project_id = client.post("/projects/open", json={"path": str(project_dir)}).json()["id"]
    result = client.post("/chat", json={"project_id": project_id, "message": "Explain greet"}).json()
    sessions = client.app.state.chat.sessions  # type: ignore[union-attr]
    with sessions.begin() as session:
        run = session.get(AgentRun, result["run_id"])
        assert run is not None
        run.result = {**run.result, "answer": BAD}
        run.events = [*run.events, {"type": "result", "message": "completed", "data": run.result}]
        message = session.scalar(select(Message).where(Message.conversation_id == result["conversation_id"], Message.role == "assistant"))
        assert message is not None
        message.content = BAD
    history = client.get(f"/projects/{project_id}/conversations/{result['conversation_id']}")
    assert BAD not in history.text
    assert history.json()[-1]["content"] == MALFORMED_RESPONSE
    assert history.json()[-1]["result"]["status"] == "failed"
    stored = client.get(f"/runs/{result['run_id']}").json()
    assert stored["status"] == "failed"
    assert "EOS_TOKEN" not in json.dumps(stored)
    replay = client.get(f"/runs/{result['run_id']}/events")
    assert "EOS_TOKEN" not in replay.text
    prepared = client.app.state.chat.prepare(ChatRequest(project_id=project_id, conversation_id=result["conversation_id"], message="Explain again"))  # type: ignore[union-attr]
    assert all(item["content"] != BAD for item in prepared.history)
    # The audit record is retained, rather than silently deleting conversation data.
    with sessions() as session:
        run = session.get(AgentRun, result["run_id"])
        assert run is not None and run.result["answer"] == BAD


class BrokenProvider(LLMProvider):
    name = "test_broken"

    async def complete(self, request: CompletionRequest) -> str:
        return BAD


def test_chat_never_marks_invalid_answer_completed(client: TestClient, project_dir: Path) -> None:
    project_id = client.post("/projects/open", json={"path": str(project_dir)}).json()["id"]
    client.app.state.chat.provider = BrokenProvider()  # type: ignore[union-attr]
    result = client.post("/chat", json={"project_id": project_id, "message": "Explain greet"}).json()
    assert result["status"] == "failed"
    assert result["answer"] == MALFORMED_RESPONSE
    assert BAD not in json.dumps(result)


async def test_total_deadline_limits_dribbling_provider_response(project_dir: Path, settings: Settings) -> None:
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            for _ in range(8):
                await asyncio.sleep(0.2)
                yield b" "

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=SlowStream()))) as client:
        provider = OpenAICompatibleProvider(settings.model_copy(update={"llm_model": "test", "llm_base_url": "http://provider", "llm_timeout_seconds": 1}), client)
        with pytest.raises(ProviderError, match="timed out"):
            await provider.complete(CompletionRequest(system="Explain", message="Hello", context=[],
                project_map=ProjectScanner(settings).scan(project_dir), level="intermediate"))


async def test_openrouter_hides_reasoning_caps_output_and_requests_opted_in_json(project_dir: Path, settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["reasoning"] == {"exclude": True}
        assert payload["max_tokens"] == 8192
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"approved": true}', "reasoning": "Private reasoning must stay outside the answer"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(settings.model_copy(update={"llm_model": "test", "llm_base_url": "https://openrouter.ai/api/v1", "llm_json_mode": True}), client)
        answer = await provider.complete(CompletionRequest(system="Return JSON", message="Review", context=[],
            project_map=ProjectScanner(settings).scan(project_dir), level="advanced", structured=True))
    assert answer == '{"approved": true}'


@pytest.mark.parametrize(("status", "message"), [(429, "rate-limiting"), (404, "unavailable"), (402, "credit limit"), (503, "temporarily unavailable")])
async def test_provider_errors_are_specific_without_upstream_bodies(project_dir: Path, settings: Settings, status: int, message: str) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status, text="sensitive upstream text"))) as client:
        provider = OpenAICompatibleProvider(settings.model_copy(update={"llm_model": "test", "llm_base_url": "http://provider"}), client)
        with pytest.raises(ProviderError, match=message) as caught:
            await provider.complete(CompletionRequest(system="Explain", message="Hi", context=[],
                project_map=ProjectScanner(settings).scan(project_dir), level="intermediate"))
        assert "sensitive upstream text" not in str(caught.value)
