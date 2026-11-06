"""Daily Coach (Today) — user-scoped watchlists and reminder prefs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CoachProfile(Base):
    """One row per user: watchlists + light reminder preferences."""

    __tablename__ = "coach_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_coach_profiles_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Shape:
    # {
    #   "jira": [{"id", "project_key", "label", "orbit_project_id"?}],
    #   "meetings": [{"id", "title", "notes_url"?, "notes_doc_id"?,
    #                 "days_of_week": [0-6], "time_local"?: "09:30",
    #                 "reminder_minutes_before"?: 15}],
    #   "repos": [{"id", "provider": "github"|"gitlab", "owner", "repo",
    #              "label"?, "orbit_project_id"?}]
    # }
    watchlists: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
    )
    # Shape: {"enabled": true, "standup_minutes_before": 15}
    reminder_prefs: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default='{"enabled": true, "standup_minutes_before": 15}',
    )
    # Saved board: daily snapshots, one attention row per MR/Jira, standup reads.
    # Page loads reuse this instead of calling Jira, GitLab, and Docs every time.
    state: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
    )
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
