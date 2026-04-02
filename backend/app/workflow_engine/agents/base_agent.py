"""Base agent interface for the workflow engine.

All agents in the pipeline implement this ABC.  The orchestrator calls
``execute()`` and collects the result for passing to the next step.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class AgentStatus(str, Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    skipped = "skipped"


@dataclass
class AgentResult:
    status: AgentStatus = AgentStatus.success
    output: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0


@dataclass
class AgentContext:
    """Runtime context available to every agent step."""
    db: AsyncSession
    project_id: uuid.UUID
    session_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    model: str = "claude-sonnet-4-5-20250929"
    step_input: dict[str, Any] = field(default_factory=dict)
    previous_results: list[AgentResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Abstract base class for all workflow agents."""

    name: str = "base"
    description: str = ""

    @abstractmethod
    async def execute(self, ctx: AgentContext) -> AgentResult:
        """Run the agent's logic and return a result."""
        ...

    async def validate(self, ctx: AgentContext) -> list[str]:
        """Optional pre-execution validation. Returns list of error messages."""
        return []

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"


_AGENT_REGISTRY: dict[str, type[BaseAgent]] = {}


def register_agent(cls: type[BaseAgent]) -> type[BaseAgent]:
    """Class decorator to register an agent in the global registry."""
    _AGENT_REGISTRY[cls.name] = cls
    return cls


def get_agent_class(name: str) -> type[BaseAgent] | None:
    return _AGENT_REGISTRY.get(name)


def list_registered_agents() -> dict[str, type[BaseAgent]]:
    return dict(_AGENT_REGISTRY)
