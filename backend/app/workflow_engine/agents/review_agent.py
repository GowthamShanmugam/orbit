"""Self-Review Agent — multi-faceted review of generated code.

Checks architecture, linting/style, and security concerns, then produces
a consolidated review with an improve/approve recommendation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.ai_client import get_ai_client
from app.services.ai_service import AVAILABLE_MODELS, _resolve_model_for_provider
from app.workflow_engine.agents.base_agent import (
    AgentContext,
    AgentResult,
    AgentStatus,
    BaseAgent,
    register_agent,
)

_REVIEW_CHECKS = ["architecture", "linting", "security", "tests"]


@register_agent
class ReviewAgent(BaseAgent):
    name = "self_review"
    description = "Multi-faceted review of generated code (architecture, lint, security)"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        start = datetime.now(UTC)

        code_to_review = ""
        for prev in ctx.previous_results:
            if prev.output.get("generated_code"):
                code_to_review = prev.output["generated_code"]
                break

        if not code_to_review:
            return AgentResult(
                status=AgentStatus.skipped,
                output={"reason": "No code to review from previous steps"},
            )

        checks = ctx.step_input.get("checks", _REVIEW_CHECKS)
        checks_str = ", ".join(checks)

        system = (
            "You are a senior code reviewer. Review the following code changes "
            f"for these aspects: {checks_str}.\n\n"
            "For each aspect, give:\n"
            "- **Status**: pass / warn / fail\n"
            "- **Findings**: specific issues found\n"
            "- **Suggestions**: how to fix\n\n"
            "End with an overall recommendation: APPROVE, REQUEST_CHANGES, or NEEDS_DISCUSSION."
        )

        client = get_ai_client()
        model_info = AVAILABLE_MODELS.get(ctx.model, AVAILABLE_MODELS["claude-sonnet-4-5-20250929"])

        response = client.messages.create(
            model=_resolve_model_for_provider(ctx.model),
            max_tokens=model_info["max_tokens"],
            system=system,
            messages=[{"role": "user", "content": f"Review this code:\n\n{code_to_review}"}],
        )

        review = response.content[0].text
        elapsed = int((datetime.now(UTC) - start).total_seconds() * 1000)

        recommendation = "APPROVE"
        upper = review.upper()
        if "REQUEST_CHANGES" in upper:
            recommendation = "REQUEST_CHANGES"
        elif "NEEDS_DISCUSSION" in upper:
            recommendation = "NEEDS_DISCUSSION"

        return AgentResult(
            status=AgentStatus.success,
            output={
                "review": review,
                "recommendation": recommendation,
                "checks": checks,
                "model": ctx.model,
            },
            artifacts=[{
                "type": "code_review",
                "format": "markdown",
                "content": review,
            }],
            duration_ms=elapsed,
        )
