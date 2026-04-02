from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.session import Session
    from app.models.user import User


class ProjectVisibility(str, enum.Enum):
    private = "private"
    public = "public"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    visibility: Mapped[ProjectVisibility] = mapped_column(
        SAEnum(
            ProjectVisibility,
            values_callable=lambda obj: [e.value for e in obj],
            native_enum=False,
            length=16,
        ),
        nullable=False,
        server_default=ProjectVisibility.private.value,
        default=ProjectVisibility.private,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    default_ai_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: Per-project overrides for whitelisted runtime keys (see app.services.runtime_settings).
    runtime_overrides: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    organization: Mapped[Organization] = relationship("Organization", back_populates="projects")
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])
    sessions: Mapped[list[Session]] = relationship(
        "Session",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    shares: Mapped[list["ProjectShare"]] = relationship(
        "ProjectShare",
        back_populates="project",
        cascade="all, delete-orphan",
    )
