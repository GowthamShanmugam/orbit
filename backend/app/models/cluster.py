from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User


class ClusterRole(str, enum.Enum):
    context = "context"
    test = "test"


class ClusterAuthMethod(str, enum.Enum):
    kubeconfig = "kubeconfig"
    token = "token"


class ClusterStatus(str, enum.Enum):
    pending = "pending"
    connected = "connected"
    error = "error"
    syncing = "syncing"


class TestRunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    passed = "passed"
    failed = "failed"
    error = "error"
    cancelled = "cancelled"


class ProjectCluster(Base):
    __tablename__ = "project_clusters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[ClusterRole] = mapped_column(
        SAEnum(ClusterRole, name="cluster_role", native_enum=True),
        nullable=False,
    )
    auth_method: Mapped[ClusterAuthMethod] = mapped_column(
        SAEnum(ClusterAuthMethod, name="cluster_auth_method", native_enum=True),
        nullable=False,
    )
    api_server_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    encrypted_credentials: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    credentials_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    credentials_tag: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    namespace_filter: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[ClusterStatus] = mapped_column(
        SAEnum(ClusterStatus, name="cluster_status", native_enum=True),
        default=ClusterStatus.pending,
        nullable=False,
    )
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
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
    test_runs: Mapped[list[TestRun]] = relationship(
        "TestRun", back_populates="cluster", cascade="all, delete-orphan"
    )


class TestRun(Base):
    __tablename__ = "test_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project_clusters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_type: Mapped[str] = mapped_column(
        String(64), default="command", nullable=False
    )
    command: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TestRunStatus] = mapped_column(
        SAEnum(TestRunStatus, name="test_run_status", native_enum=True),
        default=TestRunStatus.pending,
        nullable=False,
    )
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    cluster: Mapped[ProjectCluster] = relationship(
        "ProjectCluster", back_populates="test_runs"
    )
