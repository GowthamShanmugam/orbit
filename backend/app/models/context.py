from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.project import Project
    from app.models.session import Session


class PackVisibility(str, enum.Enum):
    public = "public"
    organization = "organization"
    personal = "personal"


class ContextSourceType(str, enum.Enum):
    github_repo = "github_repo"
    gitlab_repo = "gitlab_repo"
    jira_project = "jira_project"
    confluence_space = "confluence_space"
    google_doc = "google_doc"
    google_drive_folder = "google_drive_folder"
    file_pin = "file_pin"
    code_snippet = "code_snippet"
    k8s_cluster = "k8s_cluster"


class SessionLayerType(str, enum.Enum):
    pull_request = "pull_request"
    jira_ticket = "jira_ticket"
    google_doc = "google_doc"
    google_drive_folder = "google_drive_folder"
    file_pin = "file_pin"
    code_snippet = "code_snippet"
    past_session = "past_session"


class ContextPack(Base):
    __tablename__ = "context_packs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version: Mapped[str] = mapped_column(String(64), default="1.0.0", nullable=False)
    visibility: Mapped[PackVisibility] = mapped_column(
        SAEnum(PackVisibility, name="pack_visibility", native_enum=True),
        default=PackVisibility.organization,
        nullable=False,
    )
    dependencies: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    maintainer_team: Mapped[str | None] = mapped_column(String(255), nullable=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    repo_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    sources: Mapped[list[PackContextSource]] = relationship(
        "PackContextSource",
        back_populates="pack",
        cascade="all, delete-orphan",
    )
    installed_packs: Mapped[list[InstalledPack]] = relationship(
        "InstalledPack",
        back_populates="pack",
        cascade="all, delete-orphan",
    )


class PackContextSource(Base):
    __tablename__ = "pack_context_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("context_packs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[ContextSourceType] = mapped_column(
        SAEnum(ContextSourceType, name="context_source_type", native_enum=True),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    pack: Mapped[ContextPack] = relationship("ContextPack", back_populates="sources")


class InstalledPack(Base):
    __tablename__ = "installed_packs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("context_packs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    auto_update: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    overrides: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped[Project] = relationship("Project")
    pack: Mapped[ContextPack] = relationship(
        "ContextPack", back_populates="installed_packs"
    )


class ContextSource(Base):
    __tablename__ = "context_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[ContextSourceType] = mapped_column(
        SAEnum(ContextSourceType, name="context_source_type", native_enum=True, create_type=False),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    auto_attach: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_indexed: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project: Mapped[Project] = relationship("Project")
    indexed_chunks: Mapped[list[IndexedChunk]] = relationship(
        "IndexedChunk",
        back_populates="context_source",
        cascade="all, delete-orphan",
    )


class SessionLayer(Base):
    __tablename__ = "session_layers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[SessionLayerType] = mapped_column(
        SAEnum(SessionLayerType, name="session_layer_type", native_enum=True),
        nullable=False,
    )
    reference_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    label: Mapped[str] = mapped_column(String(512), nullable=False)
    cached_content: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[Session] = relationship("Session")


class IndexedChunk(Base):
    __tablename__ = "indexed_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("context_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(1536), nullable=True)
    chunk_type: Mapped[str] = mapped_column(String(64), default="code", nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    context_source: Mapped[ContextSource] = relationship(
        "ContextSource", back_populates="indexed_chunks"
    )
