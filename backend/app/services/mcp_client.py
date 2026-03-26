"""MCP client bridge -- connects to MCP servers and exposes their tools.

Manages MCP server lifecycle: start, connect, list tools, call tools, stop.
Converts MCP tool schemas to Anthropic tool-calling format so they can be
injected into Claude API calls alongside built-in tools.

Connection pooling: MCP servers are kept alive for POOL_TTL_SECONDS after their
last use so consecutive tool calls in one chat turn don't cold-start every time.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import McpSkill, SkillStatus, SkillTransport

logger = logging.getLogger(__name__)

TOOL_CALL_TIMEOUT = 120
CONNECTION_TIMEOUT = 30
POOL_TTL_SECONDS = 300


@dataclass
class McpToolDef:
    """An MCP tool definition in Anthropic format."""
    skill_id: uuid.UUID
    skill_slug: str
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": f"mcp_{self.skill_slug}__{self.name}",
            "description": f"[{self.skill_slug}] {self.description}",
            "input_schema": self.input_schema,
        }


@dataclass
class _PooledConnection:
    """A pooled MCP server connection kept alive for reuse."""
    skill_slug: str
    session: Any
    last_used: float = field(default_factory=time.monotonic)
    _cleanup: Any = None


_pool: dict[str, _PooledConnection] = {}
_pool_lock = asyncio.Lock()


def parse_mcp_tool_name(anthropic_name: str) -> tuple[str, str] | None:
    """Parse 'mcp_<slug>__<tool_name>' back to (slug, tool_name)."""
    if not anthropic_name.startswith("mcp_"):
        return None
    rest = anthropic_name[4:]
    parts = rest.split("__", 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def is_mcp_tool(name: str) -> bool:
    return name.startswith("mcp_")


async def get_enabled_skills(db: AsyncSession) -> list[McpSkill]:
    """Get all enabled and configured MCP skills."""
    result = await db.execute(
        select(McpSkill).where(
            McpSkill.enabled == True,
            McpSkill.config_values.isnot(None),
        )
    )
    return list(result.scalars().all())


async def get_tool_definitions(db: AsyncSession) -> list[dict[str, Any]]:
    """Get Anthropic-format tool definitions from all enabled MCP skills.

    Uses cached tools from the DB to avoid starting MCP servers on every chat turn.
    If no cache exists, attempts to connect and fetch tools.
    """
    skills = await get_enabled_skills(db)
    tools: list[dict[str, Any]] = []

    for skill in skills:
        if skill.cached_tools:
            for t in skill.cached_tools:
                tools.append({
                    "name": f"mcp_{skill.slug}__{t['name']}",
                    "description": f"[{skill.slug}] {t.get('description', '')}",
                    "input_schema": t.get("input_schema", t.get("inputSchema", {"type": "object", "properties": {}})),
                })
        else:
            fetched = await _fetch_and_cache_tools(skill, db)
            tools.extend(fetched)

    return tools


async def get_tool_activity_label(tool_name: str, tool_input: dict[str, Any]) -> str:
    parsed = parse_mcp_tool_name(tool_name)
    if not parsed:
        return f"Executing {tool_name}"
    slug, name = parsed
    input_summary = ""
    for key in ("jql", "query", "issue_key", "owner", "repo"):
        if key in tool_input:
            input_summary = f": {str(tool_input[key])[:60]}"
            break
    return f"[{slug}] {name}{input_summary}"


async def execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    db: AsyncSession,
) -> str:
    """Execute an MCP tool via the connection pool."""
    # Garbage-collect idle connections opportunistically
    asyncio.ensure_future(_gc_pool())

    parsed = parse_mcp_tool_name(tool_name)
    if not parsed:
        return f"Error: Cannot parse MCP tool name '{tool_name}'"

    slug, mcp_tool_name = parsed

    result = await db.execute(
        select(McpSkill).where(McpSkill.slug == slug, McpSkill.enabled == True)
    )
    skill = result.scalar_one_or_none()
    if not skill:
        return f"Error: MCP skill '{slug}' not found or not enabled"
    if not skill.config_values:
        return f"Error: MCP skill '{slug}' not configured. Please add credentials in Skills settings."

    try:
        return await _call_tool_via_mcp(skill, mcp_tool_name, tool_input)
    except asyncio.TimeoutError:
        logger.warning("MCP tool call timed out: %s/%s", slug, mcp_tool_name)
        return (
            f"Error: Tool '{mcp_tool_name}' timed out after {TOOL_CALL_TIMEOUT}s. "
            "The query may be too broad. Try adding filters like maxResults=20, "
            "a date range, or more specific search criteria."
        )
    except Exception as exc:
        logger.exception("MCP tool call failed: %s/%s", slug, mcp_tool_name)
        err_msg = str(exc)
        if "JSONRPC" in err_msg or "parse" in err_msg.lower():
            return (
                f"Error calling {slug}/{mcp_tool_name}: Connection error with the MCP server. "
                "This often happens with large result sets. Try a more specific query "
                "(e.g. add maxResults, limit to a single project, or narrow the JQL filter)."
            )
        return f"Error calling {slug}/{mcp_tool_name}: {exc}"


async def refresh_skill_tools(skill: McpSkill, db: AsyncSession) -> list[dict[str, Any]]:
    """Connect to an MCP server, list its tools, cache them, and return them."""
    return await _fetch_and_cache_tools(skill, db)


async def test_connection(skill: McpSkill) -> dict[str, Any]:
    """Test connection to an MCP server and return tool count."""
    try:
        tools = await _list_tools_from_server(skill)
        return {
            "success": True,
            "tool_count": len(tools),
            "tools": [{"name": t["name"], "description": t.get("description", "")[:100]} for t in tools[:20]],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Internal: MCP server communication with connection pooling & timeouts
# ---------------------------------------------------------------------------

_DEVNULL_TEXT = open(os.devnull, "w")


def _build_env(skill: McpSkill) -> dict[str, str]:
    """Build environment variables for the MCP server process."""
    env = dict(os.environ)
    env["NO_COLOR"] = "1"
    if skill.config_values:
        for key, value in skill.config_values.items():
            if isinstance(value, str) and value:
                env[key] = value
    return env


def _suppress_mcp_stdio_warnings():
    """Suppress noisy 'Failed to parse JSONRPC message' tracebacks."""
    logging.getLogger("mcp.client.stdio").setLevel(logging.CRITICAL)


def _extract_output(result: Any) -> str:
    """Extract text from an MCP tool result, truncating if needed."""
    parts: list[str] = []
    for block in result.content:
        if hasattr(block, "text"):
            parts.append(block.text)
        elif hasattr(block, "data"):
            parts.append(f"[binary data: {getattr(block, 'mimeType', 'unknown')}]")
        else:
            parts.append(str(block))
    output = "\n".join(parts)
    if len(output) > 50_000:
        output = output[:5000] + "\n\n...(truncated — full response was too large)...\n\n" + output[-5000:]
    return output


def _extract_tools(result: Any) -> list[dict[str, Any]]:
    """Convert MCP ListToolsResult to dicts."""
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.inputSchema if hasattr(t, "inputSchema") else {},
        }
        for t in result.tools
    ]


async def _get_pooled_session(skill: McpSkill) -> Any:
    """Get or create a pooled MCP session for this skill.

    Returns the ClientSession. Callers must NOT close it; the pool
    manages lifecycle. If the server is unreachable a fresh one is started.
    """
    _suppress_mcp_stdio_warnings()
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async with _pool_lock:
        conn = _pool.get(skill.slug)
        if conn is not None:
            try:
                # Smoke-test: list_tools is cheap and validates the connection
                await asyncio.wait_for(conn.session.list_tools(), timeout=5)
                conn.last_used = time.monotonic()
                return conn.session
            except Exception:
                logger.debug("Pooled connection for %s is stale, replacing", skill.slug)
                await _evict(skill.slug)

        # Start a new connection
        if skill.transport == SkillTransport.stdio:
            args = skill.server_args or []
            if isinstance(args, dict):
                args = args.get("args", [])

            server_params = StdioServerParameters(
                command=skill.server_command,
                args=args,
                env=_build_env(skill),
            )

            transport_cm = stdio_client(server_params, errlog=_DEVNULL_TEXT)
            streams = await transport_cm.__aenter__()
            read, write = streams

            session_obj = ClientSession(read, write)
            session = await session_obj.__aenter__()

            await asyncio.wait_for(session.initialize(), timeout=CONNECTION_TIMEOUT)

            async def cleanup():
                try:
                    await session_obj.__aexit__(None, None, None)
                except Exception:
                    pass
                try:
                    await transport_cm.__aexit__(None, None, None)
                except Exception:
                    pass

            _pool[skill.slug] = _PooledConnection(
                skill_slug=skill.slug,
                session=session,
                last_used=time.monotonic(),
                _cleanup=cleanup,
            )
            return session
        else:
            from mcp import ClientSession as CS
            from mcp.client.streamable_http import streamable_http_client

            if not skill.server_url:
                raise ValueError("HTTP transport requires server_url")

            transport_cm = streamable_http_client(skill.server_url)
            streams = await transport_cm.__aenter__()
            read, write, _ = streams

            session_obj = CS(read, write)
            session = await session_obj.__aenter__()

            await asyncio.wait_for(session.initialize(), timeout=CONNECTION_TIMEOUT)

            async def cleanup_http():
                try:
                    await session_obj.__aexit__(None, None, None)
                except Exception:
                    pass
                try:
                    await transport_cm.__aexit__(None, None, None)
                except Exception:
                    pass

            _pool[skill.slug] = _PooledConnection(
                skill_slug=skill.slug,
                session=session,
                last_used=time.monotonic(),
                _cleanup=cleanup_http,
            )
            return session


async def _evict(slug: str) -> None:
    """Remove and clean up a pooled connection (must hold _pool_lock)."""
    conn = _pool.pop(slug, None)
    if conn and conn._cleanup:
        try:
            await conn._cleanup()
        except Exception:
            pass


async def evict_all() -> None:
    """Shut down all pooled connections. Called on app shutdown."""
    async with _pool_lock:
        for slug in list(_pool):
            await _evict(slug)


async def _gc_pool() -> None:
    """Evict connections idle longer than POOL_TTL_SECONDS."""
    now = time.monotonic()
    async with _pool_lock:
        for slug in list(_pool):
            if now - _pool[slug].last_used > POOL_TTL_SECONDS:
                logger.debug("Evicting idle MCP pool entry: %s", slug)
                await _evict(slug)


async def _list_tools_from_server(skill: McpSkill) -> list[dict[str, Any]]:
    """List tools from a (pooled) MCP server."""
    session = await _get_pooled_session(skill)
    result = await asyncio.wait_for(session.list_tools(), timeout=CONNECTION_TIMEOUT)
    return _extract_tools(result)


async def _call_tool_via_mcp(
    skill: McpSkill,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    """Call a tool on a (pooled) MCP server with a timeout."""
    try:
        session = await _get_pooled_session(skill)
        result = await asyncio.wait_for(
            session.call_tool(tool_name, arguments=arguments),
            timeout=TOOL_CALL_TIMEOUT,
        )
        return _extract_output(result)
    except asyncio.TimeoutError:
        # Evict the stale connection so next call starts fresh
        async with _pool_lock:
            await _evict(skill.slug)
        return (
            f"Error: Tool call '{tool_name}' timed out after {TOOL_CALL_TIMEOUT}s. "
            "Try narrowing your query (e.g. add maxResults, date filters, or a more specific JQL)."
        )
    except Exception:
        # Connection might be broken; evict so next attempt gets a fresh one
        async with _pool_lock:
            await _evict(skill.slug)
        raise


async def _fetch_and_cache_tools(
    skill: McpSkill,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Fetch tools from MCP server and cache in the DB."""
    try:
        raw_tools = await _list_tools_from_server(skill)
        skill.cached_tools = raw_tools
        skill.status = SkillStatus.connected
        skill.status_message = f"{len(raw_tools)} tools available"
        await db.commit()

        return [
            {
                "name": f"mcp_{skill.slug}__{t['name']}",
                "description": f"[{skill.slug}] {t.get('description', '')}",
                "input_schema": t.get("input_schema", t.get("inputSchema", {"type": "object", "properties": {}})),
            }
            for t in raw_tools
        ]
    except Exception as exc:
        logger.warning("Failed to fetch tools for skill %s: %s", skill.slug, exc)
        skill.status = SkillStatus.error
        skill.status_message = str(exc)[:500]
        await db.commit()
        return []


# ---------------------------------------------------------------------------
# Builtin skill catalog templates
# ---------------------------------------------------------------------------


BUILTIN_SKILLS: list[dict[str, Any]] = [
    {
        "name": "Atlassian (Jira & Confluence)",
        "slug": "atlassian",
        "description": (
            "Full Jira and Confluence integration via MCP. Search issues, "
            "create/update tickets, transition statuses, manage sprints, "
            "read Confluence pages, and more."
        ),
        "icon": "jira",
        "transport": "stdio",
        "server_command": "uvx",
        "server_args": ["mcp-atlassian"],
        "config_schema": {
            "fields": [
                {"key": "JIRA_URL", "label": "Jira Base URL", "type": "url", "placeholder": "https://yourcompany.atlassian.net", "required": True},
                {"key": "JIRA_USERNAME", "label": "Jira Email", "type": "email", "placeholder": "you@company.com", "required": True},
                {"key": "JIRA_API_TOKEN", "label": "Jira API Token", "type": "password", "required": True, "help_url": "https://id.atlassian.com/manage-profile/security/api-tokens", "help_text": "Generate an API token"},
            ],
        },
    },
    {
        "name": "GitHub",
        "slug": "github",
        "description": (
            "Full GitHub integration via MCP. Manage issues, pull requests, "
            "branches, releases, code search, and repository operations."
        ),
        "icon": "github",
        "transport": "stdio",
        "server_command": "npx",
        "server_args": ["-y", "@modelcontextprotocol/server-github"],
        "config_schema": {
            "fields": [
                {"key": "GITHUB_PERSONAL_ACCESS_TOKEN", "label": "GitHub Personal Access Token", "type": "password", "required": True, "help_url": "https://github.com/settings/tokens", "help_text": "Generate a token"},
            ],
        },
    },
]


async def seed_builtin_skills(db: AsyncSession) -> None:
    """Insert or update builtin skill templates."""
    for template in BUILTIN_SKILLS:
        result = await db.execute(
            select(McpSkill).where(McpSkill.slug == template["slug"])
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            skill = McpSkill(
                name=template["name"],
                slug=template["slug"],
                description=template["description"],
                icon=template.get("icon"),
                transport=SkillTransport(template["transport"]),
                server_command=template["server_command"],
                server_args=template.get("server_args"),
                config_schema=template.get("config_schema"),
                is_builtin=True,
            )
            db.add(skill)
        elif existing.is_builtin:
            existing.server_command = template["server_command"]
            existing.server_args = template.get("server_args")
            existing.config_schema = template.get("config_schema")
            expected_keys = {f["key"] for f in (template.get("config_schema") or {}).get("fields", [])}
            saved_keys = set((existing.config_values or {}).keys())
            if existing.config_values and expected_keys and not expected_keys.issubset(saved_keys):
                existing.config_values = None
                existing.enabled = False
                existing.cached_tools = None
                existing.status = SkillStatus.available
                existing.status_message = "Reconfiguration required — credential fields changed"
    await db.commit()
