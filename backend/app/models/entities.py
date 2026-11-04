import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def identifier() -> str:
    return str(uuid.uuid4())


class IdentityMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class User(IdentityMixin, Base):
    __tablename__ = "users"
    name: Mapped[str] = mapped_column(String(200), default="Local developer")


class Project(IdentityMixin, Base):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(Text, unique=True)
    project_map: Mapped[dict[str, Any]] = mapped_column(JSON)


class Conversation(IdentityMixin, Base):
    __tablename__ = "conversations"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))


class Message(IdentityMixin, Base):
    __tablename__ = "messages"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)


class AgentRun(IdentityMixin, Base):
    __tablename__ = "agent_runs"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    intent: Mapped[str] = mapped_column(String(30), default="ASK")
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ChangeSet(IdentityMixin, Base):
    __tablename__ = "change_sets"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    proposal: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="proposed")


class RunCheckpoint(Base):
    __tablename__ = "run_checkpoints"
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class ProjectMemory(IdentityMixin, Base):
    __tablename__ = "project_memories"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    category: Mapped[str] = mapped_column(String(30))
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(Text)


class ProjectIndexMetadata(IdentityMixin, Base):
    __tablename__ = "project_indexes"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), unique=True)
    metadata_value: Mapped[dict[str, Any]] = mapped_column(JSON)
