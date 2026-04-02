"""Anthropic Claude AI service with streaming, tool-use, and secret replacement.

Supports model selection (Sonnet 4.5/4.6, Opus 4.6, Haiku 4.5).

The AI interacts with project resources entirely through tools:
  - **Repo tools**: browse cloned repositories on-demand (list files, read,
    search) instead of bulk-indexing thousands of chunks into the prompt.
  - **K8s tools**: query live clusters on-demand (pods, logs, events, etc.)
  - **Local tools**: run shell commands in cloned repos with cluster creds.

Conversation history (including tool_use/tool_result blocks) is kept in an
in-memory session cache so the AI retains full context across turns.  Only
user messages and final assistant replies are persisted to the database (for
the chat UI).  When the cache is cold (server restart), we rebuild from DB
messages and optionally summarise to stay within the context window.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.runtime_settings import eff_float, eff_int, project_runtime_context
from app.core.secret_vault import find_placeholders, replace_placeholders
from app.models.cluster import ProjectCluster
from app.models.context import ContextSource, ContextSourceType, SessionLayer
from app.models.secret import ProjectSecret
from app.models.session import Message, MessageRole
from app.services.ai_client import get_ai_client
from app.services import kube_tools
from app.services import local_tools
from app.services import mcp_client
from app.services import repo_tools
from app.services import session_artifact_tools

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Models (max output tokens from settings — see app.core.config)
# ---------------------------------------------------------------------------


def _build_available_models() -> dict[str, dict[str, Any]]:
    s = settings
    mt = s.AI_MAX_OUTPUT_TOKENS_STANDARD
    mh = s.AI_MAX_OUTPUT_TOKENS_HAIKU
    return {
        "claude-opus-4-6": {
            "display_name": "Claude Opus 4.6",
            "description": "Most capable for complex work",
            "max_tokens": mt,
            "vertex_id": "claude-opus-4-6",
        },
        "claude-sonnet-4-6": {
            "display_name": "Claude Sonnet 4.6",
            "description": "Best for everyday tasks",
            "max_tokens": mt,
            "vertex_id": "claude-sonnet-4-6",
        },
        "claude-sonnet-4-5-20250929": {
            "display_name": "Claude Sonnet 4.5",
            "description": "Balanced performance for agents and coding",
            "max_tokens": mt,
            "vertex_id": "claude-sonnet-4-5@20250929",
        },
        "claude-haiku-4-5-20251001": {
            "display_name": "Claude Haiku 4.5",
            "description": "Fastest for quick answers",
            "max_tokens": mh,
            "vertex_id": "claude-haiku-4-5@20251001",
        },
    }


AVAILABLE_MODELS: dict[str, dict[str, Any]] = _build_available_models()

# ---------------------------------------------------------------------------
# In-memory session conversation cache
# ---------------------------------------------------------------------------
# Maps session_id → list of Anthropic-format messages (including tool blocks).
# LRU cap: settings.AI_MAX_CACHED_SESSIONS

_conversation_cache: OrderedDict[uuid.UUID, list[dict[str, Any]]] = OrderedDict()


def _cache_get(session_id: uuid.UUID) -> list[dict[str, Any]] | None:
    if session_id in _conversation_cache:
        _conversation_cache.move_to_end(session_id)
        return _conversation_cache[session_id]
    return None


def _cache_set(session_id: uuid.UUID, conversation: list[dict[str, Any]]) -> None:
    _conversation_cache[session_id] = conversation
    _conversation_cache.move_to_end(session_id)
    while len(_conversation_cache) > settings.AI_MAX_CACHED_SESSIONS:
        _conversation_cache.popitem(last=False)


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

def _resolve_model_for_provider(model_id: str) -> str:
    if settings.CLAUDE_PROVIDER == "vertex":
        info = AVAILABLE_MODELS.get(model_id)
        if info and info.get("vertex_id"):
            return info["vertex_id"]
    return model_id


SYSTEM_PROMPT_HEADER = (
    "You are Orbit, an AI coding assistant with deep project context. "
    "You have tools to browse the project's code repositories, Kubernetes clusters, "
    "and other resources on-demand. Use tools to fetch only the information you need "
    "to answer each question — never request everything at once. "
    "When referencing code, cite specific file paths and line numbers. "
    "If you see {{secret:name}} placeholders, never attempt to reveal their values.\n\n"
    "RESPONSE STYLE — follow these strictly:\n"
    "- Be concise and professional. Write like a senior engineer, not a marketing bot.\n"
    "- NEVER use emojis or icons (no ✅ 🚀 ⚠️ 🔧 📁 ❌ 💡 or similar). Use plain text.\n"
    "- Use markdown formatting sparingly: headers for structure, code blocks for code, "
    "bold for emphasis. Do not over-format.\n"
    "- Do not add decorative prefixes like 'Great question!' or 'Sure thing!'.\n"
    "- Do not use bullet points when a short sentence suffices.\n"
    "- When showing commands or code, use fenced code blocks with the language tag.\n"
    "- Keep explanations direct. State what you found, what it means, and what to do next."
)


def _tool_round_budget_addendum() -> str:
    """Tell the model the per-turn tool round cap so it can wrap up before the hard limit."""
    n = max(1, eff_int("AI_MAX_TOOL_ROUNDS"))
    return (
        "\n\n## Tool-use budget (this assistant turn)\n"
        f"This turn allows at most **{n} tool-use round(s)**. Each round is: you request tools → "
        "results are returned → you may request tools again. "
        "Budget deliberately: take only the tool calls you need, avoid redundant exploration, and "
        "**move toward a clear final answer in plain text** before you run out of rounds. "
        "If the task is too large to finish within this budget, summarize progress, what remains, and "
        "what the user should do next (including continuing in a new message)."
    )


REPO_TOOLS_ADDENDUM = (
    "\n\nYou have access to the project's code repositories via repo_* tools. "
    "Start with repo_list_sources to see available repos, then use "
    "repo_get_file_tree to understand the structure before reading specific files. "
    "Use repo_search_code to find definitions, usages, or patterns across the codebase. "
    "Only read files that are relevant to the user's question."
)

CLUSTER_TOOLS_ADDENDUM = (
    "\n\nYou have access to live Kubernetes clusters attached to this project. "
    "Use the k8s_* tools to query cluster state, fetch logs, run diagnostics, or execute tests. "
    "Only fetch what you need — do NOT dump all resources at once.\n\n"
    "IMPORTANT RULES for cluster interaction:\n"
    "1. PREFER read-only tools (k8s_get_resources, k8s_get_logs, k8s_get_events, k8s_get_namespaces, "
    "k8s_list_crds) over k8s_run_command. These are faster and don't require image pulls.\n"
    "2. Only use k8s_run_command when the read-only tools truly cannot answer the question.\n"
    "3. NEVER use Docker Hub images (bitnami/*, docker.io/*) — most clusters cannot pull from Docker Hub. "
    "Use registry.access.redhat.com/ubi9/ubi-minimal:latest for general commands, or ask the user for "
    "a suitable image if you need specific tools (e.g. a test runner image).\n"
    "4. For context clusters (read-only), you can only query resources and logs.\n"
    "5. For test clusters (read-write), you can also apply manifests, run commands, and delete resources.\n"
    "6. When the user asks to 'run tests' or 'run e2e', PREFER using local_run_command (which runs "
    "on the server with full toolchains like Go, Python, Make) over k8s_run_command. The local tool "
    "automatically injects KUBECONFIG for cluster access."
)

LOCAL_TOOLS_ADDENDUM = (
    "\n\nYou have access to local_run_command which runs shell commands on the server "
    "inside cloned repository directories. This is your primary tool for building code, "
    "running tests (e2e, unit, integration), executing Makefiles, and any task that needs "
    "the repo source code plus a connection to a cluster.\n"
    "The KUBECONFIG is automatically injected so kubectl, oc, go test, and make commands "
    "can reach the attached cluster. Use this instead of k8s_run_command for test execution.\n"
    "Workflow for running tests:\n"
    "1. Use repo_list_sources to find the repo\n"
    "2. Use repo_get_file_tree or repo_search_code to find test targets (Makefile, test scripts)\n"
    "3. Use local_run_command to execute the tests\n"
    "Example: local_run_command(repo_name='opendatahub-operator', command='make e2e-test')"
)

ARTIFACT_TOOLS_ADDENDUM = (
    "\n\n## Session documents (required for reports and exports)\n"
    "You have artifact_* tools for this chat session only. "
    "They read and write files under a dedicated session folder (not the git repos). "
    "Whenever the user asks for a report, document, summary export, or any deliverable "
    "they should keep or download, you MUST use artifact_write_file to save it "
    "(e.g. under `reports/` or `docs/`). Do not only paste long deliverables in chat — "
    "persist them so they appear in the Explorer under \"Session documents\". "
    "Use artifact_list_directory and artifact_read_file to inspect what already exists."
)

MCP_TOOLS_ADDENDUM = (
    "\n\nYou have access to MCP skill tools (prefixed with mcp_<skill>__). "
    "These connect to external services like Jira, GitHub, and others. "
    "Use them when you need to interact with issue trackers, create PRs, "
    "transition tickets, search for issues, etc. "
    "The tool name format is mcp_<skill>__<tool_name> -- e.g., "
    "mcp_atlassian__jira_search or mcp_github__create_pull_request.\n\n"
    "IMPORTANT tips for Jira/Atlassian searches:\n"
    "- Always include maxResults (e.g. maxResults=20) in JQL search calls to avoid timeouts.\n"
    "- Prefer reading specific issues by key (jira_get_issue) over broad searches.\n"
    "- For large backlogs, paginate: use startAt + maxResults.\n"
    "- Narrow JQL with project, status, assignee, or date filters.\n"
    "- If a search times out, retry with a more specific query."
)

# ---------------------------------------------------------------------------
# Context assembly (lightweight — repos/clusters use tools)
# ---------------------------------------------------------------------------


async def assemble_context(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    session_id: uuid.UUID,
    max_tokens: int | None = None,
) -> str:
    parts: list[str] = []
    token_budget = max_tokens or eff_int("AI_CONTEXT_ASSEMBLY_MAX_TOKENS")
    tokens_used = 0

    layer_result = await db.execute(
        select(SessionLayer)
        .where(SessionLayer.session_id == session_id)
        .order_by(SessionLayer.created_at.asc())
    )
    layers = layer_result.scalars().all()
    for layer in layers:
        est = layer.token_count or 0
        if tokens_used + est > token_budget:
            break
        if layer.cached_content:
            content = layer.cached_content.get("text", "")
            if content:
                parts.append(f"--- Layer: {layer.label} ({layer.type.value}) ---\n{content}")
                tokens_used += est

    return "\n\n".join(parts)


async def _has_clusters(db: AsyncSession, project_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(ProjectCluster.id)
        .where(ProjectCluster.project_id == project_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _has_repos(db: AsyncSession, project_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(ContextSource.id)
        .where(
            ContextSource.project_id == project_id,
            ContextSource.type.in_([
                ContextSourceType.github_repo,
                ContextSourceType.gitlab_repo,
            ]),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def resolve_secrets(
    db: AsyncSession,
    project_id: uuid.UUID,
    text: str,
) -> str:
    """Replace {{secret:key}} placeholders with decrypted values at runtime."""
    from app.core.secret_vault import decrypt

    keys = find_placeholders(text)
    if not keys:
        return text

    result = await db.execute(
        select(ProjectSecret).where(
            ProjectSecret.project_id == project_id,
            ProjectSecret.placeholder_key.in_(keys),
        )
    )
    secrets_map: dict[str, str] = {}
    for secret in result.scalars().all():
        try:
            secrets_map[secret.placeholder_key] = decrypt(
                secret.encrypted_value, secret.nonce, secret.tag
            )
        except Exception:
            pass

    return replace_placeholders(text, secrets_map)


def _model_to_api(display_or_id: str) -> str:
    for model_id, info in AVAILABLE_MODELS.items():
        if display_or_id in (model_id, info["display_name"]):
            return model_id
    return "claude-sonnet-4-5-20250929"


# ---------------------------------------------------------------------------
# Conversation history: cache-first, DB fallback
# ---------------------------------------------------------------------------


async def _load_conversation(
    db: AsyncSession,
    session_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Return the conversation for a session, preferring the in-memory cache.

    On cache miss (e.g. server restart) we rebuild from DB messages. Since the
    DB only stores user prompts and final assistant text (no tool blocks), the
    model loses tool-call memory — but the text answers still provide context.
    """
    cached = _cache_get(session_id)
    if cached is not None:
        return cached

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()
    conversation: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == MessageRole.system:
            continue
        conversation.append({
            "role": msg.role.value,
            "content": msg.content,
        })
    _cache_set(session_id, conversation)
    return conversation


def _estimate_chars(conversation: list[dict[str, Any]]) -> int:
    """Rough character count of a conversation list."""
    total = 0
    for msg in conversation:
        content = msg.get("content")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += len(str(block.get("text", "")))
                    total += len(str(block.get("content", "")))
                    total += len(str(block.get("input", "")))
                else:
                    total += len(str(block))
    return total


async def _maybe_summarise(
    conversation: list[dict[str, Any]],
    client: Any,
    model: str,
) -> list[dict[str, Any]]:
    """If the conversation exceeds the char budget, summarise older turns.

    Keeps the most recent turns intact and replaces older turns with a single
    summary message so the model retains awareness without token explosion.
    """
    if _estimate_chars(conversation) <= settings.AI_MAX_CACHE_CHARS:
        return conversation

    # Keep the last N messages intact (typically user/assistant pairs).
    # Never split an assistant tool_use from its tool_result user message.
    keep_recent = settings.AI_SUMMARY_KEEP_RECENT_MESSAGES
    if len(conversation) <= keep_recent:
        return conversation

    cut = _safe_summarise_cut(conversation, keep_recent)
    older = conversation[:cut]
    recent = conversation[cut:]
    if not older:
        return conversation

    older_text_parts = []
    for msg in older:
        role = msg["role"]
        content = msg.get("content", "")
        if isinstance(content, str):
            older_text_parts.append(
                f"{role}: {content[: settings.AI_SUMMARY_STRING_SNIPPET_CHARS]}"
            )
        elif isinstance(content, list):
            summaries = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_use":
                        summaries.append(f"called {block.get('name', '?')}")
                    elif block.get("type") == "tool_result":
                        summaries.append(f"tool result ({len(str(block.get('content', '')))} chars)")
                    elif block.get("type") == "text":
                        summaries.append(
                            block.get("text", "")[: settings.AI_SUMMARY_TOOL_TEXT_SNIPPET_CHARS]
                        )
            older_text_parts.append(f"{role}: {'; '.join(summaries)}")

    older_text = "\n".join(older_text_parts)
    if len(older_text) > settings.AI_SUMMARY_OLDER_BLOB_MAX_CHARS:
        older_text = (
            older_text[: settings.AI_SUMMARY_OLDER_BLOB_MAX_CHARS] + "\n…(truncated)"
        )

    try:
        summary_resp = client.messages.create(
            model=model,
            max_tokens=settings.AI_SUMMARY_CALL_MAX_TOKENS,
            system="Summarise the following conversation history concisely. "
                   "Focus on key findings, decisions, tool results, and open questions. "
                   "Write in third person. Be brief.",
            messages=[{"role": "user", "content": older_text}],
        )
        summary_text = "".join(
            b.text for b in summary_resp.content if hasattr(b, "text")
        )
    except Exception as exc:
        logger.warning("Summarisation failed, trimming instead: %s", exc)
        summary_text = older_text[: settings.AI_SUMMARY_TARGET_CHARS]

    summary_msg = {
        "role": "user",
        "content": f"[Earlier conversation summary]\n{summary_text}",
    }
    return [summary_msg] + recent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_text(response: Any) -> str:
    parts = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)
    return "".join(parts)


def _extract_tool_uses(response: Any) -> list[dict[str, Any]]:
    uses = []
    for block in response.content:
        if block.type == "tool_use":
            uses.append({
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return uses


def _assistant_tool_use_ids(msg: dict[str, Any]) -> list[str]:
    content = msg.get("content")
    if not isinstance(content, list):
        return []
    ids: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tid = block.get("id")
            if tid:
                ids.append(tid)
    return ids


def _user_tool_result_ids(msg: dict[str, Any]) -> set[str]:
    content = msg.get("content")
    if not isinstance(content, list):
        return set()
    out: set[str] = set()
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            tuid = block.get("tool_use_id")
            if tuid:
                out.add(tuid)
    return out


def _repair_tool_use_tool_result_pairs(conversation: list[dict[str, Any]]) -> None:
    """Ensure each assistant ``tool_use`` has a matching user ``tool_result`` next message.

    Anthropic/Vertex require tool results in the message immediately following
    the assistant turn. Repairs cache/summarisation edge cases in place.
    """
    synthetic = (
        "Error: tool result was missing in session history "
        "(Orbit repaired this turn for API compatibility)."
    )
    i = 0
    while i < len(conversation):
        msg = conversation[i]
        if msg.get("role") != "assistant":
            i += 1
            continue
        tu_ids = _assistant_tool_use_ids(msg)
        if not tu_ids:
            i += 1
            continue

        if i + 1 >= len(conversation):
            conversation.append({
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tid, "content": synthetic}
                    for tid in tu_ids
                ],
            })
            break

        nxt = conversation[i + 1]
        if nxt.get("role") != "user":
            conversation.insert(
                i + 1,
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": tid, "content": synthetic}
                        for tid in tu_ids
                    ],
                },
            )
            i += 2
            continue

        found = _user_tool_result_ids(nxt)
        missing = [t for t in tu_ids if t not in found]
        if not missing:
            i += 2
            continue

        nc = nxt.get("content")
        if isinstance(nc, list):
            for mid in missing:
                nc.append({"type": "tool_result", "tool_use_id": mid, "content": synthetic})
        else:
            conversation.insert(
                i + 1,
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": mid, "content": synthetic}
                        for mid in missing
                    ],
                },
            )
        i += 2


def _safe_summarise_cut(conversation: list[dict[str, Any]], keep_recent: int) -> int:
    """Index to split conversation for summarisation without splitting tool pairs."""
    cut = max(0, len(conversation) - keep_recent)
    while cut > 0 and cut < len(conversation):
        prev = conversation[cut - 1]
        cur = conversation[cut]
        if prev.get("role") != "assistant" or not _assistant_tool_use_ids(prev):
            break
        if cur.get("role") != "user":
            break
        cur_content = cur.get("content")
        only_tool_results = (
            isinstance(cur_content, list)
            and bool(cur_content)
            and all(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in cur_content
            )
        )
        if only_tool_results:
            cut -= 1
            continue
        break
    return cut


def _serialize_content_blocks(blocks: Any) -> list[dict[str, Any]]:
    """Convert Anthropic SDK content blocks to JSON-serialisable dicts.

    Preserves compaction blocks so the API can drop pre-compaction messages
    on subsequent calls.
    """
    out = []
    for b in blocks:
        if b.type == "text":
            out.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            out.append({
                "type": "tool_use",
                "id": b.id,
                "name": b.name,
                "input": b.input,
            })
        elif b.type == "compaction":
            out.append({
                "type": "compaction",
                "content": b.content,
            })
    return out


# ---------------------------------------------------------------------------
# API call helper: compaction vs standard
# ---------------------------------------------------------------------------


def _create_message(
    client: Any,
    model_id: str,
    create_kwargs: dict[str, Any],
) -> Any:
    """Call the Messages API, using the compaction beta for supported models."""
    msgs = create_kwargs.get("messages")
    if isinstance(msgs, list):
        _repair_tool_use_tool_result_pairs(msgs)
    if model_id in settings.ai_compaction_model_ids_set:
        return client.beta.messages.create(
            betas=[settings.AI_COMPACTION_BETA],
            context_management={
                "edits": [{
                    "type": "compact_20260112",
                    "trigger": {
                        "type": "input_tokens",
                        "value": settings.AI_COMPACTION_TRIGGER_TOKENS,
                    },
                }],
            },
            **create_kwargs,
        )
    return client.messages.create(**create_kwargs)


# ---------------------------------------------------------------------------
# Conversation compaction (mid-loop, manual fallback)
# ---------------------------------------------------------------------------


def _trim_tool_result(content: str) -> str:
    """Shorten a tool result string for conversation history."""
    lim = settings.AI_TOOL_RESULT_TRIM_CHARS
    if len(content) <= lim:
        return content
    half = lim // 2
    return (
        content[:half]
        + f"\n\n... ({len(content) - lim} chars trimmed) ...\n\n"
        + content[-half:]
    )


def _compact_old_tool_results(conversation: list[dict[str, Any]]) -> None:
    """Trim tool_result blocks in older turns so the conversation stays within budget.

    Mutates the conversation in-place. Keeps the last 4 messages untouched
    (the most recent tool round) so the model still has full context for
    the current analysis step.
    """
    keep_recent = settings.AI_COMPACT_KEEP_RECENT_MESSAGES
    for msg in conversation[:-keep_recent] if len(conversation) > keep_recent else []:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                val = block.get("content", "")
                if isinstance(val, str) and len(val) > settings.AI_TOOL_RESULT_TRIM_CHARS:
                    block["content"] = _trim_tool_result(val)


# ---------------------------------------------------------------------------
# Workflow lookup
# ---------------------------------------------------------------------------


async def _get_workflow_prompt(db: AsyncSession, ai_config: dict[str, Any] | None) -> str:
    """Resolve the workflow system prompt from session ai_config."""
    slug = (ai_config or {}).get("workflow", "general_chat")
    if not slug or slug == "general_chat":
        return ""
    from app.models.workflow import Workflow
    result = await db.execute(select(Workflow).where(Workflow.slug == slug))
    wf = result.scalar_one_or_none()
    if wf is None:
        return ""
    return wf.system_prompt or ""


# ---------------------------------------------------------------------------
# Main chat stream
# ---------------------------------------------------------------------------


async def chat_stream(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    session_id: uuid.UUID,
    user_message: str,
    model: str = "claude-sonnet-4-5-20250929",
    ai_config: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream a chat response from Claude with agentic tool-use.

    Conversation history lives in an in-memory cache (with full tool blocks).
    Only user prompts and final assistant text are persisted to the DB.
    """
    async with project_runtime_context(db, project_id):
        model_id = _model_to_api(model)
        model_info = AVAILABLE_MODELS.get(model_id, AVAILABLE_MODELS["claude-sonnet-4-5-20250929"])

        yield {"type": "activity", "action": "Assembling context", "status": "running", "icon": "search"}

        context = await assemble_context(
            db, project_id=project_id, session_id=session_id,
            max_tokens=eff_int("AI_CONTEXT_ASSEMBLY_MAX_TOKENS"),
        )
        has_k8s = await _has_clusters(db, project_id)
        has_repos = await _has_repos(db, project_id)

        yield {"type": "activity", "action": "Assembling context", "status": "done", "icon": "search"}

        # Resolve workflow system prompt
        workflow_prompt = await _get_workflow_prompt(db, ai_config)

        # Build system prompt
        system_parts = [SYSTEM_PROMPT_HEADER]
        if workflow_prompt:
            system_parts.append(f"\n\n## Workflow Instructions\n\n{workflow_prompt}")
        if context:
            system_parts.append(f"\n\n## Session Context\n\n{context}")
        if has_repos:
            system_parts.append(REPO_TOOLS_ADDENDUM)
        if has_k8s:
            system_parts.append(CLUSTER_TOOLS_ADDENDUM)
        if has_repos and has_k8s:
            system_parts.append(LOCAL_TOOLS_ADDENDUM)

        mcp_tools = await mcp_client.get_tool_definitions(db)
        has_mcp = len(mcp_tools) > 0
        if has_mcp:
            system_parts.append(MCP_TOOLS_ADDENDUM)
        system_parts.append(ARTIFACT_TOOLS_ADDENDUM)

        # Build tool list before finalizing system prompt (budget text only if tools exist).
        tools: list[dict[str, Any]] = []
        if has_repos:
            tools.extend(repo_tools.get_tool_definitions())
        tools.extend(session_artifact_tools.get_tool_definitions())
        if has_k8s:
            tools.extend(kube_tools.get_tool_definitions())
        if has_repos and has_k8s:
            tools.extend(local_tools.get_tool_definitions())
        if has_mcp:
            tools.extend(mcp_tools)
        if tools:
            system_parts.append(_tool_round_budget_addendum())
        system_prompt = "".join(system_parts)

        # Load conversation from cache (or cold-start from DB)
        conversation = await _load_conversation(db, session_id)
        conversation.append({"role": "user", "content": user_message})

        client = get_ai_client()
        wire_model = _resolve_model_for_provider(model_id)
        use_compaction = model_id in settings.ai_compaction_model_ids_set

        # Manual summarisation only for models without server-side compaction
        if not use_compaction:
            conversation = await _maybe_summarise(conversation, client, wire_model)

        yield {"type": "activity", "action": f"Calling {model_info['display_name']}", "status": "running", "icon": "terminal"}

        try:
            create_kwargs: dict[str, Any] = {
                "model": wire_model,
                "max_tokens": model_info["max_tokens"],
                "system": system_prompt,
                "messages": conversation,
            }
            if tools:
                create_kwargs["tools"] = tools

            response = _create_message(client, model_id, create_kwargs)

            yield {"type": "activity", "action": f"Calling {model_info['display_name']}", "status": "done", "icon": "terminal"}

            # --- Agentic tool-use loop ---
            # Run whenever the model emitted tool_use blocks, not only when
            # stop_reason == "tool_use" (e.g. Vertex may use other stop reasons).
            # Each increment is one batch: assistant tool_use → tool_result → next assistant message.
            max_tool_rounds = eff_int("AI_MAX_TOOL_ROUNDS")
            rounds = 0
            while rounds < max_tool_rounds:
                tool_uses = _extract_tool_uses(response)
                if not tool_uses:
                    break
                rounds += 1

                partial_text = _extract_text(response)
                if partial_text:
                    yield {"type": "text_delta", "text": partial_text}

                # Store full content blocks (including any compaction blocks)
                serialized = _serialize_content_blocks(response.content)
                conversation.append({"role": "assistant", "content": serialized})

                tool_results = []
                for tu in tool_uses:
                    is_artifact = tu["name"].startswith("artifact_")
                    is_repo = tu["name"].startswith("repo_")
                    is_local = tu["name"].startswith("local_")
                    is_mcp = mcp_client.is_mcp_tool(tu["name"])
                    if is_artifact:
                        label = session_artifact_tools.get_tool_activity_label(
                            tu["name"], tu["input"]
                        )
                    elif is_repo:
                        label = repo_tools.get_tool_activity_label(tu["name"], tu["input"])
                    elif is_local:
                        label = local_tools.get_tool_activity_label(tu["name"], tu["input"])
                    elif is_mcp:
                        label = await mcp_client.get_tool_activity_label(tu["name"], tu["input"])
                    else:
                        label = kube_tools.get_tool_activity_label(tu["name"], tu["input"])
                    yield {"type": "activity", "action": label, "status": "running", "icon": "terminal"}

                    if is_artifact:
                        _task = asyncio.create_task(
                            session_artifact_tools.execute_tool(
                                tu["name"], tu["input"], project_id, session_id, db
                            )
                        )
                    elif is_repo:
                        _task = asyncio.create_task(
                            repo_tools.execute_tool(tu["name"], tu["input"], project_id, db)
                        )
                    elif is_local:
                        _task = asyncio.create_task(
                            local_tools.execute_tool(tu["name"], tu["input"], project_id, db)
                        )
                    elif is_mcp:
                        _task = asyncio.create_task(
                            mcp_client.execute_tool(tu["name"], tu["input"], db)
                        )
                    else:
                        _task = asyncio.create_task(
                            kube_tools.execute_tool(tu["name"], tu["input"], project_id, db)
                        )

                    try:
                        while True:
                            try:
                                result_str = await asyncio.wait_for(
                                    asyncio.shield(_task),
                                    timeout=eff_float("AI_TOOL_SSE_HEARTBEAT_SEC"),
                                )
                                break
                            except asyncio.TimeoutError:
                                yield {
                                    "type": "activity",
                                    "action": f"{label} (still running…)",
                                    "status": "running",
                                    "icon": "terminal",
                                }
                    except Exception as tool_exc:
                        logger.exception("Tool execution failed: %s", tu["name"])
                        result_str = f"Error executing tool: {tool_exc}"

                    yield {"type": "activity", "action": label, "status": "done", "icon": "terminal"}

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": result_str,
                    })

                conversation.append({"role": "user", "content": tool_results})

                # Manual compaction only when the server isn't handling it
                if not use_compaction and _estimate_chars(conversation) > settings.AI_MID_LOOP_COMPACT_CHARS:
                    _compact_old_tool_results(conversation)
                    logger.info("Compacted conversation mid-loop (round %d)", rounds)

                yield {"type": "activity", "action": f"Calling {model_info['display_name']}", "status": "running", "icon": "terminal"}
                response = _create_message(client, model_id, {**create_kwargs, "messages": conversation})
                yield {"type": "activity", "action": f"Calling {model_info['display_name']}", "status": "done", "icon": "terminal"}

            # If the last assistant reply still contains tool_use blocks (limit reached, or we could
            # not enter another loop iteration), synthesize tool_result rows and ask for a text-only
            # follow-up. Preserve any plain text already in that assistant turn — recovery replaces
            # ``response``, so we merge it below.
            pending_tools = _extract_tool_uses(response)
            preface_at_limit = _extract_text(response) if pending_tools else ""
            if pending_tools:
                logger.warning(
                    "Max tool rounds (%s) reached with pending tool calls; synthesizing results "
                    "and requesting a text-only summary",
                    max_tool_rounds,
                )
                serialized = _serialize_content_blocks(response.content)
                conversation.append({"role": "assistant", "content": serialized})
                synthetic = (
                    "Orbit did not run these tools: the tool-use limit for this message was reached "
                    f"({max_tool_rounds} tool rounds). Reply in plain text only (no tools): summarize "
                    "progress, what is left to do, and whether the user should continue in a new message "
                    "or narrow the task."
                )
                conversation.append({
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": tu["id"], "content": synthetic}
                        for tu in pending_tools
                    ],
                })
                if not use_compaction and _estimate_chars(conversation) > settings.AI_MID_LOOP_COMPACT_CHARS:
                    _compact_old_tool_results(conversation)
                yield {"type": "activity", "action": f"Calling {model_info['display_name']}", "status": "running", "icon": "terminal"}
                recovery_kwargs = {**create_kwargs, "messages": conversation}
                recovery_kwargs.pop("tools", None)
                response = _create_message(client, model_id, recovery_kwargs)
                yield {"type": "activity", "action": f"Calling {model_info['display_name']}", "status": "done", "icon": "terminal"}

                # Some models still return tool_use on the first tool-less call; nudge once more.
                if _extract_tool_uses(response) or not _extract_text(response).strip():
                    conversation.append({
                        "role": "user",
                        "content": (
                            "Answer in plain text only. Do not use tools. If you already started an "
                            "explanation above, finish it; otherwise briefly say what was blocked and "
                            "what the user should do next."
                        ),
                    })
                    yield {"type": "activity", "action": f"Calling {model_info['display_name']}", "status": "running", "icon": "terminal"}
                    recovery_kwargs2 = {**create_kwargs, "messages": conversation}
                    recovery_kwargs2.pop("tools", None)
                    response = _create_message(client, model_id, recovery_kwargs2)
                    yield {"type": "activity", "action": f"Calling {model_info['display_name']}", "status": "done", "icon": "terminal"}

            # --- Final text response (with continuation if truncated) ---
            full_text = _extract_text(response)
            if preface_at_limit.strip():
                recovery_body = full_text.strip()
                pre = preface_at_limit.strip()
                if not recovery_body:
                    full_text = pre
                elif pre and pre not in recovery_body:
                    full_text = f"{pre}\n\n{recovery_body}"
                else:
                    full_text = recovery_body or pre
            if not full_text.strip():
                full_text = (
                    "The model returned no text (often after a long tool loop). "
                    "Try a follow-up message to continue, or split the task into smaller steps."
                )

            continuations = 0
            while response.stop_reason == "max_tokens" and continuations < eff_int("AI_MAX_CONTINUATIONS"):
                continuations += 1
                logger.info(
                    "Response truncated (max_tokens), continuing (%d/%d)",
                    continuations,
                    eff_int("AI_MAX_CONTINUATIONS"),
                )
                yield {"type": "activity", "action": "Continuing response", "status": "running", "icon": "terminal"}

                conversation.append({"role": "assistant", "content": full_text})
                conversation.append({"role": "user", "content": "Continue from where you left off."})

                if not use_compaction and _estimate_chars(conversation) > settings.AI_MID_LOOP_COMPACT_CHARS:
                    _compact_old_tool_results(conversation)

                response = _create_message(client, model_id, {**create_kwargs, "messages": conversation})
                continuation_text = _extract_text(response)
                full_text += continuation_text

                yield {"type": "activity", "action": "Continuing response", "status": "done", "icon": "terminal"}

                conversation.pop()
                conversation.pop()

            yield {"type": "activity", "action": "Generating response", "status": "running", "icon": "dot"}

            chunk_size = settings.AI_SSE_TEXT_CHUNK_SIZE
            for i in range(0, len(full_text), chunk_size):
                yield {"type": "text_delta", "text": full_text[i:i + chunk_size]}

            yield {"type": "activity", "action": "Generating response", "status": "done", "icon": "dot"}

            # Store full content blocks for the final response too (may include
            # compaction blocks that the API needs on subsequent turns)
            if use_compaction:
                final_serialized = _serialize_content_blocks(response.content)
                conversation.append({"role": "assistant", "content": final_serialized})
            else:
                conversation.append({"role": "assistant", "content": full_text})

            # Persist the cache
            _cache_set(session_id, conversation)

            # Save only user message + final answer to DB (for chat UI display)
            assistant_msg = Message(
                session_id=session_id,
                role=MessageRole.assistant,
                content=full_text,
                metadata_={
                    "model": model_id,
                    "tool_rounds": rounds,
                    "usage": {
                        "input_tokens": getattr(response.usage, "input_tokens", None),
                        "output_tokens": getattr(response.usage, "output_tokens", None),
                    },
                },
            )
            db.add(assistant_msg)
            await db.commit()
            await db.refresh(assistant_msg)

            yield {
                "type": "message_complete",
                "message_id": str(assistant_msg.id),
                "content": full_text,
            }

        except Exception as exc:
            logger.exception("Chat stream error")
            _repair_tool_use_tool_result_pairs(conversation)
            _cache_set(session_id, conversation)
            yield {"type": "error", "message": str(exc)}
