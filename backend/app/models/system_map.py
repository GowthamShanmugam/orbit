from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.cluster import ProjectCluster
    from app.models.context import ContextSource
    from app.models.project import Project


class ServiceMapping(Base):
    """Links a K8s deployment to a context source (repo)."""

    __tablename__ = "service_mappings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project_clusters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    deployment_name: Mapped[str] = mapped_column(String(512), nullable=False)
    deployment_namespace: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    context_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("context_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_infrastructure: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    node_position_x: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    node_position_y: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
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
    cluster: Mapped[ProjectCluster] = relationship("ProjectCluster")
    context_source: Mapped[ContextSource | None] = relationship("ContextSource")
    outgoing_edges: Mapped[list[ServiceEdge]] = relationship(
        "ServiceEdge",
        foreign_keys="ServiceEdge.source_mapping_id",
        back_populates="source_mapping",
        cascade="all, delete-orphan",
    )
    incoming_edges: Mapped[list[ServiceEdge]] = relationship(
        "ServiceEdge",
        foreign_keys="ServiceEdge.target_mapping_id",
        back_populates="target_mapping",
        cascade="all, delete-orphan",
    )


class ServiceEdge(Base):
    """Manual connection between two services on the system map."""

    __tablename__ = "service_edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_mapping_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("service_mappings.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_mapping_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("service_mappings.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source_mapping: Mapped[ServiceMapping] = relationship(
        "ServiceMapping", foreign_keys=[source_mapping_id], back_populates="outgoing_edges"
    )
    target_mapping: Mapped[ServiceMapping] = relationship(
        "ServiceMapping", foreign_keys=[target_mapping_id], back_populates="incoming_edges"
    )
