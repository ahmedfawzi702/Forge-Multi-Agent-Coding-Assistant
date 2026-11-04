from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Intent(StrEnum):
    ASK = "ASK"
    EXPLAIN = "EXPLAIN"
    CODE = "CODE"
    EDIT = "EDIT"
    DEBUG = "DEBUG"
    TEST = "TEST"
    REVIEW = "REVIEW"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    PLAN = "PLAN"
    REFACTOR = "REFACTOR"
    PROJECT_ANALYSIS = "PROJECT_ANALYSIS"


class FileEntry(BaseModel):
    path: str
    language: str
    size: int


class CodeSymbol(BaseModel):
    id: str
    name: str
    type: str
    file_path: str
    language: str
    start_line: int
    end_line: int
    signature: str = ""
    docstring: str | None = None
    parent: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectMap(BaseModel):
    language: list[str]
    framework: list[str]
    entry_points: list[str]
    dependencies: list[str]
    files: list[FileEntry]
    important_directories: list[str]
    symbols: list[CodeSymbol]
    architecture_summary: str
    warnings: list[str] = Field(default_factory=list)
    scanned_at: str
    source_kind: Literal["local", "browser", "managed"] = "local"
    directories: list[str] = Field(default_factory=list)
    testing_framework: list[str] = Field(default_factory=list)
    database_layer: list[str] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)


class Evidence(BaseModel):
    file: str
    start_line: int
    end_line: int
    sha256: str


class ContextChunk(BaseModel):
    evidence: Evidence
    content: str
    total_lines: int | None = Field(default=None, ge=1)


class ProjectOpen(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class ProjectView(BaseModel):
    id: str
    name: str
    path: str
    project_map: ProjectMap
    source_kind: Literal["local", "browser", "managed"] = "local"
    permission: str = "Manual editing enabled; agent changes require review and approval"


ChatMode = Literal["auto", "ask", "plan", "explain", "edit", "debug", "test", "review", "agent", "security_review"]


class SelectedCode(BaseModel):
    file: str = Field(min_length=1, max_length=1024)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    start_column: int = Field(default=1, ge=1)
    end_column: int | None = Field(default=None, ge=1)
    text: str | None = Field(default=None, max_length=100000)
    base_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class EditorDraft(BaseModel):
    file: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=262144)
    base_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ChatRequest(BaseModel):
    project_id: str
    resume_run_id: str | None = None
    model: str | None = Field(default=None, min_length=1, max_length=200)
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=12000)
    mode: ChatMode = "auto"
    selected_files: list[str] = Field(default_factory=list, max_length=8)
    level: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    selected_code: SelectedCode | None = None
    allow_execution: bool = False
    editor_draft: EditorDraft | None = None
    working_drafts: list[EditorDraft] = Field(default_factory=list, max_length=8)
    context_notes: str = Field(default="", max_length=24000)
    approvals: list[str] = Field(default_factory=list, max_length=16)


class ToolResult(BaseModel):
    type: str
    title: str
    status: str
    data: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    run_id: str
    conversation_id: str
    intent: Intent
    status: Literal["pending", "running", "paused", "cancelled", "completed", "unsupported", "failed", "partial", "proposed", "awaiting_approval", "blocked"]
    answer: str
    evidence: list[Evidence]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    provider: str
    intents: list[Intent] = Field(default_factory=list)
    artifacts: list[ToolResult] = Field(default_factory=list)
    change_id: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    resumable: bool = False
    task_status: Literal["PENDING", "RUNNING", "PAUSED", "BLOCKED", "COMPLETED", "FAILED", "CANCELLED"] = "COMPLETED"
    stage: str = "FINALIZE"
    stage_states: dict[str, str] = Field(default_factory=dict)
    implementation_complete: bool = False
    checkpoint_preserved: bool = False
    staged_changes: dict[str, int] = Field(default_factory=dict)
    static_validation: dict[str, Any] = Field(default_factory=dict)
    tests: dict[str, Any] = Field(default_factory=dict)
    security: dict[str, Any] = Field(default_factory=dict)
    review: dict[str, Any] = Field(default_factory=dict)
    pause_reason: str | None = None
    retryable: bool = False
    retry_after_seconds: float | None = None
    retry_at: str | None = None
    model_selection: dict[str, Any] = Field(default_factory=dict)


class AgentEvent(BaseModel):
    type: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    agent: str | None = None
    status: str | None = None
