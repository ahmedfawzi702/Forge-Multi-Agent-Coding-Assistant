# Configuration reference

Backend settings are defined in `backend/app/config.py`. They are case-insensitive environment names; the root `.env` is loaded by Pydantic Settings. No actual `.env` or credential value belongs in Git. Restart the backend after changes. JSON arrays/maps must be valid JSON.

## Storage and source access

| Variable | Default | Purpose |
| --- | --- | --- |
| DATABASE_URL | `sqlite:///.data/forge.db` | SQLAlchemy database URL. Relative SQLite paths resolve from the checkout. |
| WORKSPACE_ROOTS | `["."]` in example | Permitted project roots. Relative entries resolve from the checkout; managed state does not grant access elsewhere. |
| CORS_ORIGINS | `["http://localhost:3000","http://127.0.0.1:3000"]` | Accepted local browser origins. Host restrictions still apply. |
| STATE_DIRECTORY | `.data` | Private managed projects, snapshots, run artifacts, checkpoints and other local state. |
| MAX_FILES | `3000` | Maximum indexed file count. |
| MAX_FILE_BYTES | `262144` | Maximum supported source file size in bytes. |
| CONTEXT_CHAR_BUDGET | `24000` | Bounded source/context budget. |
| MAX_REQUEST_BYTES | `25165824` | API body limit. |

## Model connection

| Variable | Default | Purpose |
| --- | --- | --- |
| LLM_PROVIDER | `evidence` | One of evidence, ollama or openai_compatible. |
| LLM_MODEL | empty | Endpoint-specific model name; required for model generation. |
| LLM_API_KEY | empty | Backend-only provider credential. Never put it in frontend settings. |
| LLM_BASE_URL | `http://127.0.0.1:11434` | Ollama or compatible endpoint base URL. OpenRouter uses `https://openrouter.ai/api/v1`. |
| LLM_TIMEOUT_SECONDS | `90` | Provider deadline; constrained to 1–300 seconds. |
| LLM_JSON_MODE | `false` | Enable JSON response mode only when supported by the endpoint. |
| LLM_MAX_OUTPUT_TOKENS | `8192` | Output token setting used where supported; 512–32768. |
| LLM_TOOLS_ENABLED | `true` | Native tool-calling capability setting. The selected model must actually support tools. |
| LLM_ROLE_MODELS | `{}` | Optional role-to-model JSON map; unspecified roles use LLM_MODEL. |
| LLM_FALLBACK_ENABLED | `false` | Opt into the configured fallback policy. |
| LLM_FALLBACK_MODELS | `[]` | At most four explicit alternatives using the same provider/credentials. |

No native Anthropic/Gemini adapter or provider-specific API-key variable is implemented. A compatible endpoint is not proof that every model supports every capability. Do not include credentials inside the base URL.

## Workflow budgets

| Variable | Default | Purpose |
| --- | --- | --- |
| AGENT_TIMEOUT_SECONDS | `600` | Overall task deadline, 1–1800 seconds. |
| FORGE_MAX_AGENT_STEPS | `160` | Global last-resort graph/runtime step cap. |
| FORGE_MAX_TOOL_CALLS | `64` | Global dispatched operation cap. |
| FORGE_MAX_MODEL_CALLS | `48` | Global model request cap. |
| FORGE_MAX_IMPLEMENTATION_CALLS | `32` | Per-visit implementation operation allowance. |
| FORGE_MAX_VALIDATION_CALLS | `8` | Validation operation allowance. |
| FORGE_MAX_TEST_CALLS | `4` | Test operation allowance. |
| FORGE_MAX_REVIEW_CALLS | `6` | Review operation allowance. |
| FORGE_MAX_CONTEXT_CALLS | `12` | Read/search context operation allowance. |
| FORGE_MAX_CONTEXT_FILE_READS | `8` | Bounded task-local file reads. |
| FORGE_MAX_CONTEXT_SEARCHES | `4` | Context searches. |
| FORGE_CONTEXT_ROUNDS | `2` | Initial inspection rounds before implementation. |
| FORGE_IMPLEMENTATION_ROUNDS | `8` | Native coder loop rounds. |
| FORGE_READONLY_ROUNDS | `3` | Read-only specialist loop rounds. |
| FORGE_SUBAGENT_ROUNDS | `2` | Bounded delegated inspection rounds. |
| FORGE_MAX_REPAIR_ATTEMPTS | `3` | Total implementation attempts, including the first. |
| FORGE_MAX_REVIEW_REVISIONS | `2` | Review-driven revision cap. |
| FORGE_MAX_DELEGATIONS | `2` | Maximum isolated analysis delegations. |

These limits do not turn partial work into completed implementation. Pauses preserve staged work, while final gates remain NOT_RUN until completion. Increasing limits is not a substitute for diagnosing missing actions.

## Process execution

| Variable | Default | Purpose |
| --- | --- | --- |
| EXECUTION_TIMEOUT_SECONDS | `60` | Guarded command/validation duration, 1–180 seconds. |
| EXECUTION_OUTPUT_BYTES | `65536` | Captured process output cap. |

Task preferences and per-run approval still determine whether execution is allowed. These settings provide resource bounds, not OS isolation. Ordinary OS runtime variables such as PATH, SystemRoot and temporary-directory variables are not Forge credentials/configuration and are filtered for subprocess use.

## Frontend and smoke runner

| Variable | Default | Where to set it |
| --- | --- | --- |
| FORGE_BACKEND_URL | `http://127.0.0.1:8000` | Optional server-only `frontend/.env.local`; used by the Next API proxy. |
| FORGE_SMOKE_URL | `http://127.0.0.1:3000` | Shell environment for `npm run smoke`; used by its Node script. |

The root backend `.env` is not loaded by Next.js or the plain Node smoke script. Restart Next after frontend environment changes. Never use NEXT_PUBLIC variables for provider credentials.
