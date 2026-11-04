# Editing, approval and Git upgrade

Forge keeps agent changes in a disposable workspace and a persisted ChangeSet. Saving approved changes, committing, and pushing are separate operations. This upgrade extends that implementation rather than replacing it.

## Failure evidence and root causes

The latest persisted failures `e9702a6a-6bc4-47e5-ba77-3b4e0d3fbbef` and `60903fc6-5e12-4760-b124-0c891b1154fd` paused in IMPLEMENT with zero staged files. Their events contain model responses followed by IMPLEMENT_NOW; no successful editing operation was recorded. Raw model payloads were not retained, so those records do not establish the exact upstream response shape.

Code inspection found that the recovery submission used `CodeProposal`, whose `files` and `directories` defaulted to empty lists and whose unknown keys were ignored. A summary-only object could pass schema validation and fail later with “no new edits.” The recovery request also described the editing submission as an independent assessment. The same path could repeat schema attempts before identifying missing executable actions.

`ImplementationProposal` now rejects empty submissions, unknown top-level keys, and ambiguous file operations. Both legacy structured coding and native recovery validate this executable contract. Native editing remains the primary path; a prose-only response gets one structured recovery submission, executed through the same real backend tools. Invalid recovery produces a typed diagnostic while preserving checkpoints. Provider interruptions retain their original rate-limit/authentication metadata.

Two other gaps affected simple operations: exact supplied code and empty-file creation unnecessarily required code generation; and selected text, columns and base hashes were dropped by the frontend. Exact content now uses backend staging directly. Selection metadata reaches the backend, which checks disk versions and selected text, and rejects modifications outside the selected source range. UTF-16 editor columns are translated correctly for Unicode source. Unsaved buffers remain drafts, not saved source.

Git previously implemented only init, status, diff, stage, unstage, commit and branch creation. It disabled every credential helper, including for private clones. Remote operations and branch switching were missing. The new network path permits system/global credential helpers, resets repository-provided helpers, disables hooks and interactive prompts, verifies TLS, restricts protocols to HTTPS and avoids repository-configured push refspecs. Credential values are never requested, stored, or passed to a model.

The public GitHub clone check exposed an additional gap: an extensionless README was omitted from indexing. Common extensionless documentation names are now indexed.

## Implemented behavior

- Native create/write/exact patch/move/delete/directory tools produce real staged filesystem operations. Writes are read back for verification. Read-only metadata and existence tools, plus named move/rename/delete aliases, are available within role permissions.
- Deterministic requests accept a narrowly matched empty-file instruction or an exact fenced code block addressed to one file. This parser does not interpret model Markdown or guess an implementation. Existing create targets are rejected.
- Agent proposals open in the Monaco diff view after a task ends when there is no dirty editor buffer. Proposal card file buttons open the staged diff rather than attempting to read an unsaved path from disk.
- The review view offers Save All Changes, Save this file, rejection and discard. Existing static, security, tests and review gates remain enforced. Only empty new files/directories receive an explicit “tests not applicable” result for having no executable behavior.
- Successful saves refresh clean editor buffers, Explorer and Git state; dirty buffers are preserved. Conflicts offer current-file review, regeneration, keeping manual changes, and cancellation. The underlying optimistic concurrency checks prevent silent overwrite.
- Checkpoints now retain task/conversation IDs, original/new hashes, reasons, diffs and validation reports. History offers detail inspection and conflict-checked restore independently of Git. Older checkpoint records remain readable.
- Monaco adds Ask Forge, Explain, Fix, Refactor, Review, Generate Tests and Add Documentation context actions. Manual Ctrl+S, scratch files, Save As, tabs, dirty indicators, formatting, search, rename/trash, and undo remain separate from agent approval.
- Clone supports an optional branch. A successful clone is scanned and opened as a real workspace.
- Source control adds local branch switching, branch/history/upstream inspection, fetch, fast-forward pull, confirmed push, and base/current/incoming conflict inspection with a Monaco comparison. Resolution is edited in the working file, reviewed, saved and staged by the user.
- Push confirmation names the verified URL, branch and commit. The backend rechecks those values and never force-pushes. Success is returned only after Git succeeds and `ls-remote` confirms the expected commit. Receive/authentication failures are failures, not success notifications.
- Commit-message and PR-description suggestions use filtered/redacted diffs. PR descriptions are explicitly labeled as drafts; Forge does not create GitHub PRs.

## Verification

`backend/tests/test_edit_contract.py` exercises prose recovery, bounded invalid submissions, exact/empty creation, disk approval, Explorer state, selected-function preservation, discard, stale selections, Unicode columns, history metadata, and protection against later manual saves/reverts.

`backend/tests/test_git_remote_workflow.py` runs real Git CLI operations against owned temporary repositories. HTTPS transport is substituted with a local bare repository only in the tests. It verifies branch/edit/stage/commit/push/fetch/pull, the remote commit, blocked unconfirmed/stale pushes, dirty-worktree protection, receive rejection, actual merge conflicts/resolution, URL/branch validation, and helper restrictions. These tests do not claim an authenticated GitHub push occurred.

The existing lifecycle, editing, execution, provider, checkpoint and safety suites remain part of validation, including HTTP 429 preservation/resumption and staged calculator projects with executed regression tests.

Live public clone: `https://github.com/octocat/Hello-World.git`, branch `master`, clean Git state, README indexed. Sanitized evidence: `.data/verification/public-git-clone-check.json`. No push was attempted to that repository.

Live configured-model editing also succeeded. `live-edit-check.json` records a real native create tool call for hello.py followed by approval and a verified saved file. `live-existing-edit-check.json` records calculator.py being extended with subtraction while preserving its original add function, a new test_calculator.py, real pytest exit 0, passing required gates and approved disk application. The original calculator remained unchanged until approval. Both records are in `.data/verification/`.

The full backend suite completed with **192 passed, 1 skipped** before the final additional no-model empty-file test. The skipped test requires Windows symlink privileges. After the final empty-file path changes, **51 targeted tests passed** covering the edit contract, workflow, engineering and lifecycle. These overlap with the full suite and are not an additional 51 distinct tests. Ruff, strict mypy (100 source modules), Bandit, frontend unit/render checks, the final production build/type checking and final proxy smoke checks passed.

The live existing-file scenario executed **4 pytest tests, all passed**, before its save. The final same-origin API check also created and approved an empty blank.py with **zero model calls**, correctly labeling tests NOT_APPLICABLE, and confirmed HTTP 200 plus backend health. Evidence: `.data/verification/final-app-check.json`. The app was restarted with the final source/build and left running at `http://127.0.0.1:3000/`.

## Source files changed

- Action contract and recovery: `backend/app/schemas/engineering.py`, `backend/app/agents/coder.py`, `backend/app/agents/structured.py`, `backend/app/tools/registry.py`, `backend/app/services/direct_edits.py`, `backend/app/graph/engineering.py`, `backend/app/graph/task_profile.py`.
- Selection/version protection: `backend/app/schemas/domain.py`, `backend/app/services/selection.py`, `backend/app/graph/workflow.py`, `frontend/types/index.ts`, `frontend/hooks/use-chat.ts`, `frontend/editor/code-editor.tsx`, `frontend/editor/editor-workspace.tsx`, `frontend/components/workspace.tsx`.
- Approval/history: `backend/app/services/checkpoints.py`, `backend/app/services/proposals.py`, `backend/app/api/workspace.py`, `frontend/hooks/use-editor.ts`, `frontend/editor/diff-workspace.tsx`, `frontend/editor/code-diff.tsx`, `frontend/chat/tool-result-card.tsx`, `frontend/components/workspace/checkpoints-panel.tsx`.
- Git and project indexing: `backend/app/services/git.py`, `backend/app/api/git.py`, `backend/app/schemas/workspace.py`, `backend/app/execution/commands.py`, `backend/app/code_intelligence/repository_scanner.py`, `frontend/components/workspace/git-panel.tsx`, `frontend/components/workspace/new-project-dialog.tsx`.
- Verification and documentation: `backend/tests/test_edit_contract.py`, `backend/tests/test_git_remote_workflow.py`, `backend/tests/test_progress_runtime.py`, `frontend/app/globals.css`, `README.md`, and this document.

## Configuration and limits

- Git must be on PATH. For private HTTPS repositories, authenticate outside Forge using an installed Git credential helper (for example Git Credential Manager), or configure GitHub CLI with `gh auth setup-git`. No password/token field is provided in Forge.
- Open/create destinations remain subject to WORKSPACE_ROOTS. The clone dialog combines the selected parent location and project name. SSH remotes are deliberately unsupported by this network implementation.
- A configured model is required to generate code and independent model reviews. Empty/exact content staging does not invoke the coder model; independent applicable gates still run. New empty files/directories use explicit deterministic structural checks and need zero model calls, including in evidence mode.
- Tests execute only under the existing command guard and permission policy in disposable workspaces. This is not an OS sandbox; no Docker is introduced. Unexecuted tests are never reported as passed.
- An authenticated push to a user-owned GitHub repository requires an actual destination and the user's explicit action. It has not been verified against a user's GitHub account in this session.
- PR creation, hunk-level Git staging and AST rewriting are not implemented. PR drafting covers current working changes, not committed branch history. Pull is fast-forward only; divergent branches remain untouched and require a deliberate separate reconciliation.
- Browser UI automation ended because the computer-use runtime could not confidently determine the browser URL. Type checking, production builds, render/unit checks and HTTP checks do not replace full interactive browser end-to-end coverage.
