from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RuleScope(str, enum.Enum):
    glob = "global"
    project = "project"


class RuleCategory(str, enum.Enum):
    identity = "identity"
    style = "style"
    security = "security"
    workflow = "workflow"
    coding = "coding"
    other = "other"


class AIRule(Base):
    __tablename__ = "ai_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    scope: Mapped[RuleScope] = mapped_column(
        SAEnum(RuleScope, values_callable=lambda obj: [e.value for e in obj], native_enum=False, length=16),
        nullable=False,
    )
    category: Mapped[RuleCategory] = mapped_column(
        SAEnum(RuleCategory, values_callable=lambda obj: [e.value for e in obj], native_enum=False, length=16),
        nullable=False,
        server_default=RuleCategory.other.value,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    is_seeded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
