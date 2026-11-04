# Release preparation verification · 4 November 2026

These checks ran against the source prepared for the first GitHub publication. They are local results, not a claim that source has been pushed or publicly deployed.

| Check | Observed result |
| --- | --- |
| Full backend pytest | 193 passed, 1 skipped; 193.35 seconds |
| Ruff | Passed |
| Strict mypy | Passed; 100 application modules |
| Bandit | Passed |
| Clean pinned runtime installation | Passed in a separate environment; imports and dependency compatibility checked |
| Frontend TypeScript | Passed |
| Frontend unit/render checks | Passed |
| Frontend production build | Passed |
| npm audit | Zero reported vulnerabilities |
| ESLint | NOT_RUN; no configuration or script exists |
| Staged-source Gitleaks scan | No findings; generated/private data excluded |
| Source/configuration audit | No private absolute paths or known local credentials in publication files; all 39 backend settings documented |
| Browser end-to-end interactions | NOT_RUN for this preparation; historical automation limitations remain |

The skipped test requires Windows symlink privileges. No license is included, by the maintainer's choice. Local state and audit reports remain in ignored `.data/`. The final staged snapshot and initial commit history are scanned before requesting first-push approval. GitHub publication requires that explicit approval.

Historical records follow. Their counts and failures refer to the stated revisions/dates, not the current total.

---

# Task lifecycle verification · 29 October 2026

The reported zero-tool/one-model-call rate-limit pause was traced to run `c79c45db-203f-40dc-819e-67c8e417ff08`. Its seven staged entries were two files and five directories. Inherited reports and implicit completion at a loop stop caused unfinished implementation to be presented with failed final gates. [Task lifecycle report](task-lifecycle.md) documents the fix and structured contract.

| Check | Observed result |
| --- | --- |
| Full backend suite | 164 passed, 1 skipped; 151.31 seconds |
| Lifecycle acceptance/regression coverage | 17 tests, including the five requested scenarios |
| Ruff / strict mypy / Bandit | Passed; mypy checked 98 application modules |
| Frontend render/unit checks | Passed; paused controls, staged counts, NOT_RUN gates, no fabricated review score |
| Production frontend build and TypeScript | Passed |
| Final targeted lifecycle/IDE regression run | 23 passed |
| HTTP smoke after restart | Passed; connectivity, same-origin POST and cross-origin rejection |
| Actual reported run after restart | PAUSED / IMPLEMENT; 2 staged files, 5 directories, 0 applied; all final gates NOT_RUN; no review score; Apply blocked |

The five requested acceptance cases use controlled provider faults with real source staging, SQLite checkpoints, Ruff/Bandit and pytest execution. The seven-entry test verifies initial pause, a second throttled continuation with 0 tool operations/1 model call, then a successful continuation that adds only the missing README, preserves source/attempt/ChangeSet, and reaches COMPLETED awaiting Apply. Budget pause/refill, executed failing pytest, an actual dangerous-call security finding and real final-review rejection are independently asserted. Additional tests cover Retry-After dates/seconds, no request hammering, explicit configured-model switching, opt-in fallback, model-specific persisted cooldowns, cancellation/history, restart recovery, legacy failed-report normalization and final-gate/apply guards.

No extra live request was sent to the user's throttled provider for this verification. The actual reported run is normalized on read without altering its source or audit evidence. Remote model quality remains external. The Windows symlink test remains skipped because this session lacks permission. Frontend render/build checks do not establish browser interaction correctness.

The sanitized live API observation is saved locally at `.data/task-lifecycle-real-run-view.json`.

---
# Runtime progress verification · 29 October 2026

The bounded-loop failure was traced to two persisted empty-workspace runs that exhausted six read-only debugger rounds before coding. [Runtime fix report](runtime-fix.md) records the evidence, implementation, changed files, limits and five live acceptance scenarios.

| Check | Observed result |
| --- | --- |
| Full backend pytest after final runtime changes | 147 passed, 1 skipped; 94.43 seconds |
| New runtime regression tests | 20 passed |
| Ruff | Passed |
| Strict mypy | Passed; 95 application modules |
| Bandit on Forge backend | Passed; no findings |
| Frontend unit checks | Passed |
| Production Next build and TypeScript | Passed |
| Live proxy smoke after backend restart | Passed; connectivity, same-origin POST and cross-origin rejection |

The single skipped test requires symlink creation, denied by this Windows session. Tests include real files, validators, subprocesses and SQLite; scripted model decisions isolate repeat/repair/cap/outage behavior. Live acceptance used the configured OpenRouter free model and isolated state, with no generated proposal applied to originals.

Live Hello World used 2 tool operations/1 model call and printed Hello World. FastAPI used 7/7 and passed its real pytest. The login fix used 11/10 and passed six regression tests in a repository with 40 unrelated modules. Explanation used 0/1 plus one prefetched source read. JWT hit a deliberately lowered 3-operation limit after preserving three files; continuations used 12 and 4 operations and retained the same ChangeSet without repeating initial routing/context/planning. JWT application remained blocked by generated-code defects and a later reviewer timeout; its tests did not run. This demonstrates progress preservation and explicit continuation, not a successful JWT implementation.

The live JWT experiment also exposed stale-file repair progress, empty repair submissions and overbroad secret-parameter redaction. These are fixed and regression-covered. Final runtime empty-repair behavior pauses at IMPLEMENT with retained files/feedback rather than revalidating the previous implementation. The production UI retains actionable partial-run text after history reload and exposes diagnostics/resume.

Browser interaction remains unverified: the available browser-control runtime failed to initialize with an asset-path error. Production compilation and live HTTP behavior do not establish browser interaction correctness. Automatic executable validation still supports pytest; local commands are not an OS sandbox. Remote model quality/availability remain external limitations.

---
# IDE upgrade verification · 27 October 2026

Windows, Python 3.12, Node 24, SQLite and loopback services. Existing OpenRouter credentials/model were preserved. No paid fallback was selected.

| Check | Observed result |
| --- | --- |
| Backend pytest | 127 passed, 1 skipped |
| Ruff | Passed |
| Strict mypy | Passed; 92 application modules |
| Bandit on Forge backend | Passed; no findings |
| Frontend typecheck | Passed |
| Frontend unit checks | Passed |
| Production Next build | Passed |
| npm audit | 0 known vulnerabilities at verification time |

The skipped check needs symlink creation, which Windows denied. Junction behavior, POSIX PTYs, PostgreSQL and live Ollama remain unverified. These checks are not a production security audit.

## Required scenarios

The agent workflow integration tests use deterministic native-call providers to isolate orchestration from remote model availability. Filesystem writes, AST/Ruff/Bandit, pytest, Git and PTY output are real. Scripted model reports do not prove the quality of a remote model.

| Scenario | Evidence and limits |
| --- | --- |
| A · blank Hello/save | Actual HTTP create/write/read/run produced Hello; empty folder, trash restore and human PTY arithmetic also verified. Scratch/Monaco wiring builds and typechecks; browser clicks were not verified this turn. |
| B · empty calculator | Native tools created implementation, pytest tests and an empty folder in a snapshot; five real tests passed, independent scripted review gates passed, Apply and checkpoint restore worked. |
| C · inspect authentication | Native search/read tools inspected auth.py; results cited source, and AGENTS.md reached the specialist. |
| D · diagnose/fix login | Native patch changed the observed faulty comparison; two real regression tests passed. The original remained untouched before Apply. |
| E · selected code | Server-verified line selection and unsaved-buffer context reached the explanation request. The unsaved buffer did not modify disk. |
| F · current changes review | A real fixture Git repository/commit/diff reached the independent review request. A .forgeignore-excluded marker was absent. |
| G · broken implementation | A deliberately faulty native implementation failed pytest; the retained staged implementation was repaired and rerun successfully, then independently reviewed. Three-attempt bounds are also tested. |
| H · dangerous commands | Destructive commands, traversal, shell operators and unauthorized package execution were blocked. Explicitly approved safe commands ran and returned real output. |

Additional tests cover role-specific tools, full-read/exact-patch requirements, .forgeignore/secrets/traversal, global/project policy inheritance, hard deny overriding approval, manual editing independent of agent denial, structured OpenRouter/Ollama tool normalization, source/hash conflicts, later-manual-edit rollback protection, per-file rejection with subset revalidation, actual hooks with explicit approval, safe-boundary steering, total task timeout and cleanup.

## Live model result

The configured `cohere/north-mini-code:free` remained available and advertised native tools. Live OpenRouter requests used real get_tree, read/create/write, directory and command calls. The calculator run generated source/tests and actual command output. One earlier run had 14 passing tests and one failing argument-count regression; it did not pass the application gate. A malformed review response exposed a failure path; independent report submission now uses native schema-defined calls, and invalid/unavailable reports remain unverified.

The subsequent live run inspected and revised its staged implementation, ran validation and entered repair, then received an upstream 429 rate-limit response. It did **not** finish successfully or apply original files. The record is `.data/live-native-verification.json`. This partial live evidence is distinct from the deterministic full workflow tests. Remote model reliability and reasoning quality remain external limitations; the UI must show the failure rather than a fabricated success.

## Browser verification limitation

The native browser-control tool failed to initialize with `failed to write kernel assets: The system cannot find the path specified (os error 3)`, including after a reset. No replacement browser/CDP runner or fabricated screenshot was used. This turn's new UI interaction, responsive-layout and console checks are **NOT VERIFIED**. Local HTTP responses, production compilation and API/process behavior are verified separately. The older screenshots below are historical and do not depict this upgrade.

Advanced specification workflows and an actual browser-verification adapter remain incomplete. Automatic executable validation gates currently support pytest; manual Node tests/lint/typecheck/build commands are available but are separate from an automatic JS/TS test adapter. Local execution is not an OS sandbox.

---
# Local verification · 24 October 2026

Environment: Windows, Python 3.12, Node.js 24, SQLite; local FastAPI and Next.js services; existing OpenRouter configuration preserved.

| Check | Observed result |
| --- | --- |
| `pytest backend/tests -q` | 107 passed, 1 skipped |
| `ruff check backend` | Passed |
| `mypy backend/app` | Passed; strict, 71 source files |
| `bandit -r backend/app -q` | Passed; no findings |
| `npm run typecheck` | Passed |
| `npm run test:unit` | Passed; filtering, read-only picker, cancellation, permission errors and upload fallback |
| `npm run build` | Passed |
| `npm audit` | 0 known vulnerabilities at verification time |
| `npm run smoke` | Passed; health proxy, legitimate same-origin POST and cross-origin rejection |

The skipped test attempts symlink creation, which this Windows session denied. Traversal, reserved Windows paths, credential exclusions, command policy, consent, timeout, redaction, source conflicts, bounded repair, imports and request-body limits were tested separately. Windows junction behavior was not integration-tested. This is not a production security audit.

## End-to-end model and browser verification

A small owned verification fixture contained an `add` function that incorrectly subtracted and an existing pytest regression test. The browser alternate folder picker imported it as a managed source snapshot. A real OpenRouter request asked Forge to fix the function and explain the cause.

The run selected planning/debugging/coding, produced a real diff, passed static and security checks (including Bandit), and received independent model review. Apply remained disabled while pytest permission was pending. After explicit local execution approval, actual pytest passed, and the UI applied the ChangeSet to the imported snapshot. The original fixture directory retained the subtraction implementation. Test and ChangeSet cards updated to Passed/Applied and persisted across reload.

Browser checks covered native picker cancellation, directory upload fallback, source reading and file-reference navigation in Monaco, diff display, apply gating, keyboard panel resizing, assistant maximize/restore, saved panel sizes/open tabs, conversation restoration and Code/Assistant switching at a 390 × 844 responsive viewport without horizontal page overflow. Default viewport was restored afterward. A Monaco diff-model teardown issue found during testing was fixed by detaching models before disposal; opening/closing diffs and focusing/restoring panels were retested in the production build without new console errors or warnings. A preview screenshot is saved in `.data/forge-upgrade-preview.png`.

The backend suite also exercises independent mocked structured providers, a failing-test loop bounded to three implementation attempts, partial-file application, rejection/conflicts, server-verified selected lines, actual process timeout, and rejection when tests mutate indexed validation source.

Regression coverage for the reported malformed translation-app answer verifies natural “make it work…” modification routing, one format retry without replaying corrupt output, failed status after repeated malformed responses, safe legacy history/event replay, exclusion from future prompts, complete source coverage within budget, unambiguous programming-language metadata, OpenRouter reasoning exclusion/output limits, opt-in JSON response mode, and a total deadline even when a provider dribbles response chunks. Rate limits, unavailable endpoints and credit errors get specific sanitized messages. Protocol examples inside code blocks remain valid content.

The original corrupt answer was checked in the browser after the fix: it displays Failed with a clean malformed-response message, preserving the source references without showing raw protocol text. All four relevant translation-app Python files fit completely in the revised 24,000-character source budget. A live original-model retry did not finish before the test client's timeout; alternate free endpoints returned 429/404, so the configured model and credentials were retained. These external model failures are not represented as successful coding tasks or applied changes.

A final browser retry on the updated backend selected the implementation workflow (retrieval → plan → coder) and ended with a clean timeout failure at the new 90-second total provider deadline. No ChangeSet was applied. The recovered history and bounded failure are visible in `.data/forge-response-recovery.png`.

## Limits of this evidence

Live PostgreSQL and Ollama were not verified. Provider HTTP error paths use mock transports. Native directory handles vary by browser; the alternate folder picker is always exposed. Remote model output can vary or fail JSON validation; such failures do not approve changes.

Real executable project validation currently supports Python pytest; JS/TS receives Tree-sitter syntax checking, without Jest/Vitest or project typechecking. Local process containment and minimal environment are not an OS filesystem/network sandbox. Managed browser imports are snapshots, not write handles to the original selected folder.
