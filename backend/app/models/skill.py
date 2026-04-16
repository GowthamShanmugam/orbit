"""Skill Plugin models.

Follows the opendatahub-io/skills-registry pattern:
  Plugin → contains many Skills
  User opts in per-plugin with their own credentials

Plugins can be:
  - MCP tool packs (Atlassian, GitHub) that call external APIs
  - Prompt skill packs (Fix a Bug, RFE Creator) that guide AI behavior
  - Hybrid (both tools and prompt skills)

Each user independently installs and configures plugins they want.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PluginType(str, enum.Enum):
    """What kind of capabilities this plugin provides."""

    mcp = "mcp"
    prompt = "prompt"
    hybrid = "hybrid"


class PluginSource(str, enum.Enum):
    """Where this plugin came from."""

    builtin = "builtin"
    custom = "custom"
    github = "github"


class SkillTransport(str, enum.Enum):
    stdio = "stdio"
    http = "http"


class SkillStatus(str, enum.Enum):
    available = "available"
    configured = "configured"
    connected = "connected"
    error = "error"


class SkillCategory(Base):
    """Grouping for plugins (e.g. 'planning', 'security', 'devops')."""

    __tablename__ = "skill_categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    plugins: Mapped[list[SkillPlugin]] = relationship(
        "SkillPlugin", back_populates="category", lazy="selectin"
    )


class SkillPlugin(Base):
    """A plugin in the catalog. Contains one or more skills.

    This is the equivalent of a "plugin" entry in opendatahub's registry.yaml.
    The plugin itself is just a catalog entry -- it doesn't affect any user's
    session until they install it via UserPluginConfig.
    """

    __tablename__ = "skill_plugins"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str] = mapped_column(String(32), default="0.1.0", nullable=False)
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    plugin_type: Mapped[PluginType] = mapped_column(
        SAEnum(PluginType, name="plugin_type", native_enum=True),
        default=PluginType.mcp,
        nullable=False,
    )
    source: Mapped[PluginSource] = mapped_column(
        SAEnum(PluginSource, name="plugin_source", native_enum=True),
        default=PluginSource.builtin,
        nullable=False,
    )
    source_repo: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # MCP server config (only for mcp/hybrid plugins)
    transport: Mapped[SkillTransport | None] = mapped_column(
        SAEnum(SkillTransport, name="skill_transport", native_enum=True),
        nullable=True,
    )
    server_command: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    server_args: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    server_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    config_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    cached_tools: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), default="public", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skill_categories.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    depends_on: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    category: Mapped[SkillCategory | None] = relationship(
        "SkillCategory", back_populates="plugins", lazy="selectin"
    )
    skills: Mapped[list[PluginSkill]] = relationship(
        "PluginSkill",
        back_populates="plugin",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    user_configs: Mapped[list[UserPluginConfig]] = relationship(
        "UserPluginConfig",
        back_populates="plugin",
        cascade="all, delete-orphan",
    )


class PluginSkill(Base):
    """An individual skill within a plugin.

    For MCP plugins: skills are auto-discovered from the MCP server's tool list.
    For prompt plugins: each skill has its own system_prompt instructions.
    """

    __tablename__ = "plugin_skills"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plugin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skill_plugins.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_invocable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    plugin: Mapped[SkillPlugin] = relationship("SkillPlugin", back_populates="skills")

    __table_args__ = (UniqueConstraint("plugin_id", "slug", name="uq_plugin_skill_slug"),)


class UserPluginConfig(Base):
    """Per-user plugin installation and configuration.

    Each user independently opts in to plugins and provides their own
    credentials. A plugin only appears in a user's chat session if they
    have an enabled UserPluginConfig for it.
    """

    __tablename__ = "user_plugin_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    plugin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skill_plugins.id", ondelete="CASCADE"),
        nullable=False,
    )

    config_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[SkillStatus] = mapped_column(
        SAEnum(SkillStatus, name="skill_status", native_enum=True),
        default=SkillStatus.available,
        nullable=False,
    )
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    plugin: Mapped[SkillPlugin] = relationship("SkillPlugin", back_populates="user_configs")

    __table_args__ = (UniqueConstraint("user_id", "plugin_id", name="uq_user_plugin"),)


# Keep these as aliases for backward compat during migration
McpSkill = SkillPlugin
