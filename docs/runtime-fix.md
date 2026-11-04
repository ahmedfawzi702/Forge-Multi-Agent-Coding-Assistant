# Progress-oriented runtime fix · 29 October 2026

## Verified root cause

This was an orchestration failure, not an oversized user task. Persisted runs `23aa9088-a0d1-4418-91ac-c776e9673307` and `42c66ba2-cc27-480a-9fe8-ba1687bc1e97` were empty-workspace implementation requests. The phrase “Fix any errors you discover” also selected DEBUG. The old modification graph routed PLAN → read-only DEBUGGER → CODER. The debugger's six-round native-tool loop exhausted its allowance before reaching CODER and raised “The bounded tool loop reached its limit.” Both runs performed six inspection operations, created zero files and failed.

The first trace was get_tree → list_directory → read_file → search_files → read_file → list_directory. The second was get_tree → list_directory → list_directory → search_files → load_rules → read_file. Some reads targeted a directory. No duplicate-result cache or context-to-implementation transition stopped that pattern. The coder also used shared inspection/edit rounds, repairs constructed fresh tool budgets, retrieval opened the entire inventory to score content, and each chat refreshed the full index. A proposal was persisted only after the coding loop returned.

## Resulting behavior

Modification runs now follow UNDERSTAND → bounded CONTEXT → one PLAN → IMPLEMENT → VALIDATE → TEST → REVIEW → FINALIZE. Modification no longer waits for a mandatory read-only debugger. Empty repositories skip source exploration. Source metadata ranks paths, symbols and dependencies before opening a bounded set of files. Selected-function explanation uses supplied evidence and one completion; it does not invoke coding, testing or security specialists.

Inspection has independent call/read/search/round limits. Identical successful requests reuse stamped results; the third duplicate signals REPEATED_TOOL_CALL and forces progression. Source edits or ignore-policy changes invalidate caches. Once context is sufficient, the model gets editing tools with limited targeted reads. After two nonproductive implementation rounds, a schema-only concrete proposal is required. Repairs must produce a new edit; files retained from an earlier attempt cannot count as fresh repair progress. Validation and tests run in their deterministic stages, avoiding model-controlled repeated test execution.

Each edit immediately updates a persisted working ChangeSet. Working/partial files cannot be applied until validation gates pass. Run checkpoints preserve plan, source evidence, inspected resources, staged files/baseline, reports, attempts, feedback and next stage. Explicit resume acquires a continuation lease, checks source/staged hashes, honors fresh permissions, and starts at the saved stage. Review outages resume at REVIEW; pending test permission resumes at TEST. Changed original/staged source, conflicting new paths, and simultaneous continuations are rejected. No background task automatically resumes a run.

The literal-print Python fast path accepts only a new standalone module whose AST contains print calls with constant arguments. It performs syntax/source-security checks, optionally executes the script, and labels its review as deterministic structural verification. Other code follows the normal gates. Redaction preserves typed injected-secret parameters and valid JSON while masking literal credentials; literal-secret detection is not a complete security analysis.

## Configuration and diagnostics

All values are configurable in the root `.env`; restart the backend after changing settings. Defaults are documented in `.env.example`.

| Setting | Default |
| --- | ---: |
| FORGE_MAX_AGENT_STEPS | 160 |
| FORGE_MAX_TOOL_CALLS | 64 |
| FORGE_MAX_CONTEXT_CALLS | 12 |
| FORGE_MAX_CONTEXT_FILE_READS | 8 |
| FORGE_MAX_CONTEXT_SEARCHES | 4 |
| FORGE_CONTEXT_ROUNDS | 2 |
| FORGE_IMPLEMENTATION_ROUNDS | 8 |
| FORGE_READONLY_ROUNDS | 3 |
| FORGE_SUBAGENT_ROUNDS | 2 |
| FORGE_MAX_REPAIR_ATTEMPTS | 3 total implementation attempts, including the first |
| FORGE_MAX_REVIEW_REVISIONS | 2 |
| FORGE_MAX_DELEGATIONS | 2, read-only; recursive delegation unavailable |

The global step/tool limits are last-resort guards shared by graph nodes, providers, validators and delegates. Time/output limits still apply. A hard stop reports its stage, operation/model counts, preserved file count and cause, with an explicit continuation option.

Chat results, the expandable diagnostics UI and GET `/runs/{id}/diagnostics` expose total_steps, llm_calls, tool_calls, tool_requests, read_calls, search_calls, write_calls, execution_calls, test_calls, retry_count, cache_hits, blocked_calls, repeated_calls, agent_name, current_stage, last_tool, complexity, limits and stage history. They contain no private model reasoning. GET `/runs/{id}` exposes a safe checkpoint summary; POST `/runs/{id}/resume` or streamed chat with `resume_run_id` continues it.

`tool_calls` counts dispatched tool operations and fixed validation/hook commands, including operations that return errors. Cached and budget-rejected requests are separately counted. Prefetched source reads count in `read_calls` without becoming native tool calls. Snapshot copying and integrity hashing are safety operations, not model exploration; they still touch the bounded indexed baseline. A counter total is per run; resumed runs have fresh counters and retain parent records.

## Live acceptance evidence

The configured OpenRouter provider, existing new credential and `cohere/north-mini-code:free` were used. No alternate or paid model was selected. The runner creates isolated projects/state and never applies generated changes. These are actual model calls, source operations and local validators, separate from scripted-provider regression tests.

| Scenario | Native/validation tool operations | Model calls | Observed result |
| --- | ---: | ---: | --- |
| Empty hello.py | 2 | 1 | One file created; actual execution printed Hello World. No reads/searches. Applicable proposal. |
| Empty FastAPI /health + pytest | 7 | 7 | Two files; one real pytest passed; validation/review passed. No searches. |
| Existing login bug, 40 unrelated modules | 11 | 10 | Task-local context, two writes, six source reads including staged reads, zero searches. One repair; six pytest regressions passed; applicable proposal. |
| Explain selected function | 0 | 1 | One prefetched source read; direct explanation. No coder, test execution or security agent. |
| JWT with deliberate 3-operation global limit | 3 before pause | 4 before pause | Three files persisted in one ChangeSet; IMPLEMENT checkpoint preserved. Explicit continuation reused that same ChangeSet and skipped UNDERSTAND/CONTEXT/PLAN. |

JWT's first continuation used 12 operations/13 model calls and preserved the same three files. Validation blocked application: missing test imports, a hardcoded production-secret fallback and algorithm validation issues remained. Tests did not execute because static/security checks failed. This run exposed the stale-file repair-progress bug and typed-parameter redaction problem, both subsequently fixed with regression coverage. A further continuation used 4 operations/5 model calls, retained the same ChangeSet, and remained blocked with a reviewer timeout. It also exposed an empty structured repair submission; that now pauses at IMPLEMENT with explicit feedback instead of revalidating old files. These safeguards are covered by regression tests. Across the JWT experiment: 3 → 12 → 4 operations, 4 → 13 → 5 model calls; three files remained preserved throughout. A preserved JWT proposal is not claimed production-ready, tested successfully or applied.

Raw local evidence is under `.data/runtime-acceptance/20261029-134838/`: per-scenario JSON includes public results, events, diffs and reports; `summary.json` contains counters. `backend/scripts/runtime_acceptance.py` reproduces the five scenarios with isolated state. The `--resume DIRECTORY RUN_ID` option records another explicit continuation.

## Files changed

| Area | Files |
| --- | --- |
| Runtime and graph | `backend/app/graph/runtime.py`, `task_profile.py`, `workflow.py`, `engineering.py`, `inspection.py`, `state.py` |
| Tools and retrieval | `backend/app/tools/registry.py`, `backend/app/code_intelligence/retriever.py` |
| Persistence and API | `backend/app/models/entities.py`, `services/run_checkpoints.py`, `services/chat.py`, `services/proposals.py`, `schemas/domain.py`, `api/routes.py` |
| Provider/validation measurement | `backend/app/llm/base.py`, `llm/providers/http.py`, `agents/structured.py`, `execution/process.py`, `services/hooks.py` |
| Source redaction and typing | `backend/app/security/redaction.py`, `security/policy.py`, `api/terminal.py` |
| UI | `frontend/hooks/use-chat.ts`, `frontend/chat/assistant-panel.tsx`, `frontend/types/index.ts` |
| Configuration/docs | `backend/app/config.py`, `.env.example`, `README.md`, `docs/architecture.md`, `docs/verification.md`, this report |
| Verification | `backend/tests/test_progress_runtime.py`, `test_workflow.py`, `test_ide_agent_flows.py`, `backend/scripts/runtime_acceptance.py` |

## Verification and remaining limits

Regression coverage exercises duplicate detection/invalidation, source-read/search budgets, exact stage transitions, empty/small-edit/explanation paths, format and repair bounds, review revision caps, live early ChangeSets, provider interruption, global limits, saved-stage resume, stage/source conflicts, continuation leases, fresh execution permission, stale repair progress and typed-secret redaction. Files, validators, subprocess output and SQLite persistence are real; fault-injected provider decisions isolate orchestration behavior from model availability.

Frontend unit checks, production compilation/typechecking and live proxy smoke checks passed. Ruff, strict mypy on 95 application modules and Bandit passed. Final backend suite results are recorded in `docs/verification.md`.

Remote model quality, rate limits and invalid reports remain external constraints. Failed gates retain evidence and block application. Executable project validation supports pytest; automatic JS/TS execution adapters are still absent. Continuation is explicit, not a durable background queue. Snapshot/hash work still scales with the bounded index. Browser interaction was not verified because the available control runtime failed to initialize; HTTP/build checks are separate evidence. Local execution is not an OS sandbox; PostgreSQL and live Ollama were not exercised.
