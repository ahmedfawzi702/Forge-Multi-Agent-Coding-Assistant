# Contributing to Forge

Forge is a local, single-user coding environment. Preserve the distinction between proposed edits, approved disk saves, Git commits and remote pushes.

No project license has been selected. Discuss substantial contributions with the maintainer before submitting them; a public repository alone is not a grant of reuse rights.

## Development setup

Follow [installation](docs/INSTALLATION.md). Keep the existing Python and npm package managers/lockfiles. Use evidence mode or controlled provider fixtures for ordinary tests; live-provider checks can send source to an external service and consume quota.

From `backend/`, run pytest, Ruff, strict mypy and Bandit using the repository venv as shown in the README. From `frontend/`, run `npm run typecheck`, `npm run test:unit` and `npm run build`. Run `npm run smoke` with both local services available. ESLint is not configured in this version.

## Change requirements

- Keep changes focused and explain the concrete behavior before and after.
- Preserve source-version checks, role-scoped tools, permissions, local host/origin checks, bounded execution and explicit push approval.
- Cover meaningful editing, concurrency, lifecycle or permission changes with regression tests.
- Report actual checks and distinguish NOT_RUN checks, controlled provider fixtures and live verification.
- Update documentation when capabilities, configuration or operating instructions change.
- Never include `.env`, keys, private project source, application databases, source snapshots, checkpoints, generated Monaco assets or installed dependencies.

## Dependencies

Python dependency declarations belong in `backend/pyproject.toml`. Preserve platform markers for Windows/POSIX terminal packages. Runtime requirements are pinned in `backend/requirements.lock`; development pins are in `backend/requirements-dev.lock`. `requirements.txt` is the root installation entry point. See installation documentation for lock regeneration.

Use npm and retain `frontend/package-lock.json`. Monaco assets are rebuilt by postinstall/predev/prebuild and are not committed. Read `frontend/AGENTS.md` and installed Next.js documentation before changing frontend implementation.

## Pull requests and security

Describe the problem, implementation, relevant tests and limitations. Do not claim a test passed without execution evidence. Do not include API keys or raw private source in issues, screenshots or logs. Follow [SECURITY.md](SECURITY.md) for vulnerabilities.
