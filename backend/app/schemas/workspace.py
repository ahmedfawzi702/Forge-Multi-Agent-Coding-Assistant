from typing import Literal

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(default="Untitled workspace", min_length=1, max_length=80)
    location: str | None = Field(default=None, max_length=4096)
    template: Literal["empty", "python", "fastapi", "node", "next", "react"] = "empty"


class FileWrite(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    content: str = Field(default="", max_length=1048576)
    base_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class PathAction(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    destination: str | None = Field(default=None, max_length=4096)


class TerminalCreate(BaseModel):
    approved: bool = False
    cols: int = Field(default=100, ge=20, le=400)
    rows: int = Field(default=24, ge=5, le=200)


class TerminalInput(BaseModel):
    data: str = Field(max_length=16384)


class TerminalResize(BaseModel):
    cols: int = Field(ge=20, le=400)
    rows: int = Field(ge=5, le=200)


class CommandRequest(BaseModel):
    argv: list[str] = Field(min_length=1, max_length=100)
    approved: bool = False
    timeout: int = Field(default=60, ge=1, le=300)


class GitAction(BaseModel):
    action: Literal["init", "stage", "unstage", "commit", "branch", "switch", "fetch", "pull", "push", "abort_merge"]
    paths: list[str] = Field(default_factory=list, max_length=300)
    message: str = Field(default="", max_length=4000)
    branch: str = Field(default="", max_length=120)
    approve_hooks: bool = False
    remote: str = Field(default="origin", max_length=120)
    confirmed: bool = False
    expected_url: str | None = Field(default=None, max_length=2048)
    expected_head: str | None = Field(default=None, max_length=64)


class CloneRequest(WorkspaceCreate):
    url: str = Field(min_length=1, max_length=2048)
    branch: str = Field(default="", max_length=120)


class SteeringRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
