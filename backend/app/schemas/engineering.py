from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImportedFile(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=262144)


class ProjectImport(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    files: list[ImportedFile] = Field(max_length=3000)


class ProposedFile(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    content: str | None = Field(default=None, max_length=262144)
    search: str | None = Field(default=None, max_length=30000)
    replace: str | None = Field(default=None, max_length=60000)
    reason: str = Field(min_length=1, max_length=2000)
    delete: bool = False


class CodeProposal(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)
    files: list[ProposedFile] = Field(default_factory=list, max_length=64)
    directories: list[str] = Field(default_factory=list, max_length=64)
    implementation_complete: bool = True
    pending_steps: list[str] = Field(default_factory=list, max_length=64)


class ImplementationProposal(CodeProposal):
    """An executable submission, not a prose report with silently ignored keys."""
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def executable(self) -> "ImplementationProposal":
        if not self.files and not self.directories:
            raise ValueError("At least one concrete file edit or directory is required")
        for item in self.files:
            patch = item.search is not None and item.replace is not None
            if sum((item.delete, patch, item.content is not None)) != 1:
                raise ValueError("Each file needs exactly one of content, search/replace, or delete")
            if (item.search is None) != (item.replace is None):
                raise ValueError("Patch search and replace must be supplied together")
        return self


class ReviewReport(BaseModel):
    approved: bool
    score: float = Field(ge=0, le=10)
    critical_issues: list[str] = Field(default_factory=list, max_length=30)
    warnings: list[str] = Field(default_factory=list, max_length=30)
    suggestions: list[str] = Field(default_factory=list, max_length=30)


class TestReport(BaseModel):
    status: Literal["passed", "failed", "not_run", "blocked", "awaiting_approval", "not_found", "not_applicable", "unsupported"]
    framework: str | None = None
    command: list[str] = Field(default_factory=list)
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    summary: str = ""
    evidence: Literal["VERIFIED", "NOT VERIFIED"] = "NOT VERIFIED"


class ValidationAction(BaseModel):
    allow_execution: bool = False


class ResumeAction(ValidationAction):
    model: str | None = Field(default=None, min_length=1, max_length=200)


class ApplyAction(BaseModel):
    files: list[str] | None = None
    approve_high_risk: bool = False
    allow_execution: bool = False
