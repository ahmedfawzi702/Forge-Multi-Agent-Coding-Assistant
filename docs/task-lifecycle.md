# Task lifecycle fix · 29 October 2026

## Reported failure and cause

Persisted run `c79c45db-203f-40dc-819e-67c8e417ff08` confirms the report: IMPLEMENT paused on provider throttling with zero tool operations and one model call, retaining seven staged entries. Those entries were **two files and five directories**, with no files applied to the original workspace.

The pause handler called the ordinary final-result formatter, which attached inherited test/security/review reports and a default numeric review score. A model-round stop could also return the partially staged proposal to the final validation pipeline without an explicit implementation-complete handoff. A skipped pytest path created a `failed` TestReport even though execution never occurred. Security and review provider errors were converted into failed/unapproved reports. Startup recovery marked all interrupted runs failed. These were lifecycle and dependency errors.

## New lifecycle

`task_status` is authoritative: PENDING, RUNNING, PAUSED, BLOCKED, COMPLETED, FAILED or CANCELLED. The existing `status=proposed` remains compatible with the diff/application flow and corresponds to task_status COMPLETED: implementation and required gates finished, with human Apply still pending. PAUSED is emitted as `status=paused`, with `task_paused` events rather than `task_failed` or `task_completed`.

Every stage has a state. Implementation must explicitly complete before final static, security, test or review methods can run. Native coders call `complete_implementation` after source and requested tests are staged and no pending subtasks remain. A narrow standalone literal-print task can complete deterministically. Legacy structured proposals carry an implementation-complete declaration. Exhausted model rounds, unfinished checkpoints and provider errors never infer completion from the existence of files.

`checkpoint_implementation` records completed and pending subtasks. Every edit still persists working source automatically. Resume restores the stage, source/context/inspection cache, directories, plan/subtasks, attempt counters, ChangeSet baseline/version and provider/model selection. The current staged source and directory list are supplied to the coder. An empty original workspace is not treated as a blank implementation when a staged checkpoint exists. A repair paused after its edit can finish the same attempt without another unnecessary rewrite.

Starting/resuming unfinished implementation invalidates current final reports. Earlier reports remain in validation history and feedback; they are not presented as current failures. Incomplete implementation exposes tests/security/review as NOT_RUN and no score. Tests distinguish PASSED, FAILED, NOT_RUN and BLOCKED; preflight errors do not claim pytest failed. Security interruptions retain PARTIAL scanner evidence separately from the final model assessment. Numeric review scores exist only when an actual completed-implementation review occurred.

## Provider limits, model policy and budgets

HTTP 429 and recognized provider throttling errors carry PROVIDER_RATE_LIMIT, retryable, Retry-After seconds/date and retry_at. The failed model call does not consume a tool operation. Cooldowns are per provider endpoint/model, survive backend restart through checkpoints, and block early resume without sending a provider request. There is no scheduled retry loop.

Automatic fallback defaults **OFF**. `LLM_FALLBACK_ENABLED=true` allows at most one immediate fallback to a compatible configured model from `LLM_FALLBACK_MODELS` for a throttled call. Fallback uses the same provider/credentials; it never invents or selects an unconfigured model. Explicit Switch model can choose a configured alternate even while the original model is cooling down. Effective selection and fallback events are preserved. Endpoint changes or removal of the saved model require explicit corrective configuration/selection.

Limit reasons are separate: MODEL_CALL_LIMIT, PROVIDER_RATE_LIMIT, TOOL_CALL_BUDGET, CONTEXT_BUDGET, REPAIR_LIMIT, REVIEW_REVISION_LIMIT and GLOBAL_AGENT_STEP_LIMIT. Context exhaustion advances to implementation; unfinished implementation exhaustion pauses. Existing global tool/step defaults remain 64/160. Additional controlled allowances are documented in `.env.example`: 48 model calls, 32 implementation operations, 8 validation operations, 4 test operations, 6 review operations. Stage allowances refill on a new stage visit while global counters remain cumulative.

## API and UI

Results/checkpoints include stage states, implementation_complete, checkpoint_preserved, staged_changes, current gate reports, pause_reason, retryability/cooldown and model_selection. Checkpoints additionally retain task/run IDs, completed/pending plan and implementation steps, context/tool results, reports/history, counters and project_state_version. GET `/runs/{id}/diagnostics` exposes a safe summary. POST `/runs/{id}/resume` accepts fresh execution approval and an optional configured model. GET `/models` shows configured models, availability and fallback policy. POST `/runs/{id}/cancel` makes an unfinished task terminal while retaining staged files for inspection.

The paused card shows reason, stage, staged files, staged directories and applied files, with Resume, Switch model, Review staged changes and Cancel task. Resume observes provider cooldown. Chat history, activity events, gate cards and diff badges distinguish pause/unexecuted gates from failure. The old reported run is normalized on read as PAUSED with two staged files, five directories, zero applied files and NOT_RUN final gates; its original audit/checkpoint reports are retained.

Apply and manual final validation reject incomplete implementations. Approval of local tests continues the saved validation pipeline, so a later reviewer outage pauses at REVIEW with actual test output retained. Backend restart recovers checkpointed running tasks as PAUSED, never as fabricated code failures. Cancelled tasks cannot resume. Completion hooks do not run for paused tasks.

## Acceptance evidence

Automated fault injection controls model behavior; source staging, persistence, AST/Ruff/Bandit and pytest execution are real. Tests do not depend on remote provider availability and do not send extra requests to the user's throttled model.

| Required scenario | Observed result |
| --- | --- |
| Seven staged entries, provider 429, resume, finish | Two files + five directories preserved; a second throttled continuation recorded 0 tool operations/1 model call. Final gates stayed NOT_RUN. Successful continuation wrote only the missing README, retained existing files/directories and the same ChangeSet/attempt, passed actual pytest/security/review and reached COMPLETED awaiting Apply. |
| Implementation tool budget expires | PAUSED / TOOL_CALL_BUDGET with all seven entries retained and gates NOT_RUN. Fresh continuation allowance completed the missing work and passed tests. |
| Pytest really executes and fails | Tests FAILED with actual exit code 1/output; bounded repair limit reported separately. |
| Security scan finds a real dangerous call | Security FAILED with the observed eval finding; pytest never ran and remained NOT_RUN. |
| Final reviewer rejects complete code | Review NOT_APPROVED with the actual returned score, after completed implementation and executed tests. |

Additional coverage verifies Retry-After seconds and HTTP dates, no retry hammering, per-model cooldowns, opt-in fallback, explicit configured model switch, invalid-model rejection, gate/apply guards, legacy report presentation, security partial evidence, cancellation/history, restart/resume and cooldown recovery, and stage-budget refill without resetting global counters. Frontend render checks assert paused controls/counts, NOT_RUN gates and absence of a fabricated score. Full verification totals are recorded in `docs/verification.md`.

Remaining limits: automatic fallback supports configured models on the same provider endpoint, not a second provider account/endpoint. Provider quality/availability remain external constraints. Completion is a declared handoff followed by deterministic gates and independent model review, not a proof that every semantic requirement is satisfied. Local commands are not an OS sandbox. Browser interaction remains unverified where the control runtime is unavailable; render/build/HTTP checks are separate evidence.

Post-restart HTTP verification of the actual reported run returned PAUSED / IMPLEMENT, implementation_complete=false, 2 staged files, 5 staged directories, 0 applied files, tests/security/review NOT_RUN, no score, and can_apply=false. The observation is saved in `.data/task-lifecycle-real-run-view.json`. GET `/models` confirmed automatic fallback remains OFF; no extra provider request was issued.
