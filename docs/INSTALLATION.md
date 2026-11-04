# Installation and local operation

The [README](../README.md) contains the complete quick start. These notes explain dependency reproducibility and service ownership.

## Backend dependencies

Use Python 3.11+. From the repository root, create `.venv` and install `requirements.txt`. This installs the exact runtime pins in `backend/requirements.lock` and the editable backend package. Import paths and bundled agent prompt files then work consistently. The Uvicorn `--app-dir backend` option also makes the source location explicit.

Development checks additionally require `backend/requirements-dev.lock`. The original development lock is retained. Runtime pytest/Ruff/Bandit are intentional: Forge invokes these validators itself. Windows uses pywinpty; POSIX uses ptyprocess. PostgreSQL is optional via the backend `postgres` extra and is not part of the default SQLite setup; live PostgreSQL and migrations are not verified.

To regenerate compatible pins intentionally with uv:

```text
uv pip compile backend/pyproject.toml --extra dev --universal --output-file backend/requirements-dev.lock
uv pip compile backend/pyproject.toml --constraint backend/requirements-dev.lock --universal --output-file backend/requirements.lock
```

Review dependency changes and repeat tests. Do not replace lockfiles with a host-wide pip freeze. `uv pip check --python .venv/Scripts/python.exe` checks the installed environment. Use `.venv/bin/python` on POSIX.

## Frontend dependencies

Use Node 20.9+ and npm. Run `npm ci` inside `frontend/`; it uses the existing lockfile. Postinstall/predev/prebuild bundle local Monaco editor/worker assets into `frontend/public/monaco/`. Those generated assets are excluded from source control. Tailwind 4 uses the existing PostCSS plugin; no separate Tailwind configuration file is required by this implementation.

## Configuration

Copy the root `.env.example` only when a local `.env` does not already exist. See [all settings](configuration.md). Backend relative workspace/state/database paths resolve from the checkout. The default workspace root allows this checkout; explicitly configure other project roots you intend to edit.

Optional frontend environment settings belong in `frontend/.env.local`, based on its own `.env.example`. Neither frontend variables nor NEXT_PUBLIC variables should contain a provider credential.

## Service commands

Run backend and frontend in separate terminals as documented in the README. A production Next build is still a local service; public deployment is not implemented.

On Windows, `./start-forge.ps1` requires an installed backend and an existing frontend production build. It reuses healthy loopback services and starts missing services in hidden processes. `scripts/serve-backend.mjs` owns the backend process and retries unexpected exits with bounded backoff. The launcher refuses to replace an unrelated unhealthy port owner.

Logs and process records are under `.data/`. To stop a background instance, inspect `.data/running-services.json` and `.data/backend-supervisor.json`, verify the recorded process identities, stop the supervisor first and then its owned backend/frontend processes. Stopping only a supervised backend causes a restart. Never stop unrelated Python/Node processes indiscriminately.

## Troubleshooting

- Backend unavailable: check `/health`, port 8000 and `.data/forge-api.stderr.log`; confirm the correct venv/package is installed.
- UI unavailable: check port 3000 and frontend logs; rebuild and restart Next after frontend changes.
- Model errors: check the configured provider/model and local credentials. Resume a preserved checkpoint only after cooldown; do not assume availability guarantees quality.
- Workspace rejected: configure the intended parent in WORKSPACE_ROOTS. Browser picker imports remain copies.
- Save conflict: review the current source and regenerate/resolve the proposal; do not overwrite newer manual edits.
- Private clone/push failure: authenticate outside Forge using system/global Git credential helpers. SSH remotes are unsupported.
