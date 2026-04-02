"""Bug triage data models.

Stores imported issues from Jira/GitHub and AI-generated triage reports
with root cause analysis, suggested fixes, and branch creation metadata.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.session import Session


class BugSource(str, enum.Enum):
    jira = "jira"
    github = "github"


class BugPriority(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    unknown = "unknown"


class BugStatus(str, enum.Enum):
    imported = "imported"
    triaging = "triaging"
    triaged = "triaged"
    fix_generated = "fix_generated"
    branch_created = "branch_created"
    resolved = "resolved"
    dismissed = "dismissed"


class TriageConfidence(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"


class BugReport(Base):
    """An imported bug/issue from Jira or GitHub Issues."""

    __tablename__ = "bug_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[BugSource] = mapped_column(
        SAEnum(BugSource, name="bug_source", native_enum=True),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[BugPriority] = mapped_column(
        SAEnum(BugPriority, name="bug_priority", native_enum=True),
        default=BugPriority.unknown,
        nullable=False,
    )
    status: Mapped[BugStatus] = mapped_column(
        SAEnum(BugStatus, name="bug_status", native_enum=True),
        default=BugStatus.imported,
        nullable=False,
    )
    assignee: Mapped[str | None] = mapped_column(String(255), nullable=True)
    labels: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    imported_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    triage_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
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
    triage_session: Mapped[Session | None] = relationship("Session", foreign_keys=[triage_session_id])
    triage_reports: Mapped[list[TriageReport]] = relationship(
        "TriageReport",
        back_populates="bug_report",
        cascade="all, delete-orphan",
        order_by="TriageReport.created_at.desc()",
    )


class TriageReport(Base):
    """AI-generated triage report for a bug, including root cause analysis
    and suggested fix."""

    __tablename__ = "triage_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    bug_report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bug_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    affected_files: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[TriageConfidence] = mapped_column(
        SAEnum(TriageConfidence, name="triage_confidence", native_enum=True),
        default=TriageConfidence.medium,
        nullable=False,
    )
    suggested_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    fix_diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    branch_created: Mapped[bool] = mapped_column(
        default=False, nullable=False
    )
    report_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    bug_report: Mapped[BugReport] = relationship(
        "BugReport", back_populates="triage_reports"
    )
    session: Mapped[Session | None] = relationship("Session")
