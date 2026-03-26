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

import logging
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.secret_vault import find_placeholders, replace_placeholders
from app.models.cluster import ProjectCluster
from app.models.context import ContextSource, ContextSourceType, SessionLayer
from app.models.secret import ProjectSecret
from app.models.session import Message, MessageRole
from app.services.ai_client import get_ai_client
from app.services import kube_tools
from app.services import local_tools
from app.services import repo_tools

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

AVAILABLE_MODELS: dict[str, dict[str, Any]] = {
    "claude-opus-4-6": {
        "display_name": "Claude Opus 4.6",
        "description": "Most capable for complex work",
        "max_tokens": 16384,
        "vertex_id": "claude-opus-4-6",
    },
    "claude-sonnet-4-6": {
        "display_name": "Claude Sonnet 4.6",
        "description": "Best for everyday tasks",
        "max_tokens": 16384,
        "vertex_id": "claude-sonnet-4-6",
    },
    "claude-sonnet-4-5-20250929": {
        "display_name": "Claude Sonnet 4.5",
        "description": "Balanced performance for agents and coding",
        "max_tokens": 16384,
        "vertex_id": "claude-sonnet-4-5@20250929",
    },
    "claude-haiku-4-5-20251001": {
        "display_name": "Claude Haiku 4.5",
        "description": "Fastest for quick answers",
        "max_tokens": 8192,
        "vertex_id": "claude-haiku-4-5-20251001",
    },
}

MAX_TOOL_ROUNDS = 15

# Rough token estimate: 1 token ≈ 4 chars.  We target keeping the cached
# conversation under ~180K tokens so the model still has headroom to respond.
MAX_CACHE_CHARS = 700_000
SUMMARY_TARGET_CHARS = 8_000

# ---------------------------------------------------------------------------
# In-memory session conversation cache
# ---------------------------------------------------------------------------
# Maps session_id → list of Anthropic-format messages (including tool blocks).
# Uses an LRU OrderedDict to cap memory at ~200 sessions.

MAX_CACHED_SESSIONS = 200

_conversation_cache: OrderedDict[uuid.UUID, list[dict[str, Any]]] = OrderedDict()


def _cache_get(session_id: uuid.UUID) -> list[dict[str, Any]] | None:
    if session_id in _conversation_cache:
        _conversation_cache.move_to_end(session_id)
        return _conversation_cache[session_id]
    return None


def _cache_set(session_id: uuid.UUID, conversation: list[dict[str, Any]]) -> None:
    _conversation_cache[session_id] = conversation
    _conversation_cache.move_to_end(session_id)
    while len(_conversation_cache) > MAX_CACHED_SESSIONS:
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
    token_budget = max_tokens or 100_000
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
    if _estimate_chars(conversation) <= MAX_CACHE_CHARS:
        return conversation

    # Keep the last 6 messages intact (typically 3 user/assistant pairs)
    keep_recent = 6
    if len(conversation) <= keep_recent:
        return conversation

    older = conversation[:-keep_recent]
    recent = conversation[-keep_recent:]

    older_text_parts = []
    for msg in older:
        role = msg["role"]
        content = msg.get("content", "")
        if isinstance(content, str):
            older_text_parts.append(f"{role}: {content[:2000]}")
        elif isinstance(content, list):
            summaries = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_use":
                        summaries.append(f"called {block.get('name', '?')}")
                    elif block.get("type") == "tool_result":
                        summaries.append(f"tool result ({len(str(block.get('content', '')))} chars)")
                    elif block.get("type") == "text":
                        summaries.append(block.get("text", "")[:500])
            older_text_parts.append(f"{role}: {'; '.join(summaries)}")

    older_text = "\n".join(older_text_parts)
    if len(older_text) > 30_000:
        older_text = older_text[:30_000] + "\n…(truncated)"

    try:
        summary_resp = client.messages.create(
            model=model,
            max_tokens=2048,
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
        summary_text = older_text[:SUMMARY_TARGET_CHARS]

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


def _serialize_content_blocks(blocks: Any) -> list[dict[str, Any]]:
    """Convert Anthropic SDK content blocks to JSON-serialisable dicts."""
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
    return out


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
) -> AsyncIterator[dict[str, Any]]:
    """Stream a chat response from Claude with agentic tool-use.

    Conversation history lives in an in-memory cache (with full tool blocks).
    Only user prompts and final assistant text are persisted to the DB.
    """
    model_id = _model_to_api(model)
    model_info = AVAILABLE_MODELS.get(model_id, AVAILABLE_MODELS["claude-sonnet-4-5-20250929"])

    yield {"type": "activity", "action": "Assembling context", "status": "running", "icon": "search"}

    context = await assemble_context(
        db, project_id=project_id, session_id=session_id,
        max_tokens=100_000,
    )
    has_k8s = await _has_clusters(db, project_id)
    has_repos = await _has_repos(db, project_id)

    yield {"type": "activity", "action": "Assembling context", "status": "done", "icon": "search"}

    # Build system prompt
    system_parts = [SYSTEM_PROMPT_HEADER]
    if context:
        system_parts.append(f"\n\n## Session Context\n\n{context}")
    if has_repos:
        system_parts.append(REPO_TOOLS_ADDENDUM)
    if has_k8s:
        system_parts.append(CLUSTER_TOOLS_ADDENDUM)
    if has_repos and has_k8s:
        system_parts.append(LOCAL_TOOLS_ADDENDUM)
    system_prompt = "".join(system_parts)

    # Build tool list
    tools: list[dict[str, Any]] = []
    if has_repos:
        tools.extend(repo_tools.get_tool_definitions())
    if has_k8s:
        tools.extend(kube_tools.get_tool_definitions())
    if has_repos and has_k8s:
        tools.extend(local_tools.get_tool_definitions())

    # Load conversation from cache (or cold-start from DB)
    conversation = await _load_conversation(db, session_id)
    conversation.append({"role": "user", "content": user_message})

    client = get_ai_client()
    wire_model = _resolve_model_for_provider(model_id)

    # Summarise if conversation is too long
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

        response = client.messages.create(**create_kwargs)

        yield {"type": "activity", "action": f"Calling {model_info['display_name']}", "status": "done", "icon": "terminal"}

        # --- Agentic tool-use loop ---
        rounds = 0
        while response.stop_reason == "tool_use" and rounds < MAX_TOOL_ROUNDS:
            rounds += 1
            tool_uses = _extract_tool_uses(response)

            partial_text = _extract_text(response)
            if partial_text:
                yield {"type": "text_delta", "text": partial_text}

            # Add assistant tool-call turn to in-memory conversation
            serialized = _serialize_content_blocks(response.content)
            conversation.append({"role": "assistant", "content": serialized})

            tool_results = []
            for tu in tool_uses:
                is_repo = tu["name"].startswith("repo_")
                is_local = tu["name"].startswith("local_")
                if is_repo:
                    label = repo_tools.get_tool_activity_label(tu["name"], tu["input"])
                elif is_local:
                    label = local_tools.get_tool_activity_label(tu["name"], tu["input"])
                else:
                    label = kube_tools.get_tool_activity_label(tu["name"], tu["input"])
                yield {"type": "activity", "action": label, "status": "running", "icon": "terminal"}

                if is_repo:
                    result_str = await repo_tools.execute_tool(
                        tu["name"], tu["input"], project_id, db
                    )
                elif is_local:
                    result_str = await local_tools.execute_tool(
                        tu["name"], tu["input"], project_id, db
                    )
                else:
                    result_str = await kube_tools.execute_tool(
                        tu["name"], tu["input"], project_id, db
                    )

                yield {"type": "activity", "action": label, "status": "done", "icon": "terminal"}

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": result_str,
                })

            # Add tool results to in-memory conversation
            conversation.append({"role": "user", "content": tool_results})

            yield {"type": "activity", "action": f"Calling {model_info['display_name']}", "status": "running", "icon": "terminal"}
            response = client.messages.create(**{**create_kwargs, "messages": conversation})
            yield {"type": "activity", "action": f"Calling {model_info['display_name']}", "status": "done", "icon": "terminal"}

        # --- Final text response ---
        full_text = _extract_text(response)

        yield {"type": "activity", "action": "Generating response", "status": "running", "icon": "dot"}

        chunk_size = 40
        for i in range(0, len(full_text), chunk_size):
            yield {"type": "text_delta", "text": full_text[i:i + chunk_size]}

        yield {"type": "activity", "action": "Generating response", "status": "done", "icon": "dot"}

        # Add final assistant text to in-memory conversation
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
        # Still save the cache so partial tool work isn't lost
        _cache_set(session_id, conversation)
        yield {"type": "error", "message": str(exc)}
