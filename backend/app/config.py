from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env", extra="ignore", env_file_encoding="utf-8"
    )

    database_url: str = "sqlite:///.data/forge.db"
    workspace_roots: list[Path] = Field(default_factory=lambda: [REPOSITORY_ROOT])
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    llm_provider: Literal["evidence", "ollama", "openai_compatible"] = "evidence"
    llm_model: str = ""
    llm_api_key: str = Field(default="", repr=False)
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_timeout_seconds: int = Field(default=90, ge=1, le=300)
    llm_json_mode: bool = False
    llm_max_output_tokens: int = Field(default=8192, ge=512, le=32768)
    llm_tools_enabled: bool = True
    llm_role_models: dict[str, str] = Field(default_factory=dict)
    llm_fallback_enabled: bool = False
    llm_fallback_models: list[str] = Field(default_factory=list, max_length=4)
    agent_timeout_seconds: int = Field(default=600, ge=1, le=1800)
    forge_max_agent_steps: int = Field(default=160, ge=5, le=1000)
    forge_max_tool_calls: int = Field(default=64, ge=1, le=500)
    forge_max_model_calls: int = Field(default=48, ge=1, le=200)
    forge_max_implementation_calls: int = Field(default=32, ge=1, le=200)
    forge_max_validation_calls: int = Field(default=8, ge=1, le=50)
    forge_max_test_calls: int = Field(default=4, ge=1, le=20)
    forge_max_review_calls: int = Field(default=6, ge=1, le=30)
    forge_max_context_calls: int = Field(default=12, ge=1, le=64)
    forge_max_context_file_reads: int = Field(default=8, ge=1, le=32)
    forge_max_context_searches: int = Field(default=4, ge=1, le=16)
    forge_context_rounds: int = Field(default=2, ge=1, le=6)
    forge_implementation_rounds: int = Field(default=8, ge=1, le=30)
    forge_readonly_rounds: int = Field(default=3, ge=1, le=8)
    forge_subagent_rounds: int = Field(default=2, ge=1, le=4)
    forge_max_repair_attempts: int = Field(default=3, ge=1, le=5)
    forge_max_review_revisions: int = Field(default=2, ge=0, le=3)
    forge_max_delegations: int = Field(default=2, ge=0, le=4)
    max_files: int = Field(default=3000, ge=1, le=20000)
    max_file_bytes: int = Field(default=262144, ge=1024, le=1048576)
    context_char_budget: int = Field(default=24000, ge=2000, le=64000)
    execution_timeout_seconds: int = Field(default=60, ge=1, le=180)
    execution_output_bytes: int = Field(default=65536, ge=1024, le=262144)
    state_directory: Path = Path(".data")
    max_request_bytes: int = Field(default=24 * 1024 * 1024, ge=1024, le=32 * 1024 * 1024)

    @property
    def data_directory(self) -> Path:
        return (self.state_directory if self.state_directory.is_absolute() else REPOSITORY_ROOT / self.state_directory).resolve()

    @field_validator("workspace_roots")
    @classmethod
    def resolve_roots(cls, values: list[Path]) -> list[Path]:
        if not values:
            raise ValueError("At least one workspace root is required")
        return [(p if p.is_absolute() else REPOSITORY_ROOT / p).resolve() for p in values]

    @property
    def resolved_database_url(self) -> str:
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            raw = self.database_url[len(prefix):]
            if raw != ":memory:":
                path = Path(raw)
                if not path.is_absolute():
                    path = REPOSITORY_ROOT / path
                path.parent.mkdir(parents=True, exist_ok=True)
                return prefix + path.as_posix()
        return self.database_url
