"""MCP Skill models.

Global MCP server configurations that extend Orbit's AI capabilities.
Each skill represents an MCP server (e.g., Atlassian, GitHub) that
provides tools to the AI during chat sessions.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SkillStatus(str, enum.Enum):
    available = "available"
    configured = "configured"
    connected = "connected"
    error = "error"


class SkillTransport(str, enum.Enum):
    stdio = "stdio"
    http = "http"


class McpSkill(Base):
    """A global MCP server skill available to all sessions.

    Each skill maps to an MCP server that can be started and queried
    for tool definitions. Users configure credentials, and the skill
    becomes available to the AI in all chat sessions.
    """

    __tablename__ = "mcp_skills"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)

    transport: Mapped[SkillTransport] = mapped_column(
        SAEnum(SkillTransport, name="skill_transport", native_enum=True),
        default=SkillTransport.stdio,
        nullable=False,
    )
    server_command: Mapped[str] = mapped_column(String(1024), nullable=False)
    server_args: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    server_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    config_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    config_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    status: Mapped[SkillStatus] = mapped_column(
        SAEnum(SkillStatus, name="skill_status", native_enum=True),
        default=SkillStatus.available,
        nullable=False,
    )
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    cached_tools: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
