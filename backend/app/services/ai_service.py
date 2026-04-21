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
import contextlib
import logging
import re
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
from app.services import kube_tools, local_tools, mcp_client, repo_tools, session_artifact_tools, system_map_service
from app.services.ai_client import get_ai_client
from app.services.runtime_settings import eff_float, eff_int, project_runtime_context
from app.services.session_layer_prompt import layer_to_prompt_chunk

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



_PR_REVIEW_RE = re.compile(
    r"review\s+(?:the\s+)?(?:this\s+)?(?:pr|pull\s*request)"
    r"|review.*github\.com/.+/pull/\d+"
    r"|github\.com/.+/pull/\d+.*review",
    re.IGNORECASE,
)

_CODE_REVIEW_SKILL_SLUG = "review.pr"


def _looks_like_pr_review(message: str) -> bool:
    """Return True if the user message appears to be a PR review request."""
    return bool(_PR_REVIEW_RE.search(message))


async def _resolve_skill(
    db: AsyncSession,
    project_id: uuid.UUID,
    ai_config: dict[str, Any] | None,
    user_message: str,
) -> tuple[str | None, str | None]:
    """Return (slug, system_prompt) for the active skill, or (None, None)."""
    slug = (ai_config or {}).get("skill")

    if not slug and _looks_like_pr_review(user_message):
        slug = _CODE_REVIEW_SKILL_SLUG

    if not slug:
        return None, None

    prompt_skills = await mcp_client.get_all_prompt_skills(db, project_id=project_id)
    for ps in prompt_skills:
        if ps.slug == slug:
            return slug, ps.system_prompt
    return slug, None


# ---------------------------------------------------------------------------
# Write-tool confirmation gate
# ---------------------------------------------------------------------------
_READ_PREFIXES = (
    "get_", "list_", "search_", "read_", "fetch_", "query_", "describe_",
    "count_", "check_", "find_", "show_", "view_",
)

def _is_write_tool(tool_name: str) -> bool:
    """Return True if the tool performs a write/mutation that needs user approval."""
    if tool_name.startswith("repo_") or tool_name.startswith("artifact_"):
        return False
    if tool_name.startswith("k8s_"):
        return tool_name in ("k8s_apply_manifest", "k8s_run_command", "k8s_delete_resource")
    if tool_name.startswith("local_"):
        return True
    base = tool_name.split("__", 1)[-1] if "__" in tool_name else tool_name
    return not any(base.startswith(p) for p in _READ_PREFIXES)


_pending_confirmations: dict[str, asyncio.Event] = {}
_confirmation_results: dict[str, bool] = {}


def confirm_tool_action(session_id: str, tool_use_id: str, approved: bool) -> bool:
    """Called by the API endpoint when the user approves/rejects a write tool."""
    key = f"{session_id}:{tool_use_id}"
    event = _pending_confirmations.get(key)
    if not event:
        return False
    _confirmation_results[key] = approved
    event.set()
    return True


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
        chunk_est = layer_to_prompt_chunk(layer)
        if chunk_est is None:
            continue
        chunk, est = chunk_est
        if tokens_used + est > token_budget:
            break
        parts.append(chunk)
        tokens_used += est

    return "\n\n".join(parts)


async def _feature_enabled(db: AsyncSession, flag: str) -> bool:
    """Check a global feature flag stored in the runtime_settings table."""
    from app.models.runtime_setting import RuntimeSetting

    row = await db.get(RuntimeSetting, "feature_flags")
    if not row or not isinstance(row.value, dict):
        return False
    return bool(row.value.get(flag))


async def _has_clusters(db: AsyncSession, project_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(ProjectCluster.id).where(ProjectCluster.project_id == project_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _has_repos(db: AsyncSession, project_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(ContextSource.id)
        .where(
            ContextSource.project_id == project_id,
            ContextSource.type.in_(
                [
                    ContextSourceType.github_repo,
                    ContextSourceType.gitlab_repo,
                ]
            ),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


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
    *,
    exclude_msg_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """Return the conversation for a session, preferring the in-memory cache.

    On cache miss (e.g. server restart) we rebuild from DB messages. Since the
    DB only stores user prompts and final assistant text (no tool blocks), the
    model loses tool-call memory — but the text answers still provide context.

    ``exclude_msg_id`` omits a specific message (the just-committed user
    message) so callers can append it without duplication.
    """
    cached = _cache_get(session_id)
    if cached is not None:
        return cached

    query = select(Message).where(Message.session_id == session_id, Message.thread_id.is_(None))
    if exclude_msg_id is not None:
        query = query.where(Message.id != exclude_msg_id)
    result = await db.execute(query.order_by(Message.created_at.asc()))
    messages = result.scalars().all()
    conversation: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == MessageRole.system:
            continue
        conversation.append(
            {
                "role": msg.role.value,
                "content": msg.content,
            }
        )
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
                        summaries.append(
                            f"tool result ({len(str(block.get('content', '')))} chars)"
                        )
                    elif block.get("type") == "text":
                        summaries.append(
                            block.get("text", "")[: settings.AI_SUMMARY_TOOL_TEXT_SNIPPET_CHARS]
                        )
            older_text_parts.append(f"{role}: {'; '.join(summaries)}")

    older_text = "\n".join(older_text_parts)
    if len(older_text) > settings.AI_SUMMARY_OLDER_BLOB_MAX_CHARS:
        older_text = older_text[: settings.AI_SUMMARY_OLDER_BLOB_MAX_CHARS] + "\n…(truncated)"

    try:
        summary_resp = client.messages.create(
            model=model,
            max_tokens=settings.AI_SUMMARY_CALL_MAX_TOKENS,
            system="Summarise the following conversation history concisely. "
            "Focus on key findings, decisions, tool results, and open questions. "
            "Write in third person. Be brief.",
            messages=[{"role": "user", "content": older_text}],
        )
        summary_text = "".join(b.text for b in summary_resp.content if hasattr(b, "text"))
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


async def _resolve_tool_input_secrets(
    db: AsyncSession,
    user_id: uuid.UUID,
    tool_input: dict[str, Any],
) -> dict[str, Any]:
    """Replace {{secret:key}} placeholders in tool input string values."""
    keys_found: list[str] = []
    for v in tool_input.values():
        if isinstance(v, str):
            keys_found.extend(find_placeholders(v))
    if not keys_found:
        return tool_input

    from app.core.secret_vault import decrypt as vault_decrypt

    result = await db.execute(
        select(ProjectSecret).where(
            ProjectSecret.created_by == user_id,
            ProjectSecret.placeholder_key.in_(keys_found),
        )
    )
    secrets_map: dict[str, str] = {}
    for secret in result.scalars().all():
        with contextlib.suppress(Exception):
            secrets_map[secret.placeholder_key] = vault_decrypt(
                secret.encrypted_value, secret.nonce, secret.tag
            )

    resolved: dict[str, Any] = {}
    for k, v in tool_input.items():
        if isinstance(v, str):
            resolved[k] = replace_placeholders(v, secrets_map)
        else:
            resolved[k] = v
    return resolved


def _extract_tool_uses(response: Any) -> list[dict[str, Any]]:
    uses = []
    for block in response.content:
        if block.type == "tool_use":
            uses.append(
                {
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
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
            conversation.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": tid, "content": synthetic}
                        for tid in tu_ids
                    ],
                }
            )
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
            and all(isinstance(b, dict) and b.get("type") == "tool_result" for b in cur_content)
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
            out.append(
                {
                    "type": "tool_use",
                    "id": b.id,
                    "name": b.name,
                    "input": b.input,
                }
            )
        elif b.type == "compaction":
            out.append(
                {
                    "type": "compaction",
                    "content": b.content,
                }
            )
    return out


# ---------------------------------------------------------------------------
# API call helper: compaction vs standard
# ---------------------------------------------------------------------------




from anthropic import RateLimitError as _RateLimitError

_RATE_LIMIT_MAX_RETRIES = 3
_RATE_LIMIT_BASE_DELAY = 2  # seconds


async def _create_message(
    client: Any,
    model_id: str,
    create_kwargs: dict[str, Any],
) -> Any:
    """Call the Messages API, using the compaction beta for supported models.

    Retries up to 3 times with exponential backoff on 429 (rate limit).
    """
    msgs = create_kwargs.get("messages")
    if isinstance(msgs, list):
        _repair_tool_use_tool_result_pairs(msgs)

    for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
        try:
            if model_id in settings.ai_compaction_model_ids_set:
                return client.beta.messages.create(
                    betas=[settings.AI_COMPACTION_BETA],
                    context_management={
                        "edits": [
                            {
                                "type": "compact_20260112",
                                "trigger": {
                                    "type": "input_tokens",
                                    "value": settings.AI_COMPACTION_TRIGGER_TOKENS,
                                },
                            }
                        ],
                    },
                    **create_kwargs,
                )
            return client.messages.create(**create_kwargs)
        except _RateLimitError:
            if attempt >= _RATE_LIMIT_MAX_RETRIES:
                raise
            delay = _RATE_LIMIT_BASE_DELAY * (2 ** attempt)
            logger.warning(
                "Rate limited (429) on attempt %d/%d, retrying in %ds",
                attempt + 1, _RATE_LIMIT_MAX_RETRIES, delay,
            )
            await asyncio.sleep(delay)


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
        content[:half] + f"\n\n... ({len(content) - lim} chars trimmed) ...\n\n" + content[-half:]
    )


def _compact_old_tool_results(conversation: list[dict[str, Any]]) -> None:
    """Trim tool_result blocks in older turns so the conversation stays within budget.

    Mutates the conversation in-place. Keeps the last N messages untouched
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
# Skill lookup
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Main chat stream
# ---------------------------------------------------------------------------


async def chat_stream(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    user_message: str,
    user_message_id: uuid.UUID | None = None,
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

        yield {
            "type": "activity",
            "action": "Assembling context",
            "status": "running",
            "icon": "search",
        }

        (context, has_k8s, has_repos, sys_map_enabled, mcp_tools, conversation) = (
            await asyncio.gather(
                assemble_context(
                    db,
                    project_id=project_id,
                    session_id=session_id,
                    max_tokens=eff_int("AI_CONTEXT_ASSEMBLY_MAX_TOKENS"),
                ),
                _has_clusters(db, project_id),
                _has_repos(db, project_id),
                _feature_enabled(db, "system_map"),
                mcp_client.get_tool_definitions(db, user_id),
                _load_conversation(db, session_id, exclude_msg_id=user_message_id),
            )
        )

        map_ctx = None
        if sys_map_enabled:
            map_ctx = await system_map_service.build_system_map_context(db, project_id)

        yield {
            "type": "activity",
            "action": "Assembling context",
            "status": "done",
            "icon": "search",
        }

        has_mcp = len(mcp_tools) > 0

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

        skill_slug, skill_prompt = await _resolve_skill(db, project_id, ai_config, user_message)

        from app.services.prompts import build_system_prompt
        system_prompt = await build_system_prompt(
            db,
            project_id=project_id,
            context=context,
            map_ctx=map_ctx,
            has_repos=has_repos,
            has_k8s=has_k8s,
            has_mcp=has_mcp,
            has_tools=bool(tools),
            active_skill_slug=skill_slug,
            active_skill_prompt=skill_prompt,
        )

        conversation.append({"role": "user", "content": user_message})

        client = get_ai_client()
        wire_model = _resolve_model_for_provider(model_id)
        use_compaction = model_id in settings.ai_compaction_model_ids_set

        # Manual summarisation only for models without server-side compaction
        if not use_compaction:
            conversation = await _maybe_summarise(conversation, client, wire_model)

        yield {
            "type": "activity",
            "action": f"Calling {model_info['display_name']}",
            "status": "running",
            "icon": "terminal",
        }

        try:
            create_kwargs: dict[str, Any] = {
                "model": wire_model,
                "max_tokens": model_info["max_tokens"],
                "system": system_prompt,
                "messages": conversation,
            }
            if tools:
                create_kwargs["tools"] = tools

            response = await _create_message(client, model_id, create_kwargs)

            yield {
                "type": "activity",
                "action": f"Calling {model_info['display_name']}",
                "status": "done",
                "icon": "terminal",
            }

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
                    yield {
                        "type": "activity",
                        "action": label,
                        "status": "running",
                        "icon": "terminal",
                    }

                    # Gate write tools behind user confirmation
                    if _is_write_tool(tu["name"]):
                        conf_key = f"{session_id}:{tu['id']}"
                        conf_event = asyncio.Event()
                        _pending_confirmations[conf_key] = conf_event
                        yield {
                            "type": "tool_confirmation",
                            "tool_id": tu["id"],
                            "tool_name": tu["name"],
                            "tool_input": tu["input"],
                            "description": label,
                        }
                        try:
                            await asyncio.wait_for(conf_event.wait(), timeout=300)
                        except TimeoutError:
                            _confirmation_results[conf_key] = False
                        approved = _confirmation_results.pop(conf_key, False)
                        _pending_confirmations.pop(conf_key, None)
                        if not approved:
                            yield {
                                "type": "activity",
                                "action": f"{label} (rejected)",
                                "status": "done",
                                "icon": "terminal",
                            }
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tu["id"],
                                "content": _trim_tool_result("Action was rejected by the user."),
                            })
                            continue

                    resolved_input = await _resolve_tool_input_secrets(
                        db, user_id, tu["input"]
                    )

                    if is_artifact:
                        _task = asyncio.create_task(
                            session_artifact_tools.execute_tool(
                                tu["name"], resolved_input, project_id, session_id, db
                            )
                        )
                    elif is_repo:
                        _task = asyncio.create_task(
                            repo_tools.execute_tool(tu["name"], resolved_input, project_id, db)
                        )
                    elif is_local:
                        _task = asyncio.create_task(
                            local_tools.execute_tool(tu["name"], resolved_input, project_id, db)
                        )
                    elif is_mcp:
                        _task = asyncio.create_task(
                            mcp_client.execute_tool(tu["name"], resolved_input, db, user_id)
                        )
                    else:
                        _task = asyncio.create_task(
                            kube_tools.execute_tool(tu["name"], resolved_input, project_id, db)
                        )

                    try:
                        while True:
                            try:
                                result_str = await asyncio.wait_for(
                                    asyncio.shield(_task),
                                    timeout=eff_float("AI_TOOL_SSE_HEARTBEAT_SEC"),
                                )
                                break
                            except TimeoutError:
                                yield {
                                    "type": "activity",
                                    "action": f"{label} (still running…)",
                                    "status": "running",
                                    "icon": "terminal",
                                }
                    except Exception as tool_exc:
                        logger.exception("Tool execution failed: %s", tu["name"])
                        result_str = f"Error executing tool: {tool_exc}"

                    yield {
                        "type": "activity",
                        "action": label,
                        "status": "done",
                        "icon": "terminal",
                    }

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu["id"],
                            "content": _trim_tool_result(result_str),
                        }
                    )

                conversation.append({"role": "user", "content": tool_results})

                # Manual compaction only when the server isn't handling it
                if (
                    not use_compaction
                    and _estimate_chars(conversation) > settings.AI_MID_LOOP_COMPACT_CHARS
                ):
                    _compact_old_tool_results(conversation)
                    logger.info("Compacted conversation mid-loop (round %d)", rounds)

                yield {
                    "type": "activity",
                    "action": f"Calling {model_info['display_name']}",
                    "status": "running",
                    "icon": "terminal",
                }
                response = await _create_message(
                    client, model_id, {**create_kwargs, "messages": conversation}
                )
                yield {
                    "type": "activity",
                    "action": f"Calling {model_info['display_name']}",
                    "status": "done",
                    "icon": "terminal",
                }

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
                conversation.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": tu["id"], "content": synthetic}
                            for tu in pending_tools
                        ],
                    }
                )
                if (
                    not use_compaction
                    and _estimate_chars(conversation) > settings.AI_MID_LOOP_COMPACT_CHARS
                ):
                    _compact_old_tool_results(conversation)
                yield {
                    "type": "activity",
                    "action": f"Calling {model_info['display_name']}",
                    "status": "running",
                    "icon": "terminal",
                }
                recovery_kwargs = {**create_kwargs, "messages": conversation}
                recovery_kwargs.pop("tools", None)
                response = await _create_message(client, model_id, recovery_kwargs)
                yield {
                    "type": "activity",
                    "action": f"Calling {model_info['display_name']}",
                    "status": "done",
                    "icon": "terminal",
                }

                # Some models still return tool_use on the first tool-less call; nudge once more.
                if _extract_tool_uses(response) or not _extract_text(response).strip():
                    conversation.append(
                        {
                            "role": "user",
                            "content": (
                                "Answer in plain text only. Do not use tools. If you already started an "
                                "explanation above, finish it; otherwise briefly say what was blocked and "
                                "what the user should do next."
                            ),
                        }
                    )
                    yield {
                        "type": "activity",
                        "action": f"Calling {model_info['display_name']}",
                        "status": "running",
                        "icon": "terminal",
                    }
                    recovery_kwargs2 = {**create_kwargs, "messages": conversation}
                    recovery_kwargs2.pop("tools", None)
                    response = await _create_message(client, model_id, recovery_kwargs2)
                    yield {
                        "type": "activity",
                        "action": f"Calling {model_info['display_name']}",
                        "status": "done",
                        "icon": "terminal",
                    }

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
                logger.warning(
                    "Empty text from model — stop_reason=%s, content_types=%s, content_len=%d",
                    response.stop_reason,
                    [b.type for b in response.content],
                    len(response.content),
                )
                full_text = (
                    "The model returned no text (often after a long tool loop). "
                    "Try a follow-up message to continue, or split the task into smaller steps."
                )

            continuations = 0
            while response.stop_reason == "max_tokens" and continuations < eff_int(
                "AI_MAX_CONTINUATIONS"
            ):
                continuations += 1
                logger.info(
                    "Response truncated (max_tokens), continuing (%d/%d)",
                    continuations,
                    eff_int("AI_MAX_CONTINUATIONS"),
                )
                yield {
                    "type": "activity",
                    "action": "Continuing response",
                    "status": "running",
                    "icon": "terminal",
                }

                conversation.append({"role": "assistant", "content": full_text})
                conversation.append(
                    {"role": "user", "content": "Continue from where you left off."}
                )

                if (
                    not use_compaction
                    and _estimate_chars(conversation) > settings.AI_MID_LOOP_COMPACT_CHARS
                ):
                    _compact_old_tool_results(conversation)

                response = await _create_message(
                    client, model_id, {**create_kwargs, "messages": conversation}
                )
                continuation_text = _extract_text(response)
                full_text += continuation_text

                yield {
                    "type": "activity",
                    "action": "Continuing response",
                    "status": "done",
                    "icon": "terminal",
                }

                conversation.pop()
                conversation.pop()

            yield {
                "type": "activity",
                "action": "Generating response",
                "status": "running",
                "icon": "dot",
            }

            chunk_size = settings.AI_SSE_TEXT_CHUNK_SIZE
            for i in range(0, len(full_text), chunk_size):
                yield {"type": "text_delta", "text": full_text[i : i + chunk_size]}

            yield {
                "type": "activity",
                "action": "Generating response",
                "status": "done",
                "icon": "dot",
            }

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


# ---------------------------------------------------------------------------
# Thread conversation loading
# ---------------------------------------------------------------------------

_thread_cache_prefix = "thread_"


def _thread_cache_key(thread_id: uuid.UUID) -> uuid.UUID:
    """Return a synthetic UUID used as the conversation-cache key for a thread."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"thread:{thread_id}")


async def _load_thread_conversation(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    thread_id: uuid.UUID,
    parent_message_id: uuid.UUID,
    exclude_msg_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """Build the conversation for a branch thread.

    1. Load all main session messages up to and including ``parent_message_id``.
    2. Append all thread-specific messages after that.
    3. Use a separate cache key so thread context never pollutes the main session.

    ``exclude_msg_id`` omits a specific message (the just-committed user
    message) so callers can append it without duplication.
    """
    cache_key = _thread_cache_key(thread_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Main session messages up to (and including) the parent message
    parent_msg_q = await db.execute(select(Message).where(Message.id == parent_message_id))
    parent_msg = parent_msg_q.scalar_one_or_none()
    if parent_msg is None:
        return []

    session_msgs_q = await db.execute(
        select(Message)
        .where(
            Message.session_id == session_id,
            Message.thread_id.is_(None),
            Message.created_at <= parent_msg.created_at,
        )
        .order_by(Message.created_at.asc())
    )
    session_msgs = session_msgs_q.scalars().all()

    conversation: list[dict[str, Any]] = []
    for msg in session_msgs:
        if msg.role == MessageRole.system:
            continue
        conversation.append({"role": msg.role.value, "content": msg.content})

    # Thread-specific messages (exclude the just-committed user message)
    thread_query = select(Message).where(Message.thread_id == thread_id)
    if exclude_msg_id is not None:
        thread_query = thread_query.where(Message.id != exclude_msg_id)
    thread_msgs_q = await db.execute(thread_query.order_by(Message.created_at.asc()))
    thread_msgs = thread_msgs_q.scalars().all()
    for msg in thread_msgs:
        if msg.role == MessageRole.system:
            continue
        conversation.append({"role": msg.role.value, "content": msg.content})

    _cache_set(cache_key, conversation)
    return conversation


# ---------------------------------------------------------------------------
# Thread chat stream
# ---------------------------------------------------------------------------


async def chat_stream_thread(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    parent_message_id: uuid.UUID,
    user_message: str,
    user_message_id: uuid.UUID | None = None,
    model: str = "claude-sonnet-4-5-20250929",
    ai_config: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream an AI response within a branch thread.

    Reuses the same system prompt, tools, and context assembly as the main
    session chat. The conversation is built from main-session messages up to
    the parent message plus thread-local messages.
    """
    async with project_runtime_context(db, project_id):
        model_id = _model_to_api(model)
        model_info = AVAILABLE_MODELS.get(model_id, AVAILABLE_MODELS["claude-sonnet-4-5-20250929"])

        yield {
            "type": "activity",
            "action": "Assembling context",
            "status": "running",
            "icon": "search",
        }

        (context, has_k8s, has_repos, sys_map_enabled, mcp_tools, conversation) = (
            await asyncio.gather(
                assemble_context(
                    db,
                    project_id=project_id,
                    session_id=session_id,
                    max_tokens=eff_int("AI_CONTEXT_ASSEMBLY_MAX_TOKENS"),
                ),
                _has_clusters(db, project_id),
                _has_repos(db, project_id),
                _feature_enabled(db, "system_map"),
                mcp_client.get_tool_definitions(db, user_id),
                _load_thread_conversation(
                    db,
                    session_id=session_id,
                    thread_id=thread_id,
                    parent_message_id=parent_message_id,
                    exclude_msg_id=user_message_id,
                ),
            )
        )

        map_ctx = None
        if sys_map_enabled:
            map_ctx = await system_map_service.build_system_map_context(db, project_id)

        yield {
            "type": "activity",
            "action": "Assembling context",
            "status": "done",
            "icon": "search",
        }

        has_mcp = len(mcp_tools) > 0

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

        skill_slug, skill_prompt = await _resolve_skill(db, project_id, ai_config, user_message)

        from app.services.prompts import build_system_prompt
        system_prompt = await build_system_prompt(
            db,
            project_id=project_id,
            context=context,
            map_ctx=map_ctx,
            has_repos=has_repos,
            has_k8s=has_k8s,
            has_mcp=has_mcp,
            has_tools=bool(tools),
            active_skill_slug=skill_slug,
            active_skill_prompt=skill_prompt,
            is_thread=True,
            thread_intro=(
                "You are responding inside a **branch thread**. The user branched "
                "off from a specific message in the main chat to ask a follow-up question. "
                "Focus your answer on the user's thread question while being aware of the "
                "full conversation context up to the branch point."
            ),
        )
        conversation.append({"role": "user", "content": user_message})

        client = get_ai_client()
        wire_model = _resolve_model_for_provider(model_id)
        use_compaction = model_id in settings.ai_compaction_model_ids_set
        cache_key = _thread_cache_key(thread_id)

        if not use_compaction:
            conversation = await _maybe_summarise(conversation, client, wire_model)

        yield {
            "type": "activity",
            "action": f"Calling {model_info['display_name']}",
            "status": "running",
            "icon": "terminal",
        }

        try:
            create_kwargs: dict[str, Any] = {
                "model": wire_model,
                "max_tokens": model_info["max_tokens"],
                "system": system_prompt,
                "messages": conversation,
            }
            if tools:
                create_kwargs["tools"] = tools

            response = await _create_message(client, model_id, create_kwargs)
            yield {
                "type": "activity",
                "action": f"Calling {model_info['display_name']}",
                "status": "done",
                "icon": "terminal",
            }

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
                    yield {
                        "type": "activity",
                        "action": label,
                        "status": "running",
                        "icon": "terminal",
                    }

                    # Gate write tools behind user confirmation (threads)
                    if _is_write_tool(tu["name"]):
                        conf_key = f"{session_id}:{tu['id']}"
                        conf_event = asyncio.Event()
                        _pending_confirmations[conf_key] = conf_event
                        yield {
                            "type": "tool_confirmation",
                            "tool_id": tu["id"],
                            "tool_name": tu["name"],
                            "tool_input": tu["input"],
                            "description": label,
                        }
                        try:
                            await asyncio.wait_for(conf_event.wait(), timeout=300)
                        except TimeoutError:
                            _confirmation_results[conf_key] = False
                        approved = _confirmation_results.pop(conf_key, False)
                        _pending_confirmations.pop(conf_key, None)
                        if not approved:
                            yield {
                                "type": "activity",
                                "action": f"{label} (rejected)",
                                "status": "done",
                                "icon": "terminal",
                            }
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tu["id"],
                                "content": _trim_tool_result("Action was rejected by the user."),
                            })
                            continue

                    resolved_input = await _resolve_tool_input_secrets(
                        db, user_id, tu["input"]
                    )

                    if is_artifact:
                        _task = asyncio.create_task(
                            session_artifact_tools.execute_tool(
                                tu["name"], resolved_input, project_id, session_id, db
                            )
                        )
                    elif is_repo:
                        _task = asyncio.create_task(
                            repo_tools.execute_tool(tu["name"], resolved_input, project_id, db)
                        )
                    elif is_local:
                        _task = asyncio.create_task(
                            local_tools.execute_tool(tu["name"], resolved_input, project_id, db)
                        )
                    elif is_mcp:
                        _task = asyncio.create_task(
                            mcp_client.execute_tool(tu["name"], resolved_input, db, user_id)
                        )
                    else:
                        _task = asyncio.create_task(
                            kube_tools.execute_tool(tu["name"], resolved_input, project_id, db)
                        )

                    try:
                        while True:
                            try:
                                result_str = await asyncio.wait_for(
                                    asyncio.shield(_task),
                                    timeout=eff_float("AI_TOOL_SSE_HEARTBEAT_SEC"),
                                )
                                break
                            except TimeoutError:
                                yield {
                                    "type": "activity",
                                    "action": f"{label} (still running…)",
                                    "status": "running",
                                    "icon": "terminal",
                                }
                    except Exception as tool_exc:
                        logger.exception("Tool execution failed: %s", tu["name"])
                        result_str = f"Error executing tool: {tool_exc}"

                    yield {
                        "type": "activity",
                        "action": label,
                        "status": "done",
                        "icon": "terminal",
                    }
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu["id"],
                            "content": _trim_tool_result(result_str),
                        }
                    )

                conversation.append({"role": "user", "content": tool_results})

                if (
                    not use_compaction
                    and _estimate_chars(conversation) > settings.AI_MID_LOOP_COMPACT_CHARS
                ):
                    _compact_old_tool_results(conversation)

                yield {
                    "type": "activity",
                    "action": f"Calling {model_info['display_name']}",
                    "status": "running",
                    "icon": "terminal",
                }
                response = await _create_message(
                    client, model_id, {**create_kwargs, "messages": conversation}
                )
                yield {
                    "type": "activity",
                    "action": f"Calling {model_info['display_name']}",
                    "status": "done",
                    "icon": "terminal",
                }

            # Handle pending tool calls at limit
            pending_tools = _extract_tool_uses(response)
            preface_at_limit = _extract_text(response) if pending_tools else ""
            if pending_tools:
                serialized = _serialize_content_blocks(response.content)
                conversation.append({"role": "assistant", "content": serialized})
                synthetic = (
                    "Orbit did not run these tools: the tool-use limit for this message was reached "
                    f"({max_tool_rounds} tool rounds). Reply in plain text only (no tools)."
                )
                conversation.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": tu["id"], "content": synthetic}
                            for tu in pending_tools
                        ],
                    }
                )
                yield {
                    "type": "activity",
                    "action": f"Calling {model_info['display_name']}",
                    "status": "running",
                    "icon": "terminal",
                }
                recovery_kwargs = {**create_kwargs, "messages": conversation}
                recovery_kwargs.pop("tools", None)
                response = await _create_message(client, model_id, recovery_kwargs)
                yield {
                    "type": "activity",
                    "action": f"Calling {model_info['display_name']}",
                    "status": "done",
                    "icon": "terminal",
                }

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
                logger.warning(
                    "Empty text from model (thread) — stop_reason=%s, content_types=%s, content_len=%d",
                    response.stop_reason,
                    [b.type for b in response.content],
                    len(response.content),
                )
                full_text = "The model returned no text. Try a follow-up message."

            yield {
                "type": "activity",
                "action": "Generating response",
                "status": "running",
                "icon": "dot",
            }

            chunk_size = settings.AI_SSE_TEXT_CHUNK_SIZE
            for i in range(0, len(full_text), chunk_size):
                yield {"type": "text_delta", "text": full_text[i : i + chunk_size]}

            yield {
                "type": "activity",
                "action": "Generating response",
                "status": "done",
                "icon": "dot",
            }

            if use_compaction:
                final_serialized = _serialize_content_blocks(response.content)
                conversation.append({"role": "assistant", "content": final_serialized})
            else:
                conversation.append({"role": "assistant", "content": full_text})

            _cache_set(cache_key, conversation)

            assistant_msg = Message(
                session_id=session_id,
                thread_id=thread_id,
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
                "thread_id": str(thread_id),
            }

        except Exception as exc:
            logger.exception("Thread chat stream error")
            _repair_tool_use_tool_result_pairs(conversation)
            _cache_set(cache_key, conversation)
            yield {"type": "error", "message": str(exc)}
