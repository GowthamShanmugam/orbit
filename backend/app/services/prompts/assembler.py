"""Unified system prompt assembler.

Builds the final system prompt from DB rules + dynamic context + tool addendums + skill.
Single source of truth — called by both chat_stream() and chat_stream_thread().
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_rule import AIRule, RuleScope
from app.services.prompts.tools import (
    ARTIFACT_TOOLS,
    CLUSTER_TOOLS,
    LOCAL_TOOLS,
    MCP_TOOLS,
    REPO_TOOLS,
    tool_round_budget,
)


async def build_system_prompt(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    context: str = "",
    map_ctx: str | None = None,
    has_repos: bool = False,
    has_k8s: bool = False,
    has_mcp: bool = False,
    has_tools: bool = False,
    active_skill_slug: str | None = None,
    active_skill_prompt: str | None = None,
    is_thread: bool = False,
    thread_intro: str = "",
) -> str:
    """Assemble the full system prompt from rules, context, tools, and skill."""

    parts: list[str] = []

    # ── 1. Rules from DB (global first, then project) ────────────────────
    result = await db.execute(
        select(AIRule)
        .where(
            AIRule.enabled.is_(True),
            (AIRule.scope == RuleScope.glob)
            | (
                (AIRule.scope == RuleScope.project)
                & (AIRule.project_id == project_id)
            ),
        )
        .order_by(AIRule.scope.asc(), AIRule.sort_order.asc())
    )
    rules = result.scalars().all()

    global_rules = [r for r in rules if r.scope == RuleScope.glob]
    project_rules = [r for r in rules if r.scope == RuleScope.project]

    for i, rule in enumerate(global_rules):
        if i > 0:
            parts.append("\n\n")
        parts.append(rule.content)

    if project_rules:
        parts.append("\n\n## Project Rules\n")
        for rule in project_rules:
            parts.append(f"\n**{rule.title}**: {rule.content}")

    # ── 2. Thread intro (only for branch threads) ────────────────────────
    if is_thread and thread_intro:
        parts.append(f"\n\n{thread_intro}")

    # ── 3. Dynamic context ───────────────────────────────────────────────
    if context:
        parts.append(f"\n\n## Session Context\n\n{context}")
    if map_ctx:
        parts.append(f"\n\n{map_ctx}")

    # ── 4. Tool addendums (conditional) ──────────────────────────────────
    if has_repos:
        parts.append(REPO_TOOLS)
    if has_k8s:
        parts.append(CLUSTER_TOOLS)
    if has_repos and has_k8s:
        parts.append(LOCAL_TOOLS)
    if has_mcp:
        parts.append(MCP_TOOLS)

    # ── 5. Active skill ──────────────────────────────────────────────────
    if active_skill_slug and active_skill_prompt:
        parts.append(
            f"\n\n## Active Skill: {active_skill_slug}\n\n"
            f"{active_skill_prompt}\n\n"
            "IMPORTANT: The user has explicitly selected this skill. "
            "You MUST apply the skill behavior to every user message in this session. "
            "Do NOT ask the user to repeat what the skill already instructs. "
            "When the user provides content (a document, link, description, etc.), "
            "immediately apply the skill's task to that content."
        )

    # Artifact tools always available
    parts.append(ARTIFACT_TOOLS)

    # ── 6. Tool round budget (only if tools exist) ───────────────────────
    if has_tools:
        parts.append(tool_round_budget())

    return "".join(parts)
