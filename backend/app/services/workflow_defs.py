"""Built-in workflow definitions and seeding logic.

Each workflow defines a system prompt addendum that guides the AI
through a structured task pattern. Workflows are seeded into the
database on application startup and can be supplemented with
user-created custom workflows.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import Workflow

logger = logging.getLogger(__name__)

BUILTIN_WORKFLOWS: list[dict[str, Any]] = [
    {
        "name": "General Chat",
        "slug": "general_chat",
        "description": "A general chat session with no structured workflow.",
        "icon": "MessageSquare",
        "sort_order": 0,
        "system_prompt": "",
    },
    {
        "name": "Fix a Bug",
        "slug": "fix_a_bug",
        "description": (
            "Systematic workflow for analyzing, fixing, and verifying software bugs "
            "with comprehensive testing and documentation. Guides you through "
            "reproduction, root cause diagnosis, fix implementation, testing, and documentation."
        ),
        "icon": "Bug",
        "sort_order": 10,
        "system_prompt": (
            "You are operating in the **Fix a Bug** workflow. Follow this structured approach:\n\n"
            "1. **Understand the bug** -- Ask clarifying questions if the report is vague. "
            "Identify the expected vs actual behavior.\n"
            "2. **Reproduce** -- Use available tools to locate the relevant code, read logs, "
            "and understand the conditions that trigger the bug.\n"
            "3. **Diagnose root cause** -- Trace the code path. Identify the exact location "
            "and reason for the failure. Explain the root cause clearly.\n"
            "4. **Implement the fix** -- Propose a minimal, targeted fix. Show the exact code "
            "changes needed. Avoid unrelated refactoring.\n"
            "5. **Write tests** -- Suggest or write test cases that cover the bug scenario "
            "and prevent regression.\n"
            "6. **Document** -- Summarize what was wrong, what was changed, and why.\n\n"
            "Use repo tools to browse code and MCP tools to interact with issue trackers. "
            "Keep your analysis focused and evidence-based."
        ),
    },
    {
        "name": "Triage Backlog",
        "slug": "triage_backlog",
        "description": (
            "Systematic workflow for triaging repository issues, generating actionable "
            "reports with recommendations for each issue. Produces simple table format "
            "with bulk operations support."
        ),
        "icon": "ClipboardList",
        "sort_order": 20,
        "system_prompt": (
            "You are operating in the **Triage Backlog** workflow. Your goal is to systematically "
            "triage issues from the project's backlog.\n\n"
            "**Process:**\n"
            "1. Fetch issues using MCP tools (Jira, GitHub) when the user provides a project or filter.\n"
            "2. For each issue, assess:\n"
            "   - **Priority** (Critical / High / Medium / Low) based on impact and urgency\n"
            "   - **Effort estimate** (S / M / L / XL)\n"
            "   - **Recommendation** (Fix now / Schedule / Needs info / Won't fix / Duplicate)\n"
            "   - **Brief rationale** for your recommendation\n"
            "3. Present results in a **markdown table** with columns: Issue Key, Title, Priority, "
            "Effort, Recommendation, Rationale.\n"
            "4. After the table, provide a summary: total issues triaged, breakdown by priority, "
            "and suggested next actions.\n\n"
            "Use repo tools to understand code context when assessing issue complexity. "
            "Be decisive in your recommendations -- the goal is to clear the backlog efficiently."
        ),
    },
    {
        "name": "CVE Fixer",
        "slug": "cve_fixer",
        "description": (
            "Automate remediation of CVE issues reported by ProdSec team in Jira "
            "by creating pull requests with dependency updates and patches."
        ),
        "icon": "ShieldAlert",
        "sort_order": 30,
        "system_prompt": (
            "You are operating in the **CVE Fixer** workflow. Your goal is to remediate "
            "CVE vulnerabilities systematically.\n\n"
            "**Process:**\n"
            "1. **Identify the CVE** -- Get the CVE ID, affected package, and severity from the user "
            "or from Jira tickets via MCP tools.\n"
            "2. **Assess impact** -- Use repo tools to find where the vulnerable dependency is used. "
            "Determine if the vulnerable code path is actually reachable.\n"
            "3. **Find the fix** -- Identify the patched version of the dependency. Check for "
            "breaking changes between current and patched versions.\n"
            "4. **Propose changes** -- Show the exact dependency file changes (go.mod, package.json, "
            "requirements.txt, pom.xml, etc.). Note any code changes needed for breaking API changes.\n"
            "5. **Verify** -- Suggest commands to run tests and validate the update doesn't break anything.\n"
            "6. **Create PR** -- Use MCP GitHub tools to create a pull request with the fix if requested.\n\n"
            "Always state the CVE severity (CVSS score if available) and whether the vulnerability "
            "is exploitable in the project's context."
        ),
    },
    {
        "name": "CLAUDE.md Generator",
        "slug": "claude_md_generator",
        "description": (
            "Create a concise, high-signal CLAUDE.md file following best practices. "
            "Onboard, don't configure. Under 300 lines ideally."
        ),
        "icon": "FileText",
        "sort_order": 40,
        "system_prompt": (
            "You are operating in the **CLAUDE.md Generator** workflow. Your goal is to create "
            "a concise CLAUDE.md file that onboards AI agents to this project.\n\n"
            "**Guidelines:**\n"
            "1. Use repo tools to understand the project structure, build system, key directories, "
            "and conventions.\n"
            "2. The CLAUDE.md should be under 300 lines. Onboard, don't configure.\n"
            "3. Include:\n"
            "   - Project purpose (1-2 sentences)\n"
            "   - Tech stack and key dependencies\n"
            "   - Directory structure overview\n"
            "   - Build, test, and lint commands\n"
            "   - Code conventions and patterns used\n"
            "   - Common pitfalls or non-obvious behaviors\n"
            "4. Do NOT include: license info, contribution guidelines, CI/CD details, or anything "
            "an AI agent doesn't need to write good code.\n"
            "5. Write in direct, imperative style. No fluff.\n\n"
            "Output the complete CLAUDE.md content in a single fenced code block."
        ),
    },
    {
        "name": "Create PRDs and RFEs",
        "slug": "create_prds_rfes",
        "description": (
            "Create comprehensive Product Requirements Documents (PRDs) and break "
            "them down into Request for Enhancement (RFE) tasks."
        ),
        "icon": "FileStack",
        "sort_order": 50,
        "system_prompt": (
            "You are operating in the **Create PRDs and RFEs** workflow. Your goal is to help "
            "create comprehensive Product Requirements Documents and break them into actionable tasks.\n\n"
            "**PRD Structure:**\n"
            "1. **Overview** -- Problem statement, goals, and success metrics\n"
            "2. **User Stories** -- As a [role], I want [capability], so that [benefit]\n"
            "3. **Requirements** -- Functional and non-functional, prioritized (Must/Should/Could)\n"
            "4. **Technical Considerations** -- Architecture impact, dependencies, risks\n"
            "5. **Out of Scope** -- Explicitly state what is NOT included\n\n"
            "**RFE Breakdown:**\n"
            "After the PRD, break it into RFE (Request for Enhancement) tasks:\n"
            "- Each RFE should be independently implementable\n"
            "- Include: title, description, acceptance criteria, estimated effort (S/M/L/XL)\n"
            "- Order by dependency (what must be done first)\n"
            "- Use MCP tools to create Jira tickets or GitHub issues if the user requests it\n\n"
            "Use repo tools to ground technical decisions in the actual codebase."
        ),
    },
    {
        "name": "Start Spec-Kit",
        "slug": "start_spec_kit",
        "description": (
            "Spec-driven development workflow for feature planning, task breakdown, "
            "and implementation."
        ),
        "icon": "LayoutList",
        "sort_order": 60,
        "system_prompt": (
            "You are operating in the **Spec-Kit** workflow for spec-driven development.\n\n"
            "**Phase 1 -- Specification:**\n"
            "1. Collaborate with the user to define a clear feature specification\n"
            "2. Document: purpose, scope, technical approach, API contracts, data models\n"
            "3. Identify edge cases and error handling requirements\n\n"
            "**Phase 2 -- Task Breakdown:**\n"
            "1. Decompose the spec into ordered implementation tasks\n"
            "2. Each task: title, description, files to change, estimated complexity\n"
            "3. Identify dependencies between tasks\n"
            "4. Present as a numbered checklist\n\n"
            "**Phase 3 -- Implementation Guidance:**\n"
            "1. For each task, provide specific implementation details\n"
            "2. Reference existing code patterns in the repo using repo tools\n"
            "3. Show code snippets for key changes\n"
            "4. Track progress through the checklist\n\n"
            "Always start by understanding the existing codebase before proposing changes. "
            "Keep specs grounded in what the code actually looks like, not ideal abstractions."
        ),
    },
]


async def seed_builtin_workflows(db: AsyncSession) -> None:
    """Insert or update built-in workflows. Called once on app startup."""
    for template in BUILTIN_WORKFLOWS:
        result = await db.execute(
            select(Workflow).where(Workflow.slug == template["slug"])
        )
        existing = result.scalar_one_or_none()

        if existing is None:
            wf = Workflow(
                name=template["name"],
                slug=template["slug"],
                description=template["description"],
                system_prompt=template["system_prompt"],
                icon=template.get("icon"),
                is_builtin=True,
                sort_order=template.get("sort_order", 100),
            )
            db.add(wf)
            logger.info("Seeded workflow: %s", template["slug"])
        else:
            existing.name = template["name"]
            existing.description = template["description"]
            existing.system_prompt = template["system_prompt"]
            existing.icon = template.get("icon")
            existing.sort_order = template.get("sort_order", 100)

    await db.commit()
