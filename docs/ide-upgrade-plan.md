# Forge IDE upgrade · 27 October 2026

> Historical implementation plan. The gaps described below refer to the starting state on that date. See the README and architecture documentation for current implemented capabilities and remaining limitations.

Preserve the current FastAPI/SQLAlchemy/Next.js/Monaco architecture, project scanner,
source retrieval, Auto/Ask/Plan modes, independent review, proposal gates, streaming and
provider abstraction. The current filesystem facade is read only, terminal/Git modules
are contracts, and manual drafts cannot be saved. These are implementation gaps.

## Implementation sequence

1. Workspace foundation: empty/new projects, templates, directory trees, safe manual
   create/read/save/rename/move/trash/restore, text/symbol search, diagnostics/formatting.
2. Manual IDE: scratch tabs before opening a project, Save/Save As, project/file/folder
   dialogs, explorer actions, command palette, keyboard shortcuts and bottom panels.
3. Execution and Git: workspace-scoped guarded commands, live output/input/cancellation,
   application execution, Git status/diff/stage/unstage/commit/branches and clone.
4. Agent tools: normalized provider tool calls, role-restricted ToolRegistry, autonomous
   read/search/inspection, greenfield proposals, real validation and bounded repair.
5. Collaboration with the agent: project/global rules, .forgeignore, Git/terminal/editor
   context, editable/implementable plans, safe steering and cancellation boundaries.
6. Change recovery: checkpoints before application, per-file decisions, optimistic
   rollback that preserves later manual edits, configurable local hook events.
7. Verification and polish: manual Hello/save, empty-project calculator/tests, source
   explanation/selection, debugging/repair, Git review and dangerous-command policy;
   run regression checks, build and browser QA, leave local services running.

## Boundaries

Manual editing is independent of model availability. Agent changes remain reviewable;
the coder cannot approve its output. Commands pass deterministic policy and use minimal
environments, bounded output/time and process-tree cleanup. Local execution is not an OS
sandbox. No Docker, Electron/Tauri, mandatory vector database, auto-push or fabricated
verification. Existing credentials stay backend-only. Optional specs and future browser
verification must be distinguished from implemented functionality.

## Verification record

Progress and observed results will be recorded in docs/verification.md after each stage.
