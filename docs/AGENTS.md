# Forge agent responsibilities

This document describes the application's agent roles. It is not an instruction to run development subagents.

The deterministic orchestrator selects intent and workflow. Ask/Plan enforce read-only behavior. Source retrieval ranks bounded path/symbol/text evidence; repository content and historical output are untrusted data.

Read-only explainer, analyzer, planner, debugger and reviewer workflows inspect permitted source. The coder alone receives staged edit tools in addition to bounded inspection and guarded commands. Optional repository/architecture/test analysis delegates cannot recursively delegate, edit, execute or approve a parent proposal.

Coding must produce executable operations or a schema-validated concrete proposal. A plain text answer cannot finish a modification task. Empty requests or exact user-supplied content can be staged without code generation. Missing actions get one bounded structured recovery; invalid output preserves progress and remains incomplete.

Final gates run only after implementation completion. Static checks and security scanners report observed scope; model security/review opinions remain inference. Python tests need execution permission and factual exit/output evidence. A reviewer cannot save files on the developer's behalf.

Task statuses distinguish RUNNING, PAUSED, BLOCKED, COMPLETED, FAILED and CANCELLED. Staged source is not saved source. Provider interruptions retain checkpoints/cooldowns; continuation starts at the saved stage after version checks. No automatic background continuation is implemented.

See [architecture](architecture.md), [task lifecycle](task-lifecycle.md), and [editing/approval behavior](editing-and-git-upgrade.md). The README identifies future contracts and current limitations.
