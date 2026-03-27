from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User


class ProjectShareSubject(str, enum.Enum):
    user = "user"
    group = "group"


class ProjectShareRole(str, enum.Enum):
    view = "view"
    edit = "edit"
    admin = "admin"


class ProjectShare(Base):
    """Explicit grants for who can access a project when sharing is enforced."""

    __tablename__ = "project_shares"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_type: Mapped[ProjectShareSubject] = mapped_column(
        SAEnum(ProjectShareSubject, name="project_share_subject", native_enum=True),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    group_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[ProjectShareRole] = mapped_column(
        SAEnum(ProjectShareRole, name="project_share_role", native_enum=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    project: Mapped[Project] = relationship("Project", back_populates="shares")
    user: Mapped[User | None] = relationship("User")
