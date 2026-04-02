"""Agent Orchestrator — core engine for executing agent pipelines.

Runs a sequence of agent steps, threading context and results between
them, with real-time status updates via an async callback.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.workflow_engine.agents.base_agent import (
    AgentContext,
    AgentResult,
    AgentStatus,
    BaseAgent,
    get_agent_class,
    list_registered_agents,
)

import app.workflow_engine.agents.codebase_agent  # noqa: F401  register
import app.workflow_engine.agents.codegen_agent  # noqa: F401  register
import app.workflow_engine.agents.review_agent  # noqa: F401  register


class PipelineStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


@dataclass
class StepConfig:
    agent_name: str
    config: dict[str, Any] = field(default_factory=dict)
    continue_on_failure: bool = False


@dataclass
class StepExecution:
    step_index: int
    agent_name: str
    status: AgentStatus = AgentStatus.pending
    result: AgentResult | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class PipelineExecution:
    pipeline_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: PipelineStatus = PipelineStatus.pending
    steps: list[StepExecution] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class Orchestrator:
    """Execute a sequence of agent steps as a pipeline."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_pipeline(
        self,
        *,
        steps: list[StepConfig],
        project_id: uuid.UUID,
        session_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        model: str = "claude-sonnet-4-5-20250929",
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute steps sequentially, yielding status events."""
        execution = PipelineExecution(
            status=PipelineStatus.running,
            started_at=datetime.now(UTC),
            steps=[
                StepExecution(step_index=i, agent_name=s.agent_name)
                for i, s in enumerate(steps)
            ],
        )

        yield _pipeline_event(execution, "pipeline_started")

        results: list[AgentResult] = []

        for i, step_cfg in enumerate(steps):
            step = execution.steps[i]
            step.status = AgentStatus.running
            step.started_at = datetime.now(UTC)

            yield _step_event(execution, step, "step_started")

            agent_cls = get_agent_class(step_cfg.agent_name)
            if agent_cls is None:
                step.status = AgentStatus.failed
                step.result = AgentResult(
                    status=AgentStatus.failed,
                    errors=[f"Unknown agent: {step_cfg.agent_name}"],
                )
                step.completed_at = datetime.now(UTC)
                yield _step_event(execution, step, "step_failed")
                if not step_cfg.continue_on_failure:
                    break
                results.append(step.result)
                continue

            agent = agent_cls()
            ctx = AgentContext(
                db=self.db,
                project_id=project_id,
                session_id=session_id,
                user_id=user_id,
                model=model,
                step_input=step_cfg.config,
                previous_results=results,
                metadata=metadata or {},
            )

            validation_errors = await agent.validate(ctx)
            if validation_errors:
                step.status = AgentStatus.failed
                step.result = AgentResult(
                    status=AgentStatus.failed,
                    errors=validation_errors,
                )
                step.completed_at = datetime.now(UTC)
                yield _step_event(execution, step, "step_failed")
                if not step_cfg.continue_on_failure:
                    break
                results.append(step.result)
                continue

            try:
                result = await agent.execute(ctx)
                step.status = result.status
                step.result = result
            except Exception as exc:
                step.status = AgentStatus.failed
                step.result = AgentResult(
                    status=AgentStatus.failed,
                    errors=[str(exc)],
                )

            step.completed_at = datetime.now(UTC)
            results.append(step.result)

            event_name = (
                "step_completed" if step.status == AgentStatus.success
                else "step_failed"
            )
            yield _step_event(execution, step, event_name)

            if step.status == AgentStatus.failed and not step_cfg.continue_on_failure:
                break

        any_failed = any(s.status == AgentStatus.failed for s in execution.steps)
        execution.status = PipelineStatus.failed if any_failed else PipelineStatus.completed
        execution.completed_at = datetime.now(UTC)
        yield _pipeline_event(execution, "pipeline_completed")

    @staticmethod
    def available_agents() -> list[dict[str, str]]:
        return [
            {"name": name, "description": cls.description}
            for name, cls in list_registered_agents().items()
        ]


def _pipeline_event(execution: PipelineExecution, event_type: str) -> dict[str, Any]:
    return {
        "type": event_type,
        "pipeline_id": execution.pipeline_id,
        "status": execution.status.value,
        "total_steps": len(execution.steps),
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
    }


def _step_event(
    execution: PipelineExecution,
    step: StepExecution,
    event_type: str,
) -> dict[str, Any]:
    return {
        "type": event_type,
        "pipeline_id": execution.pipeline_id,
        "step_index": step.step_index,
        "agent_name": step.agent_name,
        "status": step.status.value,
        "total_steps": len(execution.steps),
        "result": {
            "output": step.result.output if step.result else {},
            "errors": step.result.errors if step.result else [],
            "artifacts": step.result.artifacts if step.result else [],
            "duration_ms": step.result.duration_ms if step.result else 0,
        },
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "completed_at": step.completed_at.isoformat() if step.completed_at else None,
    }
