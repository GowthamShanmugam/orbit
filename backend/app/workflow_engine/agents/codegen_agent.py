"""Code Generation Agent — generates code changes based on instructions.

Takes an instruction (from an issue, user, or previous agent step) and
produces code patches / file changes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.config import settings
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
class CodegenAgent(BaseAgent):
    name = "code_generation"
    description = "Generate code changes based on instructions and project context"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        start = datetime.now(UTC)
        instruction = ctx.step_input.get("instruction", "")
        if not instruction:
            return AgentResult(
                status=AgentStatus.failed,
                errors=["No instruction provided for code generation"],
            )

        prior_analysis = ""
        for prev in ctx.previous_results:
            if prev.output.get("analysis"):
                prior_analysis = prev.output["analysis"]
                break

        context = await assemble_context(
            ctx.db,
            project_id=ctx.project_id,
            session_id=ctx.session_id,
            max_tokens=settings.WORKFLOW_CODEGEN_MAX_TOKENS,
        )

        system = (
            "You are a code generation agent. Generate high-quality code changes "
            "based on the instruction and project context. "
            "Output code in fenced code blocks with file paths as headers:\n"
            "```path/to/file.py\n<code>\n```\n"
            "Include only changed files. Explain what you changed and why."
        )
        if prior_analysis:
            system += f"\n\n## Prior Analysis\n\n{prior_analysis}"
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

        generated = response.content[0].text
        elapsed = int((datetime.now(UTC) - start).total_seconds() * 1000)

        return AgentResult(
            status=AgentStatus.success,
            output={
                "generated_code": generated,
                "model": ctx.model,
                "instruction": instruction,
            },
            artifacts=[{
                "type": "generated_code",
                "format": "markdown",
                "content": generated,
            }],
            duration_ms=elapsed,
        )
