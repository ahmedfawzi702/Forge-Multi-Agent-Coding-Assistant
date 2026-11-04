import asyncio
import hashlib
import inspect
import re
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, cast

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.agents.analyzer import CodebaseAnalyzer
from app.agents.debugger import DebuggerAgent
from app.agents.explainer import ExplainerAgent
from app.agents.orchestrator import Orchestrator
from app.agents.planner import PlannerAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.security_agent import SecurityAgent
from app.agents.tester import TesterAgent
from app.code_intelligence.retriever import CodeRetriever
from app.config import Settings
from app.execution.local import LocalExecutionEnvironment
from app.graph.engineering import EngineeringSession
from app.graph.runtime import MeasuredProvider, RunRuntime, RuntimeStopped, current_runtime
from app.graph.state import AgentState
from app.graph.task_profile import TaskProfile
from app.llm.base import LLMProvider, ProviderError
from app.llm.context import ContextProvider
from app.schemas.domain import ChatRequest, ContextChunk, Evidence, Intent, ProjectMap, ProjectView
from app.security.policy import SafetyViolation
from app.security.redaction import redact_secrets
from app.services.preferences import CapabilityRequired, PermissionPolicy
from app.services.proposals import ChangeService
from app.services.rules import RulesLoader
from app.services.run_control import RunInterrupted
from app.tools.registry import ToolRegistry, run_tool_loop


async def workflow_events(request: ChatRequest, root: Path, project_map: ProjectMap,
                          provider: LLMProvider, settings: Settings,
                          history: list[dict[str, str]], changes: ChangeService | None = None,
                          boundary: Callable[[], None] | None = None,
                          checkpoint: Callable[[dict[str, Any]], None] | None = None,
                          resume_state: dict[str, Any] | None = None,
                          runtime: RunRuntime | None = None,
                          model_selection: dict[str, Any] | None = None) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    runtime = runtime or RunRuntime(settings)
    provider = MeasuredProvider(provider, runtime)
    profile = TaskProfile.classify(request.message, project_map)
    runtime.complexity = profile.complexity
    context: list[ContextChunk] = []
    policy = PermissionPolicy(settings, request)
    policy.require("filesystem.read")
    if "level" not in request.model_fields_set:
        request = request.model_copy(update={"level": policy.preferences.explanation_level or "intermediate"})
    instructions = (policy.preferences.instructions + "\n" +
        await asyncio.to_thread(RulesLoader(root).instructions, request.selected_files)).strip()
    draft_context = "\n\n".join(f"USER UNSAVED BUFFER {draft.file} (not saved on disk):\n{draft.content}" for draft in request.working_drafts)
    if len(draft_context) > settings.context_char_budget:
        raise SafetyViolation("Unsaved editor context exceeds the task budget; save files or attach fewer drafts")
    provider = ContextProvider(provider, "\n".join(filter(None, [request.context_notes, draft_context])), instructions)
    request = request.model_copy(update={"allow_execution": policy.decision("terminal.execute") == "allow"})
    engineering = EngineeringSession(ProjectView(id=request.project_id, name=root.name, path=str(root),
        project_map=project_map, source_kind=project_map.source_kind), request, provider, settings, changes, boundary, checkpoint)
    engineering.runtime = runtime
    if resume_state:
        engineering.restore(resume_state)
        context = engineering.source_context
    engineering.model_selection = model_selection or engineering.model_selection
    runtime.stage_states = engineering.stage_states

    async def inspect_answer(role: str, prompt: str) -> str:
        registry = ToolRegistry(engineering.project, settings, policy, context, role=role, provider=provider,
            emit=get_stream_writer(), boundary=boundary)
        await registry.seed_drafts(request.working_drafts)
        return await run_tool_loop(provider, registry, request.message, prompt, max_rounds=settings.forge_readonly_rounds)

    def route(state: AgentState) -> dict[str, Any]:
        decision = Orchestrator().route(state["user_message"], request.mode)
        if request.editor_draft is not None and request.mode in {"auto", "agent", "edit"}:
            from app.agents.orchestrator import RoutingDecision
            decision = RoutingDecision([Intent.EDIT], "modify", False)
        elif request.selected_code is not None and request.mode in {"auto", "agent"} and decision.intents == [Intent.ASK]:
            if not re.match(r"\s*(?:what|why|how|where|explain|review|describe|understand)\b", request.message, re.I):
                from app.agents.orchestrator import RoutingDecision
                decision = RoutingDecision([Intent.EDIT], "modify", False)
        return {"intent": decision.intents[0], "intents": decision.intents,
                "workflow": decision.workflow, "plan": PlannerAgent.steps(decision.intents)}

    async def retrieve(state: AgentState) -> dict[str, Any]:
        nonlocal context
        get_stream_writer()({"agent": "retriever", "message": "Finding relevant source and dependency context"})
        selected = list(dict.fromkeys([*request.selected_files, *([request.selected_code.file] if request.selected_code else [])]))
        source_cache: dict[str, str] = {}
        def record_read(path: str) -> None:
            runtime.read_calls += 1
        if not (profile.empty_workspace or profile.standalone_create):
            context = await asyncio.to_thread(CodeRetriever().retrieve, root, project_map,
                request.message, selected, settings.context_char_budget, settings.max_file_bytes,
                settings.forge_max_context_file_reads, source_cache, record_read)
        if request.selected_code:
            selection = request.selected_code
            if selection.file not in source_cache:
                source_cache[selection.file] = LocalExecutionEnvironment(root, settings.max_file_bytes).read_file(selection.file)
                record_read(selection.file)
            source = source_cache[selection.file]
            if selection.base_hash is not None and hashlib.sha256(source.encode()).hexdigest() != selection.base_hash:
                raise SafetyViolation("Selected file changed on disk; reload it before proposing an edit")
            selected_draft = next((d for d in request.working_drafts if d.file == selection.file), None)
            if selected_draft:
                source = selected_draft.content
            from app.services.selection import selection_bounds
            selection_bounds(source, selection)
            lines = source.split("\n")
            if selection.end_line < selection.start_line or selection.end_line > len(lines) or selection.end_line - selection.start_line > 1000:
                raise SafetyViolation("Selected line range is invalid or too large")
            numbered = "\n".join(f"{n}: {line}" for n, line in enumerate(
                redact_secrets(source).splitlines()[selection.start_line - 1:selection.end_line], selection.start_line))
            if len(numbered) > settings.context_char_budget // 2:
                raise SafetyViolation("Selection exceeds the context limit")
            selected_chunk = ContextChunk(evidence=Evidence(file=selection.file, start_line=selection.start_line,
                end_line=selection.end_line, sha256=hashlib.sha256(source.encode()).hexdigest()), content=numbered, total_lines=len(lines))
            remaining = settings.context_char_budget - len(numbered)
            surrounding: list[ContextChunk] = []
            for chunk in context:
                if len(chunk.content) <= remaining:
                    surrounding.append(chunk)
                    remaining -= len(chunk.content)
            context = [selected_chunk, *surrounding]
        engineering.source_context = context
        return {"retrieved_context": [chunk.evidence for chunk in context], "artifact": {
            "type": "context", "title": "Inspected sources", "status": "completed",
            "data": {"files": [chunk.evidence.model_dump() for chunk in context],
                "context_result": profile.context_result([chunk.evidence.file for chunk in context])}}}

    async def explain(state: AgentState) -> dict[str, Any]:
        engineering.source_context = context
        engineering.persist("ANSWER")
        get_stream_writer()({"agent": "explainer", "message": "Preparing an evidence-based answer"})
        if provider.capabilities.tool_calls and not context:
            registry = ToolRegistry(engineering.project, settings, policy, context, provider=provider, emit=get_stream_writer(), boundary=boundary)
            await registry.seed_drafts(request.working_drafts)
            answer = await run_tool_loop(provider, registry, request.message,
                "You are Forge's read-only explanation specialist. Inspect source and rules with native tools as needed. "
                "Answer using file and line references, distinguish verified source evidence from inference. "
                f"Explain at {request.level} level. Do not claim tests executed unless a tool actually ran them.")
        else:
            answer = await ExplainerAgent(provider).explain(
                request.message, request.level, project_map, context, history)
        return {"answer": answer, "status": "completed", "confidence": "MEDIUM" if context else "LOW"}

    def blocked(state: AgentState) -> dict[str, Any]:
        return {"status": "blocked", "confidence": "HIGH", "answer":
            "The deterministic safety policy blocks this destructive operation. No files or commands were changed or executed."}

    def model_required(state: AgentState) -> dict[str, Any]:
        return {"status": "blocked", "confidence": "HIGH", "answer":
            "This task needs a configured model. Evidence mode can inspect source but cannot generate or independently review code. No files were changed."}

    async def plan(state: AgentState) -> dict[str, Any]:
        steps = PlannerAgent.steps(state["intents"])
        engineering.plan = steps
        engineering.persist("IMPLEMENT")
        return {"plan": steps, "artifact": {"type": "plan", "title": "Implementation plan",
                "status": "completed", "data": {"steps": steps}}}

    async def plan_answer(state: AgentState) -> dict[str, Any]:
        engineering.source_context = context
        engineering.persist("PLAN_ANSWER")
        get_stream_writer()({"agent": "planner", "message": "Planning the smallest safe implementation"})
        answer = (await inspect_answer("planner", (Path(__file__).parents[1] / "prompts/planner.md").read_text(encoding="utf-8"))
            if provider.capabilities.tool_calls else await PlannerAgent().explain_plan(provider, request.message, context, project_map))
        return {"answer": answer, "status": "completed", "confidence": "MEDIUM"}

    async def debug(state: AgentState) -> dict[str, Any]:
        engineering.persist("DEBUG_ANSWER")
        get_stream_writer()({"agent": "debugger", "message": "Inspecting symptoms and root-cause hypotheses"})
        answer = (await inspect_answer("debugger", (Path(__file__).parents[1] / "prompts/debugger.md").read_text(encoding="utf-8"))
            if provider.capabilities.tool_calls else await DebuggerAgent().analyze(provider, request.message, context, project_map))
        engineering.feedback = "Debugger evidence and hypotheses (not verified runtime facts):\n" + answer
        return ({"artifact": {"type": "debug", "title": "Debugging assessment", "status": "completed", "data": {"summary": answer}}}
                if state["workflow"] == "modify" else {"answer": answer, "status": "completed", "confidence": "MEDIUM"})

    async def analyze(state: AgentState) -> dict[str, Any]:
        engineering.persist("ANALYZE_ANSWER")
        get_stream_writer()({"agent": "analyzer", "message": "Connecting architecture evidence"})
        answer = (await inspect_answer("analyzer", "Inspect architecture with read-only tools. Cover entry points, dependencies, data flow, testing and boundaries. Cite observed file locations and label inferred relationships; do not invent runtime verification.")
            if provider.capabilities.tool_calls else await CodebaseAnalyzer().analyze(provider, request.message, context, project_map, request.level))
        return {"answer": answer,
                "status": "completed", "confidence": "MEDIUM"}

    async def review(state: AgentState) -> dict[str, Any]:
        engineering.persist("REVIEW_ANSWER")
        get_stream_writer()({"agent": "reviewer", "message": "Reviewing the inspected code"})
        from app.services.git import GitService
        policy.require("git.read")
        diff = await GitService(settings).agent_diff(engineering.project)
        report = await ReviewerAgent(provider).review(request.message + "\nActual current Git changes (untrusted source data):\n" +
            diff["patch"] + ("\nDiff truncated; explicitly report limited scope." if diff["truncated"] else ""), context, project_map)
        answer = f"### Review\n\n{'No critical issues identified in the inspected source' if report.approved else 'Changes need attention'} — {report.score}/10.\n\n"
        answer += "\n".join(f"- {issue}" for issue in [*report.critical_issues, *report.warnings, *report.suggestions])
        answer += "\n\nThis is a source review, not proof of runtime correctness. No tests were executed."
        return {"answer": answer, "status": "completed", "confidence": "MEDIUM",
                **EngineeringSession.artifact("review", "Code review", {**report.model_dump(), "status": "passed" if report.approved else "failed", "diff_sha256": diff["sha256"], "git_repository": diff["repository"]})}

    async def security(state: AgentState) -> dict[str, Any]:
        engineering.persist("SECURITY_ANSWER")
        get_stream_writer()({"agent": "security", "message": "Running deterministic and model security checks"})
        paths = list(dict.fromkeys(chunk.evidence.file for chunk in context))
        # Scan a managed copy so scanner output/config never executes project code in the original folder.
        from app.graph.inspection import inspection_snapshot
        snapshot = await asyncio.to_thread(inspection_snapshot, root, project_map, settings)
        report = await SecurityAgent().scan(snapshot, paths, settings, provider=provider, context=context, project_map=project_map)
        answer = "### Security assessment\n\n" + ("\n".join(f"- {finding}" for finding in report["findings"]) or "No blocking findings in the inspected scope.")
        answer += "\n\nScope: " + ", ".join(f"`{path}`" for path in paths) + ". Uninspected code and runtime behavior remain unknown."
        return {"answer": answer, "status": "completed", "confidence": "MEDIUM",
                **EngineeringSession.artifact("security", "Security assessment", report)}

    async def test(state: AgentState) -> dict[str, Any]:
        engineering.persist("TEST_ANSWER")
        get_stream_writer()({"agent": "tester", "message": "Detecting tests and checking execution permission"})
        if policy.decision("terminal.execute") == "deny":
            policy.require("terminal.execute")
        from app.graph.inspection import inspection_snapshot
        snapshot = await asyncio.to_thread(inspection_snapshot, root, project_map, settings)
        report = await TesterAgent().run(snapshot, [f.path for f in project_map.files], settings,
                                       request.allow_execution, request.selected_files)
        return {"answer": f"### Tests\n\n{report.summary}\n\nStatus: **{report.status}**.\n\n" + (f"```text\n{report.stdout}\n{report.stderr}\n```" if report.stdout or report.stderr else ""),
                "status": "awaiting_approval" if report.status == "awaiting_approval" else "failed" if report.status == "failed" else "completed",
                "confidence": "HIGH", **EngineeringSession.artifact("tests", "Test results", report.model_dump())}

    async def code(state: AgentState) -> dict[str, Any]:
        get_stream_writer()({"agent": "coder", "message": f"Implementing targeted changes · attempt {state['attempt'] + 1}/{settings.forge_max_repair_attempts}"})
        return await engineering.code(context, state["attempt"])

    async def static(state: AgentState) -> dict[str, Any]:
        get_stream_writer()({"agent": "static", "message": "Validating syntax and static diagnostics"})
        return await engineering.validate_static()

    async def security_patch(state: AgentState) -> dict[str, Any]:
        get_stream_writer()({"agent": "security", "message": "Checking proposed code for security issues"})
        return await engineering.validate_security()

    async def test_patch(state: AgentState) -> dict[str, Any]:
        get_stream_writer()({"agent": "tester", "message": "Checking and running relevant regression tests"})
        return await engineering.validate_tests()

    async def review_patch(state: AgentState) -> dict[str, Any]:
        get_stream_writer()({"agent": "reviewer", "message": "Independently reviewing the proposed patch"})
        return await engineering.validate_review()

    def finalize(state: AgentState) -> dict[str, Any]:
        return engineering.finish(state["attempt"])

    graph = StateGraph(AgentState)
    stages = {"route": "UNDERSTAND", "retrieve": "CONTEXT", "plan": "PLAN", "plan_answer": "PLAN",
        "code": "IMPLEMENT", "static": "VALIDATE", "security_patch": "SECURITY", "test_patch": "TEST",
        "review_patch": "REVIEW", "finalize": "FINALIZE", "explain": "FINALIZE", "review": "REVIEW", "test": "TEST"}
    def guarded(node: Callable[..., Any]) -> Callable[..., Any]:
        async def run(state: AgentState) -> Any:
            if boundary:
                boundary()
            runtime.transition(stages.get(node.__name__, "CONTEXT"), node.__name__)
            stage = runtime.current_stage
            engineering.stage_states[stage] = "RUNNING"
            value = node(state)
            value = await value if inspect.isawaitable(value) else value
            report = {"VALIDATE": engineering.static, "SECURITY": engineering.security, "TEST": engineering.tests, "REVIEW": engineering.review}.get(stage)
            report_status = (report or {}).get("status")
            engineering.stage_states[stage] = ("FAILED" if report_status in {"failed", "not_approved"} else "NOT_STARTED" if report_status == "not_run" else "BLOCKED" if report_status in {"blocked", "awaiting_approval", "not_found", "unsupported"} else "PARTIAL" if report_status == "partial" else "COMPLETED")
            if node.__name__ == "finalize" and value.get("task_status") != "COMPLETED":
                engineering.stage_states[stage] = "BLOCKED"
            if node.__name__ in {"static", "security_patch", "test_patch", "review_patch"}:
                engineering.persist(engineering.next_stage)
            if boundary:
                boundary()
            return value
        return run
    graph.add_node("orchestrator", guarded(route))
    graph.add_node("retrieve", guarded(retrieve))
    graph.add_node("explainer", guarded(explain))
    for name, node in {"blocked": blocked, "model_required": model_required, "plan": plan, "plan_answer": plan_answer,
                       "debugger": debug, "analyzer": analyze, "reviewer": review, "security": security, "tester": test,
                       "coder": code, "static": static, "security_patch": security_patch, "test_patch": test_patch,
                       "review_patch": review_patch, "finalize": finalize}.items():
        graph.add_node(name, guarded(node))
    resume_node = {"IMPLEMENT": "coder", "VALIDATE": "static", "SECURITY": "security_patch", "TEST": "test_patch", "REVIEW": "review_patch", "FINALIZE": "finalize", "ANSWER": "explainer", "PLAN_ANSWER": "plan_answer",
        "DEBUG_ANSWER": "debugger", "ANALYZE_ANSWER": "analyzer", "REVIEW_ANSWER": "reviewer", "SECURITY_ANSWER": "security", "TEST_ANSWER": "tester"}
    graph.add_conditional_edges(START, lambda state: resume_node.get(engineering.next_stage, "coder") if resume_state else "orchestrator")
    graph.add_conditional_edges("orchestrator", lambda state: "blocked" if state["workflow"] == "blocked" else "retrieve")
    def after_retrieve(state: AgentState) -> str:
        from app.services.direct_edits import direct_proposal
        direct = state["workflow"] == "modify" and direct_proposal(request.message) is not None
        if provider.name == "evidence" and state["workflow"] in {"modify", "review", "plan"} and not direct:
            return "model_required"
        return {"modify": "plan", "plan": "plan_answer", "debug": "debugger", "analyze": "analyzer",
                "review": "reviewer", "security": "security", "test": "tester"}.get(state["workflow"], "explainer")
    graph.add_conditional_edges("retrieve", after_retrieve)
    graph.add_edge("plan", "coder")
    graph.add_conditional_edges("debugger", lambda state: "coder" if state["workflow"] == "modify" else END)
    graph.add_conditional_edges("coder", lambda state: "finalize" if engineering.generation_error else "static")
    graph.add_edge("static", "security_patch")
    graph.add_edge("security_patch", "test_patch")
    graph.add_edge("test_patch", "review_patch")
    graph.add_conditional_edges("review_patch", lambda state: "coder" if engineering.needs_repair(state["attempt"]) else "finalize")
    for name in ("explainer", "blocked", "model_required", "plan_answer", "analyzer", "reviewer", "security", "tester", "finalize"):
        graph.add_edge(name, END)
    compiled = graph.compile()
    initial: AgentState = {
        "task": request.message, "user_message": request.message, "project_id": request.project_id,
        "project_path": str(root), "selected_files": request.selected_files, "intent": Intent.ASK,
        "retrieved_context": [], "plan": [], "changes": [], "test_results": [],
        "security_results": [], "review_results": [], "attempt": max(0, engineering.attempt - 1) if resume_state and engineering.next_stage == "IMPLEMENT" else engineering.attempt, "status": "running",
        "answer": "", "confidence": "LOW", "intents": [], "workflow": "explain", "artifact": None, "change_id": None,
    }
    if resume_state:
        resumed_route = route(initial)
        initial["intent"], initial["intents"], initial["workflow"] = resumed_route["intent"], resumed_route["intents"], resumed_route["workflow"]
    runtime_token = current_runtime.set(runtime)
    try:
        async for packet in compiled.astream(initial, stream_mode=["updates", "custom"], config={"recursion_limit": 12 + 6 * settings.forge_max_repair_attempts}):
            stream_kind, update = cast(tuple[str, dict[str, Any]], packet)
            if stream_kind == "custom":
                yield "_status", update
            else:
                for node_name, values in update.items():
                    yield node_name, values
            yield "_status", {"agent": runtime.agent_name, "type": "run_diagnostics", "message": "Run diagnostics updated", **runtime.diagnostics()}
    except RunInterrupted as error:
        yield "finalize", engineering.finish(engineering.attempt, cancelled=error.cancelled,
            paused=None if error.cancelled else RuntimeStopped(str(error), "USER_PAUSED"))
    except CapabilityRequired as error:
        engineering.persist(engineering.next_stage)
        if engineering.patches:
            yield "_status", {"agent": "orchestrator", "type": "permission_required", "message": str(error),
                "artifact": {"type": "permission", "title": "Agent capability permission", "status": error.result()["status"], "data": error.result()}}
            result = engineering.finish(engineering.attempt, paused=error)
            result["status"] = error.result()["status"]
            result["task_status"] = "BLOCKED"
            yield "finalize", result
        else:
            raise
    except (RuntimeStopped, ProviderError, TimeoutError) as error:
        engineering.persist(engineering.next_stage)
        if isinstance(error, ProviderError) and not error.retryable and not engineering.patches and Orchestrator().route(request.message, request.mode).read_only:
            raise
        yield "finalize", engineering.finish(engineering.attempt, paused=error)
    except asyncio.CancelledError:
        engineering.finish(engineering.attempt, paused=ProviderError("Task interrupted safely", reason="TASK_INTERRUPTED"))
        raise
    finally:
        current_runtime.reset(runtime_token)
