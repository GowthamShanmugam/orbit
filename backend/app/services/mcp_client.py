"""MCP client bridge -- connects to MCP servers and exposes their tools.

Manages MCP server lifecycle: start, connect, list tools, call tools, stop.
Converts MCP tool schemas to Anthropic tool-calling format so they can be
injected into Claude API calls alongside built-in tools.

Connection pooling: **HTTP/streamable** MCP sessions are pooled (see ``MCP_POOL_TTL_SECONDS`` in settings).
**Stdio** MCP clients are always short-lived: the official client uses an AnyIO task
group that must be torn down in the same asyncio task that created it (pooling
would exit it from GC / another task and break the app).

Plugin registry pattern (opendatahub-io/skills-registry):
  - Plugins are catalog entries containing one or more skills
  - Users independently install and configure plugins (per-user credentials)
  - Only tools from plugins a user has enabled appear in their chat sessions
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.skill import (
    PluginSkill,
    PluginSource,
    PluginType,
    SkillCategory,
    SkillPlugin,
    SkillStatus,
    SkillTransport,
    UserPluginConfig,
)
from app.services.runtime_settings import eff_int

logger = logging.getLogger(__name__)


@dataclass
class McpToolDef:
    """An MCP tool definition in Anthropic format."""

    plugin_id: uuid.UUID
    plugin_slug: str
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": f"mcp_{self.plugin_slug}__{self.name}",
            "description": f"[{self.plugin_slug}] {self.description}",
            "input_schema": self.input_schema,
        }


@dataclass
class _PooledConnection:
    """A pooled MCP server connection kept alive for reuse."""

    plugin_slug: str
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


# ---------------------------------------------------------------------------
# Per-user plugin resolution
# ---------------------------------------------------------------------------


async def get_user_configured_plugins(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[tuple[SkillPlugin, UserPluginConfig]]:
    """Get all MCP integrations the user has configured and enabled."""
    result = await db.execute(
        select(SkillPlugin, UserPluginConfig)
        .join(UserPluginConfig, UserPluginConfig.plugin_id == SkillPlugin.id)
        .where(
            UserPluginConfig.user_id == user_id,
            UserPluginConfig.enabled,
            UserPluginConfig.config_values.isnot(None),
            SkillPlugin.plugin_type.in_([PluginType.mcp, PluginType.hybrid]),
        )
    )
    return list(result.all())


# Synthetic tools injected for plugins that use MCP resources instead of tools
# for file reading (e.g. Google Drive).
_SYNTHETIC_TOOLS: dict[str, list[dict[str, Any]]] = {
    "google-drive": [
        {
            "name": "read_file",
            "description": (
                "Read the full content of a Google Drive file by its file ID. "
                "Use after 'search' to retrieve file contents. "
                "Google Docs are returned as Markdown, Sheets as CSV, "
                "Presentations as plain text."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The Google Drive file ID (from search results)",
                    }
                },
                "required": ["file_id"],
            },
        }
    ],
}


async def get_tool_definitions(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Get Anthropic-format tool definitions from all integrations the user has configured.

    Uses cached tools from the plugin to avoid starting MCP servers on every
    chat turn. If no cache exists, attempts to connect and fetch tools.
    """
    pairs = await get_user_configured_plugins(db, user_id)
    tools: list[dict[str, Any]] = []

    for plugin, user_config in pairs:
        if plugin.cached_tools:
            for t in plugin.cached_tools:
                tools.append(
                    {
                        "name": f"mcp_{plugin.slug}__{t['name']}",
                        "description": f"[{plugin.slug}] {t.get('description', '')}",
                        "input_schema": t.get(
                            "input_schema",
                            t.get("inputSchema", {"type": "object", "properties": {}}),
                        ),
                    }
                )
        else:
            fetched = await _fetch_and_cache_tools(plugin, user_config, db)
            tools.extend(fetched)

        for synth in _SYNTHETIC_TOOLS.get(plugin.slug, []):
            tools.append(
                {
                    "name": f"mcp_{plugin.slug}__{synth['name']}",
                    "description": f"[{plugin.slug}] {synth['description']}",
                    "input_schema": synth["input_schema"],
                }
            )

    return tools


async def get_all_prompt_skills(
    db: AsyncSession,
    project_id: uuid.UUID | None = None,
) -> list[PluginSkill]:
    """Get prompt-based skills available in a project.

    Returns skills from built-in packs (always available) plus skills from
    packs explicitly installed in the project. If no project_id is given,
    returns only built-in skills.
    """
    from sqlalchemy import or_

    from app.models.skill import ProjectSkillPack

    filters = [
        SkillPlugin.plugin_type.in_([PluginType.prompt, PluginType.hybrid]),
        PluginSkill.user_invocable,
    ]

    if project_id is not None:
        installed_subq = (
            select(ProjectSkillPack.skill_plugin_id)
            .where(ProjectSkillPack.project_id == project_id)
            .scalar_subquery()
        )
        filters.append(or_(SkillPlugin.is_builtin, SkillPlugin.id.in_(installed_subq)))
    else:
        filters.append(SkillPlugin.is_builtin)

    result = await db.execute(
        select(PluginSkill)
        .join(SkillPlugin, PluginSkill.plugin_id == SkillPlugin.id)
        .where(*filters)
        .order_by(PluginSkill.sort_order.asc())
    )
    return list(result.scalars().all())


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
    user_id: uuid.UUID,
) -> str:
    """Execute an MCP tool using the calling user's credentials."""
    asyncio.ensure_future(_gc_pool())

    parsed = parse_mcp_tool_name(tool_name)
    if not parsed:
        return f"Error: Cannot parse MCP tool name '{tool_name}'"

    slug, mcp_tool_name = parsed

    result = await db.execute(
        select(SkillPlugin, UserPluginConfig)
        .join(UserPluginConfig, UserPluginConfig.plugin_id == SkillPlugin.id)
        .where(
            SkillPlugin.slug == slug,
            UserPluginConfig.user_id == user_id,
            UserPluginConfig.enabled,
        )
    )
    row = result.first()
    if not row:
        return f"Error: MCP plugin '{slug}' not found or not enabled for your account"

    plugin, user_config = row
    if not user_config.config_values:
        return f"Error: MCP plugin '{slug}' not configured. Please add your credentials in Skills settings."

    # Handle synthetic resource-based tools (e.g. Google Drive read_file)
    if slug in _SYNTHETIC_TOOLS and mcp_tool_name in {s["name"] for s in _SYNTHETIC_TOOLS[slug]}:
        try:
            return await _call_synthetic_tool(plugin, user_config, mcp_tool_name, tool_input)
        except Exception as exc:
            logger.exception("Synthetic tool call failed: %s/%s", slug, mcp_tool_name)
            return f"Error calling {slug}/{mcp_tool_name}: {exc}"

    try:
        return await _call_tool_via_mcp(plugin, user_config, mcp_tool_name, tool_input)
    except TimeoutError:
        logger.warning("MCP tool call timed out: %s/%s", slug, mcp_tool_name)
        return (
            f"Error: Tool '{mcp_tool_name}' timed out after {eff_int('MCP_TOOL_CALL_TIMEOUT_SEC')}s. "
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


async def refresh_plugin_tools(
    plugin: SkillPlugin,
    user_config: UserPluginConfig,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Connect to an MCP server, list its tools, cache them, and return them."""
    return await _fetch_and_cache_tools(plugin, user_config, db)


_PROBE_TOOLS: dict[str, list[tuple[str, dict[str, Any]]]] = {
    "atlassian": [
        ("jira_search", {"jql": "project IS NOT EMPTY", "limit": 1}),
        ("jira_get_all_projects", {}),
    ],
    "github": [
        ("search_repositories", {"query": "test", "perPage": 1}),
        ("list_issues", {"owner": "octocat", "repo": "hello-world", "perPage": 1}),
    ],
}


async def _probe_credential(
    plugin: SkillPlugin,
    user_config: UserPluginConfig,
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[bool, str]:
    """Call a real tool to verify credentials actually work.

    Returns (success, message). Checks the MCP isError flag AND scans
    the output text for common error patterns.
    """
    try:
        if plugin.transport == SkillTransport.stdio:
            async with _stdio_mcp_session(plugin, user_config) as session:
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments=arguments),
                    timeout=eff_int("MCP_CONNECTION_TIMEOUT_SEC"),
                )
        else:
            session = await _get_pooled_http_session(plugin, user_config)
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments=arguments),
                timeout=eff_int("MCP_CONNECTION_TIMEOUT_SEC"),
            )
    except Exception as exc:
        return False, str(exc)

    is_error = getattr(result, "isError", False)
    text = _extract_output(result)
    lower = text.lower()

    if is_error:
        return False, text[:300]

    error_patterns = (
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "authentication failed",
        "invalid credentials",
        "bad credentials",
        "access denied",
        "unauthenticated",
        "enotfound",
        "getaddrinfo",
        "econnrefused",
        "connect etimedout",
        "request failed",
        "invalid url",
        "not found",
    )
    if any(pat in lower for pat in error_patterns):
        return False, text[:300]

    return True, text[:200]


async def test_connection(
    plugin: SkillPlugin,
    user_config: UserPluginConfig,
) -> dict[str, Any]:
    """Test connection: start MCP server, list tools, then call a probe tool
    to verify the credentials actually work against the remote service."""
    try:
        tools = await _list_tools_from_server(plugin, user_config)
    except Exception as exc:
        return {"success": False, "error": f"MCP server failed to start: {exc}"}

    if not tools:
        return {"success": False, "error": "MCP server returned no tools"}

    tool_names = {t["name"] for t in tools}

    probe_candidates = _PROBE_TOOLS.get(plugin.slug, [])
    probed = False
    for probe_name, probe_args in probe_candidates:
        if probe_name in tool_names:
            ok, message = await _probe_credential(
                plugin,
                user_config,
                probe_name,
                probe_args,
            )
            if not ok:
                short = message.split("\n")[0][:200]
                return {
                    "success": False,
                    "error": f"Connection failed -- check your credentials: {short}",
                }
            probed = True
            break

    if probe_candidates and not probed:
        return {
            "success": False,
            "error": (
                "Could not verify credentials: none of the expected probe tools "
                f"({', '.join(n for n, _ in probe_candidates)}) were found on the server."
            ),
        }

    return {
        "success": True,
        "tool_count": len(tools),
        "tools": [
            {"name": t["name"], "description": t.get("description", "")[:100]} for t in tools[:20]
        ],
    }


# ---------------------------------------------------------------------------
# Internal: MCP server communication with connection pooling & timeouts
# ---------------------------------------------------------------------------

_DEVNULL_TEXT = open(os.devnull, "w")  # noqa: SIM115


def _build_env(plugin: SkillPlugin, user_config: UserPluginConfig) -> dict[str, str]:
    """Build environment variables for the MCP server process using the user's credentials."""
    env = dict(os.environ)
    env["NO_COLOR"] = "1"
    if user_config.config_values:
        for key, value in user_config.config_values.items():
            if key.startswith("oauth_") or key.startswith("_"):
                continue
            if isinstance(value, str) and value:
                env[key] = value
    return env


def _write_gdrive_temp_files(user_config: UserPluginConfig) -> tuple[str, str] | None:
    """Decrypt stored Google OAuth credentials and write them to temp files.

    Returns (oauth_keys_path, credentials_path) or None if not configured.
    The caller is responsible for cleaning up the temp directory.
    """
    from app.core.secret_vault import decrypt_value

    cfg = user_config.config_values or {}
    encrypted_client = cfg.get("oauth_client_config")
    encrypted_creds = cfg.get("oauth_credentials")
    if not encrypted_client or not encrypted_creds:
        return None

    try:
        client_info = json.loads(decrypt_value(encrypted_client))
        token_info = json.loads(decrypt_value(encrypted_creds))
    except Exception:
        logger.warning("Failed to decrypt Google Drive credentials")
        return None

    tmp_dir = tempfile.mkdtemp(prefix="orbit_gdrive_")

    oauth_keys = {
        "installed": {
            "client_id": client_info["client_id"],
            "client_secret": client_info["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    keys_path = os.path.join(tmp_dir, "gcp-oauth.keys.json")
    with open(keys_path, "w") as f:
        json.dump(oauth_keys, f)

    creds_path = os.path.join(tmp_dir, ".gdrive-server-credentials.json")
    with open(creds_path, "w") as f:
        json.dump(token_info, f)

    return keys_path, creds_path


def _build_gdrive_env(
    plugin: SkillPlugin,
    user_config: UserPluginConfig,
) -> tuple[dict[str, str], str | None]:
    """Build env for Google Drive MCP, writing temp credential files.

    Returns (env_dict, temp_dir_to_cleanup).
    """
    env = _build_env(plugin, user_config)
    paths = _write_gdrive_temp_files(user_config)
    if paths:
        env["GDRIVE_OAUTH_PATH"] = paths[0]
        env["GDRIVE_CREDENTIALS_PATH"] = paths[1]
        return env, os.path.dirname(paths[0])
    return env, None


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
    if len(output) > 15_000:
        output = (
            output[:7000]
            + "\n\n...(truncated — full response was too large)...\n\n"
            + output[-3000:]
        )
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


@asynccontextmanager
async def _stdio_mcp_session(plugin: SkillPlugin, user_config: UserPluginConfig):
    """Run one MCP stdio client in a single task (required by anyio/mcp stdio_client).

    Do **not** pool stdio transports: entering ``stdio_client`` and exiting it from
    different tasks triggers
    ``RuntimeError: Attempted to exit cancel scope in a different task``.
    """
    import shutil

    _suppress_mcp_stdio_warnings()
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    args = plugin.server_args or []
    if isinstance(args, dict):
        args = args.get("args", [])

    tmp_dir: str | None = None
    if plugin.slug == "google-drive":
        env, tmp_dir = _build_gdrive_env(plugin, user_config)
    else:
        env = _build_env(plugin, user_config)

    server_params = StdioServerParameters(
        command=plugin.server_command,
        args=args,
        env=env,
    )

    try:
        async with stdio_client(server_params, errlog=_DEVNULL_TEXT) as streams:
            read, write = streams
            session_obj = ClientSession(read, write)
            await session_obj.__aenter__()
            try:
                await asyncio.wait_for(
                    session_obj.initialize(), timeout=eff_int("MCP_CONNECTION_TIMEOUT_SEC")
                )
                yield session_obj
            finally:
                try:
                    await session_obj.__aexit__(None, None, None)
                except Exception:
                    logger.debug("MCP ClientSession __aexit__ for %s", plugin.slug, exc_info=True)
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


async def _get_pooled_http_session(plugin: SkillPlugin, user_config: UserPluginConfig) -> Any:
    """Pool **HTTP/streamable** MCP sessions only (stdio uses `_stdio_mcp_session`)."""
    from mcp import ClientSession as CS
    from mcp.client.streamable_http import streamable_http_client

    if plugin.transport == SkillTransport.stdio:
        raise ValueError("_get_pooled_http_session does not support stdio")
    if not plugin.server_url:
        raise ValueError("HTTP transport requires server_url")

    pool_key = f"{plugin.slug}:{user_config.user_id}"

    async with _pool_lock:
        conn = _pool.get(pool_key)
        if conn is not None:
            try:
                await asyncio.wait_for(
                    conn.session.list_tools(),
                    timeout=settings.MCP_LIST_TOOLS_TIMEOUT_SEC,
                )
                conn.last_used = time.monotonic()
                return conn.session
            except Exception:
                logger.debug("Pooled HTTP connection for %s is stale, replacing", pool_key)
                await _evict(pool_key)

        transport_cm = streamable_http_client(plugin.server_url)
        streams = await transport_cm.__aenter__()
        read, write, _ = streams

        session_obj = CS(read, write)
        session = await session_obj.__aenter__()

        await asyncio.wait_for(session.initialize(), timeout=eff_int("MCP_CONNECTION_TIMEOUT_SEC"))

        async def cleanup_http():
            with suppress(Exception):
                await session_obj.__aexit__(None, None, None)
            with suppress(Exception):
                await transport_cm.__aexit__(None, None, None)

        _pool[pool_key] = _PooledConnection(
            plugin_slug=plugin.slug,
            session=session,
            last_used=time.monotonic(),
            _cleanup=cleanup_http,
        )
        return session


async def _evict(key: str) -> None:
    """Remove and clean up a pooled connection (must hold _pool_lock)."""
    conn = _pool.pop(key, None)
    if conn and conn._cleanup:
        with suppress(Exception):
            await conn._cleanup()


async def evict_all() -> None:
    """Shut down all pooled connections. Called on app shutdown."""
    async with _pool_lock:
        for key in list(_pool):
            await _evict(key)


async def _gc_pool() -> None:
    """Evict connections idle longer than the configured pool TTL."""
    now = time.monotonic()
    async with _pool_lock:
        for key in list(_pool):
            if now - _pool[key].last_used > settings.MCP_POOL_TTL_SECONDS:
                logger.debug("Evicting idle MCP pool entry: %s", key)
                await _evict(key)


async def _list_tools_from_server(
    plugin: SkillPlugin,
    user_config: UserPluginConfig,
) -> list[dict[str, Any]]:
    """List tools from an MCP server (stdio: ephemeral session; HTTP: pool)."""
    if plugin.transport == SkillTransport.stdio:
        async with _stdio_mcp_session(plugin, user_config) as session:
            result = await asyncio.wait_for(
                session.list_tools(), timeout=eff_int("MCP_CONNECTION_TIMEOUT_SEC")
            )
            return _extract_tools(result)
    session = await _get_pooled_http_session(plugin, user_config)
    result = await asyncio.wait_for(
        session.list_tools(), timeout=eff_int("MCP_CONNECTION_TIMEOUT_SEC")
    )
    return _extract_tools(result)


async def _call_tool_via_mcp(
    plugin: SkillPlugin,
    user_config: UserPluginConfig,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    """Call a tool on an MCP server with a timeout (stdio: ephemeral; HTTP: pool)."""
    pool_key = f"{plugin.slug}:{user_config.user_id}"
    try:
        if plugin.transport == SkillTransport.stdio:
            async with _stdio_mcp_session(plugin, user_config) as session:
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments=arguments),
                    timeout=eff_int("MCP_TOOL_CALL_TIMEOUT_SEC"),
                )
                return _extract_output(result)
        session = await _get_pooled_http_session(plugin, user_config)
        result = await asyncio.wait_for(
            session.call_tool(tool_name, arguments=arguments),
            timeout=eff_int("MCP_TOOL_CALL_TIMEOUT_SEC"),
        )
        return _extract_output(result)
    except TimeoutError:
        if plugin.transport != SkillTransport.stdio:
            async with _pool_lock:
                await _evict(pool_key)
        return (
            f"Error: Tool call '{tool_name}' timed out after {eff_int('MCP_TOOL_CALL_TIMEOUT_SEC')}s. "
            "Try narrowing your query (e.g. add maxResults, date filters, or a more specific JQL)."
        )
    except Exception:
        if plugin.transport != SkillTransport.stdio:
            async with _pool_lock:
                await _evict(pool_key)
        raise


_GDRIVE_EXPORT_MIMES: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": ("text/markdown", "Google Doc"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", "Google Sheet"),
    "application/vnd.google-apps.presentation": ("text/plain", "Google Slides"),
}


async def _read_gdrive_file(user_config: UserPluginConfig, file_id: str) -> str:
    """Read a Google Drive file using the REST API with the stored OAuth tokens."""
    import httpx

    from app.core.secret_vault import decrypt_value

    cfg = user_config.config_values or {}
    encrypted_creds = cfg.get("oauth_credentials")
    encrypted_client = cfg.get("oauth_client_config")
    if not encrypted_creds:
        return "Error: Google Drive not configured. Please set up OAuth in Integrations."

    try:
        token_info = json.loads(decrypt_value(encrypted_creds))
    except Exception:
        return "Error: Failed to decrypt Google Drive credentials."

    access_token = token_info.get("access_token", "")
    if not access_token:
        return "Error: No access token found. Please re-authenticate Google Drive."

    headers = {"Authorization": f"Bearer {access_token}"}
    timeout = eff_int("MCP_TOOL_CALL_TIMEOUT_SEC")

    async with httpx.AsyncClient(timeout=timeout) as http:
        # Get file metadata to determine type
        meta_resp = await http.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={"fields": "id,name,mimeType"},
            headers=headers,
        )

        if meta_resp.status_code == 401 and encrypted_client:
            access_token = await _refresh_gdrive_token(user_config, token_info, encrypted_client)
            if not access_token:
                return "Error: Google Drive token expired. Please re-authenticate in Integrations."
            headers = {"Authorization": f"Bearer {access_token}"}
            meta_resp = await http.get(
                f"https://www.googleapis.com/drive/v3/files/{file_id}",
                params={"fields": "id,name,mimeType"},
                headers=headers,
            )

        if meta_resp.status_code != 200:
            return f"Error reading file: {meta_resp.status_code} — {meta_resp.text[:500]}"

        meta = meta_resp.json()
        mime = meta.get("mimeType", "")
        name = meta.get("name", file_id)

        if mime in _GDRIVE_EXPORT_MIMES:
            export_mime, kind = _GDRIVE_EXPORT_MIMES[mime]
            resp = await http.get(
                f"https://www.googleapis.com/drive/v3/files/{file_id}/export",
                params={"mimeType": export_mime},
                headers=headers,
            )
        else:
            resp = await http.get(
                f"https://www.googleapis.com/drive/v3/files/{file_id}",
                params={"alt": "media"},
                headers=headers,
            )

        if resp.status_code != 200:
            return f"Error downloading '{name}': {resp.status_code} — {resp.text[:500]}"

        output = resp.text
        if len(output) > 12_000:
            output = (
                output[:6000]
                + f"\n\n...(truncated — '{name}' was too large)...\n\n"
                + output[-3000:]
            )
        return f"# {name}\n\n{output}"


async def _refresh_gdrive_token(
    user_config: UserPluginConfig,
    token_info: dict[str, Any],
    encrypted_client: str,
) -> str | None:
    """Refresh the Google Drive access token using the refresh token."""
    import httpx

    from app.core.secret_vault import decrypt_value, encrypt_value

    refresh_token = token_info.get("refresh_token")
    if not refresh_token:
        return None
    try:
        client_info = json.loads(decrypt_value(encrypted_client))
    except Exception:
        return None

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_info["client_id"],
                "client_secret": client_info["client_secret"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if resp.status_code != 200:
        return None

    new_tokens = resp.json()
    token_info["access_token"] = new_tokens["access_token"]
    if "refresh_token" in new_tokens:
        token_info["refresh_token"] = new_tokens["refresh_token"]

    # Persist the refreshed tokens
    user_config.config_values = {
        **(user_config.config_values or {}),
        "oauth_credentials": encrypt_value(json.dumps(token_info)),
    }
    return new_tokens["access_token"]


async def _call_synthetic_tool(
    plugin: SkillPlugin,
    user_config: UserPluginConfig,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    """Handle synthetic tools that bridge to direct API calls."""
    if plugin.slug == "google-drive" and tool_name == "read_file":
        file_id = arguments.get("file_id", "").strip()
        if not file_id:
            return "Error: file_id is required. Use 'search' first to find the file ID."
        return await _read_gdrive_file(user_config, file_id)

    return f"Error: Unknown synthetic tool '{tool_name}' for plugin '{plugin.slug}'"


async def _fetch_and_cache_tools(
    plugin: SkillPlugin,
    user_config: UserPluginConfig,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Fetch tools from MCP server and cache in the DB."""
    try:
        raw_tools = await _list_tools_from_server(plugin, user_config)
        plugin.cached_tools = raw_tools
        user_config.status = SkillStatus.connected
        user_config.status_message = f"{len(raw_tools)} tools available"
        await db.commit()

        return [
            {
                "name": f"mcp_{plugin.slug}__{t['name']}",
                "description": f"[{plugin.slug}] {t.get('description', '')}",
                "input_schema": t.get(
                    "input_schema", t.get("inputSchema", {"type": "object", "properties": {}})
                ),
            }
            for t in raw_tools
        ]
    except Exception as exc:
        logger.warning("Failed to fetch tools for plugin %s: %s", plugin.slug, exc)
        user_config.status = SkillStatus.error
        user_config.status_message = str(exc)[:500]
        await db.commit()
        return []


# ---------------------------------------------------------------------------
# Builtin plugin catalog (MCP + prompt packs)
# ---------------------------------------------------------------------------

BUILTIN_CATEGORIES: list[dict[str, Any]] = [
    {
        "name": "Integrations",
        "slug": "integrations",
        "description": "Connect to external services and APIs",
        "sort_order": 0,
    },
    {
        "name": "Development",
        "slug": "development",
        "description": "Code analysis, bug fixing, and development skills",
        "sort_order": 10,
    },
    {
        "name": "Planning",
        "slug": "planning",
        "description": "Requirements, specs, and product strategy",
        "sort_order": 20,
    },
    {
        "name": "Security",
        "slug": "security",
        "description": "Security analysis, CVE remediation, and compliance",
        "sort_order": 30,
    },
    {
        "name": "Documentation",
        "slug": "documentation",
        "description": "Documentation generation and maintenance",
        "sort_order": 40,
    },
]

BUILTIN_PLUGINS: list[dict[str, Any]] = [
    # -- MCP tool packs --
    {
        "name": "Atlassian (Jira & Confluence)",
        "slug": "atlassian",
        "description": (
            "Full Jira and Confluence integration via MCP. Search issues, "
            "create/update tickets, transition statuses, manage sprints, "
            "read Confluence pages, and more."
        ),
        "icon": "jira",
        "plugin_type": "mcp",
        "category_slug": "integrations",
        "tags": ["jira", "confluence", "project-management"],
        "transport": "stdio",
        "server_command": "uvx",
        "server_args": ["mcp-atlassian"],
        "config_schema": {
            "fields": [
                {
                    "key": "JIRA_URL",
                    "label": "Jira Base URL",
                    "type": "url",
                    "placeholder": "https://yourcompany.atlassian.net",
                    "required": True,
                },
                {
                    "key": "JIRA_USERNAME",
                    "label": "Jira Email",
                    "type": "email",
                    "placeholder": "you@company.com",
                    "required": True,
                },
                {
                    "key": "JIRA_API_TOKEN",
                    "label": "Jira API Token",
                    "type": "password",
                    "required": True,
                    "help_url": "https://id.atlassian.com/manage-profile/security/api-tokens",
                    "help_text": "Generate an API token",
                },
            ],
        },
        "sort_order": 10,
        "skills": [],
    },
    {
        "name": "GitHub",
        "slug": "github",
        "description": (
            "Full GitHub integration via MCP. Manage issues, pull requests, "
            "branches, releases, code search, and repository operations."
        ),
        "icon": "github",
        "plugin_type": "mcp",
        "category_slug": "integrations",
        "tags": ["github", "git", "code-review", "issues"],
        "transport": "stdio",
        "server_command": "npx",
        "server_args": ["-y", "@modelcontextprotocol/server-github"],
        "config_schema": {
            "fields": [
                {
                    "key": "GITHUB_PERSONAL_ACCESS_TOKEN",
                    "label": "GitHub Personal Access Token",
                    "type": "password",
                    "required": True,
                    "help_url": "https://github.com/settings/tokens",
                    "help_text": "Generate a token",
                },
            ],
        },
        "sort_order": 20,
        "skills": [],
    },
    {
        "name": "Google Drive",
        "slug": "google-drive",
        "description": (
            "Search and read files from Google Drive via MCP. "
            "Automatically converts Google Docs to Markdown, Sheets to CSV, "
            "Presentations to plain text, and Drawings to PNG."
        ),
        "icon": "google-drive",
        "plugin_type": "mcp",
        "category_slug": "integrations",
        "tags": ["google", "drive", "docs", "sheets", "files"],
        "transport": "stdio",
        "server_command": "npx",
        "server_args": ["-y", "@modelcontextprotocol/server-gdrive"],
        "config_schema": {
            "config_type": "oauth",
            "oauth_provider": "google-drive",
            "fields": [],
        },
        "sort_order": 30,
        "skills": [],
    },
    # -- Prompt skill packs --
    {
        "name": "Fix a Bug",
        "slug": "fix-a-bug",
        "description": (
            "Systematic skill for analyzing, fixing, and verifying software bugs "
            "with comprehensive testing and documentation."
        ),
        "icon": "Bug",
        "plugin_type": "prompt",
        "category_slug": "development",
        "tags": ["bug", "debugging", "testing"],
        "sort_order": 100,
        "skills": [
            {
                "name": "Understand the bug",
                "slug": "fix.understand",
                "description": "Clarify the bug report, identify expected vs actual behavior",
                "user_invocable": True,
                "system_prompt": (
                    "You are now in **fix.understand** mode. Focus on:\n"
                    "- Ask clarifying questions if the bug report is vague\n"
                    "- Identify the expected vs actual behavior\n"
                    "- Determine severity and impact\n"
                    "- List what information is still missing"
                ),
            },
            {
                "name": "Reproduce the bug",
                "slug": "fix.reproduce",
                "description": "Locate relevant code and reproduce the bug conditions",
                "user_invocable": True,
                "system_prompt": (
                    "You are now in **fix.reproduce** mode. Focus on:\n"
                    "- Use repo tools to locate the relevant code\n"
                    "- Read logs and understand the triggering conditions\n"
                    "- Identify the exact steps to reproduce\n"
                    "- Confirm the bug is reproducible"
                ),
            },
            {
                "name": "Diagnose root cause",
                "slug": "fix.diagnose",
                "description": "Trace the code path and identify the exact cause of the failure",
                "user_invocable": True,
                "system_prompt": (
                    "You are now in **fix.diagnose** mode. Focus on:\n"
                    "- Trace the code path from input to failure\n"
                    "- Identify the exact location and reason for the failure\n"
                    "- Explain the root cause clearly\n"
                    "- Rule out other potential causes"
                ),
            },
            {
                "name": "Implement the fix",
                "slug": "fix.implement",
                "description": "Propose a minimal, targeted code fix",
                "user_invocable": True,
                "system_prompt": (
                    "You are now in **fix.implement** mode. Focus on:\n"
                    "- Propose a minimal, targeted fix\n"
                    "- Show the exact code changes needed\n"
                    "- Avoid unrelated refactoring\n"
                    "- Explain why this fix addresses the root cause"
                ),
            },
            {
                "name": "Write tests",
                "slug": "fix.test",
                "description": "Write test cases covering the bug scenario and preventing regression",
                "user_invocable": True,
                "system_prompt": (
                    "You are now in **fix.test** mode. Focus on:\n"
                    "- Write test cases that cover the bug scenario\n"
                    "- Add regression tests to prevent recurrence\n"
                    "- Consider edge cases related to the fix\n"
                    "- Follow existing test patterns in the codebase"
                ),
            },
            {
                "name": "Document the fix",
                "slug": "fix.document",
                "description": "Summarize what was wrong, what changed, and why",
                "user_invocable": True,
                "system_prompt": (
                    "You are now in **fix.document** mode. Focus on:\n"
                    "- Summarize what was wrong\n"
                    "- Describe what was changed and why\n"
                    "- Write a clear commit message\n"
                    "- Update any relevant documentation"
                ),
            },
            {
                "name": "Full bug fix pipeline",
                "slug": "fix.all",
                "description": "Run the complete bug fix pipeline end-to-end",
                "user_invocable": True,
                "system_prompt": (
                    "You are in **Fix a Bug** mode. Follow this structured approach:\n\n"
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
        ],
    },
    {
        "name": "Triage Backlog",
        "slug": "triage-backlog",
        "description": (
            "Systematic skill for triaging repository issues with actionable "
            "recommendations and bulk operations support."
        ),
        "icon": "ClipboardList",
        "plugin_type": "prompt",
        "category_slug": "planning",
        "tags": ["triage", "backlog", "issues", "prioritization"],
        "sort_order": 110,
        "skills": [
            {
                "name": "Triage issues",
                "slug": "triage.run",
                "description": "Fetch and triage issues with priority, effort, and recommendations",
                "user_invocable": True,
                "system_prompt": (
                    "You are in **Triage Backlog** mode. Your goal is to systematically "
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
        ],
    },
    {
        "name": "CVE Fixer",
        "slug": "cve-fixer",
        "description": (
            "Automate remediation of CVE issues by creating pull requests "
            "with dependency updates and patches."
        ),
        "icon": "ShieldAlert",
        "plugin_type": "prompt",
        "category_slug": "security",
        "tags": ["cve", "security", "dependencies", "vulnerabilities"],
        "sort_order": 120,
        "skills": [
            {
                "name": "Assess CVE impact",
                "slug": "cve.assess",
                "description": "Identify the CVE, find the affected package, and assess exploitability",
                "user_invocable": True,
                "system_prompt": (
                    "You are in **cve.assess** mode. Focus on:\n"
                    "- Get the CVE ID, affected package, and severity\n"
                    "- Use repo tools to find where the vulnerable dependency is used\n"
                    "- Determine if the vulnerable code path is actually reachable\n"
                    "- State the CVSS score if available"
                ),
            },
            {
                "name": "Fix CVE",
                "slug": "cve.fix",
                "description": "Find the patched version and propose dependency update changes",
                "user_invocable": True,
                "system_prompt": (
                    "You are in **cve.fix** mode. Focus on:\n"
                    "- Identify the patched version of the dependency\n"
                    "- Check for breaking changes between versions\n"
                    "- Show the exact dependency file changes needed\n"
                    "- Note any code changes needed for breaking API changes\n"
                    "- Suggest commands to run tests and validate"
                ),
            },
            {
                "name": "Full CVE pipeline",
                "slug": "cve.all",
                "description": "Run the complete CVE remediation pipeline end-to-end",
                "user_invocable": True,
                "system_prompt": (
                    "You are in **CVE Fixer** mode. Your goal is to remediate "
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
        ],
    },
    {
        "name": "CLAUDE.md Generator",
        "slug": "claude-md-generator",
        "description": "Create a concise, high-signal CLAUDE.md file for AI agent onboarding.",
        "icon": "FileText",
        "plugin_type": "prompt",
        "category_slug": "documentation",
        "tags": ["documentation", "onboarding", "claude"],
        "sort_order": 130,
        "skills": [
            {
                "name": "Generate CLAUDE.md",
                "slug": "claudemd.generate",
                "description": "Analyze the repo and generate a concise CLAUDE.md file",
                "user_invocable": True,
                "system_prompt": (
                    "You are in **CLAUDE.md Generator** mode. Your goal is to create "
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
        ],
    },
    {
        "name": "Create PRDs and RFEs",
        "slug": "create-prds-rfes",
        "description": (
            "Create comprehensive Product Requirements Documents (PRDs) and break "
            "them down into Request for Enhancement (RFE) tasks."
        ),
        "icon": "FileStack",
        "plugin_type": "prompt",
        "category_slug": "planning",
        "tags": ["prd", "rfe", "requirements", "product"],
        "sort_order": 140,
        "skills": [
            {
                "name": "Create PRD",
                "slug": "prd.create",
                "description": "Create a comprehensive Product Requirements Document",
                "user_invocable": True,
                "system_prompt": (
                    "You are in **prd.create** mode. Create a comprehensive PRD:\n\n"
                    "1. **Overview** -- Problem statement, goals, and success metrics\n"
                    "2. **User Stories** -- As a [role], I want [capability], so that [benefit]\n"
                    "3. **Requirements** -- Functional and non-functional, prioritized (Must/Should/Could)\n"
                    "4. **Technical Considerations** -- Architecture impact, dependencies, risks\n"
                    "5. **Out of Scope** -- Explicitly state what is NOT included\n\n"
                    "Use repo tools to ground technical decisions in the actual codebase."
                ),
            },
            {
                "name": "Break into RFEs",
                "slug": "rfe.create",
                "description": "Break a PRD into independently implementable RFE tasks",
                "user_invocable": True,
                "system_prompt": (
                    "You are in **rfe.create** mode. Break the PRD into RFE tasks:\n\n"
                    "- Each RFE should be independently implementable\n"
                    "- Include: title, description, acceptance criteria, estimated effort (S/M/L/XL)\n"
                    "- Order by dependency (what must be done first)\n"
                    "- Use MCP tools to create Jira tickets or GitHub issues if the user requests it"
                ),
            },
            {
                "name": "Full PRD and RFE pipeline",
                "slug": "prd.all",
                "description": "Run the full PRD creation and RFE breakdown pipeline",
                "user_invocable": True,
                "system_prompt": (
                    "You are in **Create PRDs and RFEs** mode. Your goal is to help "
                    "create comprehensive Product Requirements Documents and break them into actionable tasks.\n\n"
                    "**PRD Structure:**\n"
                    "1. **Overview** -- Problem statement, goals, and success metrics\n"
                    "2. **User Stories** -- As a [role], I want [capability], so that [benefit]\n"
                    "3. **Requirements** -- Functional and non-functional, prioritized (Must/Should/Could)\n"
                    "4. **Technical Considerations** -- Architecture impact, dependencies, risks\n"
                    "5. **Out of Scope** -- Explicitly state what is NOT included\n\n"
                    "**RFE Breakdown:**\n"
                    "After the PRD, break it into RFE tasks:\n"
                    "- Each RFE should be independently implementable\n"
                    "- Include: title, description, acceptance criteria, estimated effort (S/M/L/XL)\n"
                    "- Order by dependency (what must be done first)\n"
                    "- Use MCP tools to create Jira tickets or GitHub issues if the user requests it\n\n"
                    "Use repo tools to ground technical decisions in the actual codebase."
                ),
            },
        ],
    },
    {
        "name": "Spec-Kit",
        "slug": "spec-kit",
        "description": "Spec-driven development skill for feature planning, task breakdown, and implementation.",
        "icon": "LayoutList",
        "plugin_type": "prompt",
        "category_slug": "development",
        "tags": ["spec", "planning", "implementation", "tasks"],
        "sort_order": 150,
        "skills": [
            {
                "name": "Write specification",
                "slug": "spec.write",
                "description": "Collaborate on a clear feature specification",
                "user_invocable": True,
                "system_prompt": (
                    "You are in **spec.write** mode. Focus on:\n"
                    "- Collaborate with the user to define a clear feature specification\n"
                    "- Document: purpose, scope, technical approach, API contracts, data models\n"
                    "- Identify edge cases and error handling requirements"
                ),
            },
            {
                "name": "Break into tasks",
                "slug": "spec.tasks",
                "description": "Decompose the spec into ordered implementation tasks",
                "user_invocable": True,
                "system_prompt": (
                    "You are in **spec.tasks** mode. Focus on:\n"
                    "- Decompose the spec into ordered implementation tasks\n"
                    "- Each task: title, description, files to change, estimated complexity\n"
                    "- Identify dependencies between tasks\n"
                    "- Present as a numbered checklist"
                ),
            },
            {
                "name": "Implementation guide",
                "slug": "spec.implement",
                "description": "Provide specific implementation details for each task",
                "user_invocable": True,
                "system_prompt": (
                    "You are in **spec.implement** mode. Focus on:\n"
                    "- For each task, provide specific implementation details\n"
                    "- Reference existing code patterns in the repo using repo tools\n"
                    "- Show code snippets for key changes\n"
                    "- Track progress through the checklist\n\n"
                    "Always start by understanding the existing codebase before proposing changes."
                ),
            },
            {
                "name": "Full spec-kit pipeline",
                "slug": "spec.all",
                "description": "Run the full spec-driven development pipeline",
                "user_invocable": True,
                "system_prompt": (
                    "You are in **Spec-Kit** mode for spec-driven development.\n\n"
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
        ],
    },
]


async def seed_builtin_plugins(db: AsyncSession) -> None:
    """Insert or update builtin categories and plugins. Called once on app startup."""
    # Seed categories
    category_map: dict[str, uuid.UUID] = {}
    for cat_tmpl in BUILTIN_CATEGORIES:
        result = await db.execute(
            select(SkillCategory).where(SkillCategory.slug == cat_tmpl["slug"])
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            cat = SkillCategory(
                name=cat_tmpl["name"],
                slug=cat_tmpl["slug"],
                description=cat_tmpl.get("description"),
                sort_order=cat_tmpl.get("sort_order", 0),
            )
            db.add(cat)
            await db.flush()
            category_map[cat_tmpl["slug"]] = cat.id
        else:
            existing.name = cat_tmpl["name"]
            existing.description = cat_tmpl.get("description")
            existing.sort_order = cat_tmpl.get("sort_order", 0)
            category_map[cat_tmpl["slug"]] = existing.id

    # Seed plugins with their skills
    for tmpl in BUILTIN_PLUGINS:
        result = await db.execute(select(SkillPlugin).where(SkillPlugin.slug == tmpl["slug"]))
        existing = result.scalar_one_or_none()

        cat_id = category_map.get(tmpl.get("category_slug", ""))

        if existing is None:
            plugin = SkillPlugin(
                name=tmpl["name"],
                slug=tmpl["slug"],
                description=tmpl.get("description"),
                version=tmpl.get("version", "0.1.0"),
                icon=tmpl.get("icon"),
                tags=tmpl.get("tags"),
                plugin_type=PluginType(tmpl.get("plugin_type", "mcp")),
                source=PluginSource.builtin,
                transport=SkillTransport(tmpl["transport"]) if tmpl.get("transport") else None,
                server_command=tmpl.get("server_command"),
                server_args=tmpl.get("server_args"),
                server_url=tmpl.get("server_url"),
                config_schema=tmpl.get("config_schema"),
                is_builtin=True,
                sort_order=tmpl.get("sort_order", 100),
                category_id=cat_id,
                depends_on=tmpl.get("depends_on"),
            )
            db.add(plugin)
            await db.flush()

            for skill_tmpl in tmpl.get("skills", []):
                skill = PluginSkill(
                    plugin_id=plugin.id,
                    name=skill_tmpl["name"],
                    slug=skill_tmpl["slug"],
                    description=skill_tmpl.get("description"),
                    system_prompt=skill_tmpl.get("system_prompt"),
                    user_invocable=skill_tmpl.get("user_invocable", True),
                    sort_order=skill_tmpl.get("sort_order", 0),
                )
                db.add(skill)

        elif existing.is_builtin:
            existing.name = tmpl["name"]
            existing.description = tmpl.get("description")
            existing.icon = tmpl.get("icon")
            existing.tags = tmpl.get("tags")
            existing.sort_order = tmpl.get("sort_order", 100)
            existing.category_id = cat_id
            if tmpl.get("server_command"):
                existing.server_command = tmpl["server_command"]
            if tmpl.get("server_args"):
                existing.server_args = tmpl["server_args"]
            if tmpl.get("config_schema"):
                {f["key"] for f in (tmpl.get("config_schema") or {}).get("fields", [])}
                existing.config_schema = tmpl["config_schema"]

            # Upsert skills
            for skill_tmpl in tmpl.get("skills", []):
                skill_result = await db.execute(
                    select(PluginSkill).where(
                        PluginSkill.plugin_id == existing.id,
                        PluginSkill.slug == skill_tmpl["slug"],
                    )
                )
                existing_skill = skill_result.scalar_one_or_none()
                if existing_skill is None:
                    skill = PluginSkill(
                        plugin_id=existing.id,
                        name=skill_tmpl["name"],
                        slug=skill_tmpl["slug"],
                        description=skill_tmpl.get("description"),
                        system_prompt=skill_tmpl.get("system_prompt"),
                        user_invocable=skill_tmpl.get("user_invocable", True),
                        sort_order=skill_tmpl.get("sort_order", 0),
                    )
                    db.add(skill)
                else:
                    existing_skill.name = skill_tmpl["name"]
                    existing_skill.description = skill_tmpl.get("description")
                    existing_skill.system_prompt = skill_tmpl.get("system_prompt")
                    existing_skill.user_invocable = skill_tmpl.get("user_invocable", True)

    # Auto-enable configs that have credentials but enabled=False (data fix for
    # the bug where configure_integration never set enabled=True).
    from sqlalchemy import update

    await db.execute(
        update(UserPluginConfig)
        .where(
            UserPluginConfig.enabled.is_(False),
            UserPluginConfig.config_values.isnot(None),
        )
        .values(enabled=True)
    )

    await db.commit()


# Backward-compatible alias
seed_builtin_skills = seed_builtin_plugins
