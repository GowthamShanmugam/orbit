"""Codebase Agent — always-on AI deeply integrated with project repos.

Understands conventions, modules, and architecture.  Powers all other
workflow agents by providing codebase analysis and relevant-file lookup.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.models.context import ContextSource, IndexedChunk
from app.services.ai_client import get_ai_client
from app.services.ai_service import AVAILABLE_MODELS, _resolve_model_for_provider, assemble_context
from app.workflow_engine.agents.base_agent import (
    AgentContext,
    AgentResult,
    AgentStatus,
    BaseAgent,
    register_agent,
)


@register_agent
class CodebaseAgent(BaseAgent):
    name = "codebase_analysis"
    description = "Analyze project codebase using indexed context and AI"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        start = datetime.now(UTC)
        instruction = ctx.step_input.get(
            "instruction", "Analyze the project codebase and summarize the architecture."
        )
        focus = ctx.step_input.get("focus")

        context = await assemble_context(
            ctx.db,
            project_id=ctx.project_id,
            session_id=ctx.session_id,
            max_tokens=80_000,
        )

        system = (
            "You are a codebase analysis agent. Analyze the provided project context "
            "and answer the instruction precisely. "
            "Identify relevant files, modules, patterns, and architectural decisions."
        )
        if focus:
            system += f"\n\nFocus area: {focus}"

        if context:
            system += f"\n\n## Project Context\n\n{context}"

        client = get_ai_client()
        model_info = AVAILABLE_MODELS.get(ctx.model, AVAILABLE_MODELS["claude-sonnet-4-5-20250929"])

        response = client.messages.create(
            model=_resolve_model_for_provider(ctx.model),
            max_tokens=model_info["max_tokens"],
            system=system,
            messages=[{"role": "user", "content": instruction}],
        )

        analysis = response.content[0].text
        elapsed = int((datetime.now(UTC) - start).total_seconds() * 1000)

        return AgentResult(
            status=AgentStatus.success,
            output={
                "analysis": analysis,
                "model": ctx.model,
                "focus": focus,
            },
            duration_ms=elapsed,
        )
