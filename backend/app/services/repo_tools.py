"""Anthropic tool definitions for on-demand repository exploration.

Instead of bulk-indexing repo files into the DB, the AI uses these tools
to browse cloned repos on disk — listing directories, reading files, and
searching code — fetching only what it needs per conversation turn.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.context import ContextSource, ContextSourceType
from app.services.github_service import (
    branch_from_context_config,
    repo_stream_from_context_config,
)

logger = logging.getLogger(__name__)

SKIP_DIRS = frozenset({
    ".git", "node_modules", "vendor", "dist", "build", "__pycache__",
    ".tox", ".mypy_cache", ".pytest_cache", ".venv", "venv", "env",
    ".next", ".nuxt", "target", "out", "coverage", ".terraform",
    ".eggs", "site-packages",
})

# ---------------------------------------------------------------------------
# Tool definitions (Anthropic format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "repo_list_sources",
        "description": (
            "List all code repositories attached to this project. "
            "Returns each repo's name, URL, configured branch and stream role "
            "(upstream/midstream/downstream when set), clone status, and local path. "
            "Call this first to discover which repos are available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "repo_get_file_tree",
        "description": (
            "Get a compact file tree of the entire repository. "
            "Returns a newline-separated list of all file paths (excluding "
            "common non-source directories like node_modules, .git, etc). "
            "Use this to understand the project structure before reading specific files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_name": {
                    "type": "string",
                    "description": "Name of the repo context source",
                },
                "path": {
                    "type": "string",
                    "description": "Subdirectory to scope the tree to (e.g. 'src/'). Empty for root.",
                },
            },
            "required": ["repo_name"],
        },
    },
    {
        "name": "repo_list_directory",
        "description": (
            "List files and directories at a specific path in the repo. "
            "Returns entries with name, type (file/dir), and size."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_name": {
                    "type": "string",
                    "description": "Name of the repo context source",
                },
                "path": {
                    "type": "string",
                    "description": "Directory path relative to repo root (e.g. 'src/components'). Empty for root.",
                },
            },
            "required": ["repo_name"],
        },
    },
    {
        "name": "repo_read_file",
        "description": (
            "Read the contents of a specific file from the repo. "
            "Returns the file content as text. For large files, only the "
            "first 100KB is returned."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_name": {
                    "type": "string",
                    "description": "Name of the repo context source",
                },
                "file_path": {
                    "type": "string",
                    "description": "Path to the file relative to repo root (e.g. 'src/main.py')",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Start reading from this line number (1-based). Omit for beginning of file.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Stop reading at this line number (inclusive). Omit for end of file.",
                },
            },
            "required": ["repo_name", "file_path"],
        },
    },
    {
        "name": "repo_search_code",
        "description": (
            "Search for a text pattern across all files in the repo. "
            "Returns matching file paths and line numbers with context. "
            "Supports basic text search (case-insensitive). "
            "Use this to find function definitions, imports, usages, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_name": {
                    "type": "string",
                    "description": "Name of the repo context source",
                },
                "query": {
                    "type": "string",
                    "description": "Text pattern to search for",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Glob pattern to restrict search (e.g. '*.py', '*.tsx'). Omit for all files.",
                },
                "path": {
                    "type": "string",
                    "description": "Subdirectory to restrict search to (e.g. 'src/'). Omit for entire repo.",
                },
            },
            "required": ["repo_name", "query"],
        },
    },
]


def get_tool_definitions() -> list[dict[str, Any]]:
    return list(TOOL_DEFINITIONS)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

async def execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    project_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    try:
        if tool_name == "repo_list_sources":
            return await _list_sources(project_id, db)
        elif tool_name == "repo_get_file_tree":
            return await _get_file_tree(tool_input, project_id, db)
        elif tool_name == "repo_list_directory":
            return await _list_directory(tool_input, project_id, db)
        elif tool_name == "repo_read_file":
            return await _read_file(tool_input, project_id, db)
        elif tool_name == "repo_search_code":
            return await _search_code(tool_input, project_id, db)
        else:
            return f"Error: Unknown tool '{tool_name}'"
    except FileNotFoundError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        logger.exception("Repo tool execution failed: %s", tool_name)
        return f"Error: {exc}"


def get_tool_activity_label(tool_name: str, tool_input: dict[str, Any]) -> str:
    repo = tool_input.get("repo_name", "")
    labels: dict[str, str] = {
        "repo_list_sources": "Listing project repositories",
        "repo_get_file_tree": f"Getting file tree for {repo}",
        "repo_list_directory": f"Listing {tool_input.get('path', '/')} in {repo}",
        "repo_read_file": f"Reading {tool_input.get('file_path', 'file')} from {repo}",
        "repo_search_code": f"Searching '{tool_input.get('query', '')}' in {repo}",
    }
    return labels.get(tool_name, f"Executing {tool_name}")


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------

async def _resolve_source(
    repo_name: str, project_id: uuid.UUID, db: AsyncSession
) -> tuple[ContextSource, Path]:
    stmt = select(ContextSource).where(
        ContextSource.project_id == project_id,
        ContextSource.name == repo_name,
        ContextSource.type.in_([
            ContextSourceType.github_repo,
            ContextSourceType.gitlab_repo,
        ]),
    )
    result = await db.execute(stmt)
    source = result.scalar_one_or_none()
    if source is None:
        raise FileNotFoundError(
            f"Repo '{repo_name}' not found. Use repo_list_sources to see available repos."
        )

    clone_path = (source.config or {}).get("clone_path")
    if not clone_path:
        clone_path = str(
            Path(settings.REPO_CLONE_DIR) / str(project_id) / str(source.id)
        )

    repo_dir = Path(clone_path)
    if not repo_dir.exists():
        raise FileNotFoundError(
            f"Repo '{repo_name}' has not been cloned yet. The clone directory does not exist."
        )
    return source, repo_dir


def _safe_path(repo_dir: Path, relative: str) -> Path:
    """Resolve a relative path inside the repo, preventing directory traversal."""
    target = (repo_dir / relative).resolve()
    if not str(target).startswith(str(repo_dir.resolve())):
        raise FileNotFoundError("Path traversal not allowed")
    return target


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _list_sources(project_id: uuid.UUID, db: AsyncSession) -> str:
    import json
    stmt = select(ContextSource).where(
        ContextSource.project_id == project_id,
        ContextSource.type.in_([
            ContextSourceType.github_repo,
            ContextSourceType.gitlab_repo,
        ]),
    )
    result = await db.execute(stmt)
    sources = result.scalars().all()

    if not sources:
        return "No code repositories are attached to this project."

    rows = []
    for s in sources:
        cfg = s.config or {}
        clone_path = cfg.get("clone_path", "")
        cloned = bool(clone_path and Path(clone_path).exists())
        stream = repo_stream_from_context_config(cfg)
        row: dict[str, Any] = {
            "name": s.name,
            "url": s.url,
            "type": s.type.value,
            "branch": branch_from_context_config(cfg),
            "cloned": cloned,
        }
        if stream:
            row["repo_stream"] = stream
        rows.append(row)
    return json.dumps(rows, indent=2)


async def _get_file_tree(
    inp: dict[str, Any], project_id: uuid.UUID, db: AsyncSession
) -> str:
    _, repo_dir = await _resolve_source(inp["repo_name"], project_id, db)
    sub = inp.get("path", "")
    root = _safe_path(repo_dir, sub) if sub else repo_dir

    if not root.is_dir():
        return f"Error: '{sub}' is not a directory."

    entries: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel_dir = Path(dirpath).relative_to(repo_dir)
        for fname in sorted(filenames):
            entries.append(str(rel_dir / fname))
            if len(entries) >= settings.REPO_MAX_TREE_ENTRIES:
                entries.append(
                    f"... truncated at {settings.REPO_MAX_TREE_ENTRIES} entries"
                )
                return "\n".join(entries)

    if not entries:
        return "No files found."
    return "\n".join(entries)


async def _list_directory(
    inp: dict[str, Any], project_id: uuid.UUID, db: AsyncSession
) -> str:
    import json
    _, repo_dir = await _resolve_source(inp["repo_name"], project_id, db)
    sub = inp.get("path", "")
    target = _safe_path(repo_dir, sub) if sub else repo_dir

    if not target.is_dir():
        return f"Error: '{sub}' is not a directory."

    entries = []
    for item in sorted(target.iterdir()):
        if item.name in SKIP_DIRS or item.name.startswith("."):
            continue
        entry: dict[str, Any] = {
            "name": item.name,
            "type": "dir" if item.is_dir() else "file",
        }
        if item.is_file():
            entry["size"] = item.stat().st_size
        entries.append(entry)

    return json.dumps(entries, indent=2)


async def _read_file(
    inp: dict[str, Any], project_id: uuid.UUID, db: AsyncSession
) -> str:
    _, repo_dir = await _resolve_source(inp["repo_name"], project_id, db)
    target = _safe_path(repo_dir, inp["file_path"])

    if not target.is_file():
        return f"Error: '{inp['file_path']}' is not a file or does not exist."

    if target.stat().st_size > settings.REPO_MAX_FILE_READ_CHARS:
        content = target.read_text(errors="replace")[: settings.REPO_MAX_FILE_READ_CHARS]
        content += "\n... (truncated at 100KB)"
    else:
        content = target.read_text(errors="replace")

    start = inp.get("start_line")
    end = inp.get("end_line")
    if start or end:
        lines = content.split("\n")
        s = max(0, (start or 1) - 1)
        e = end or len(lines)
        selected = lines[s:e]
        numbered = [f"{s + i + 1:4d} | {line}" for i, line in enumerate(selected)]
        return "\n".join(numbered)

    return content


async def _search_code(
    inp: dict[str, Any], project_id: uuid.UUID, db: AsyncSession
) -> str:
    import asyncio
    import json as json_mod

    _, repo_dir = await _resolve_source(inp["repo_name"], project_id, db)
    query = inp["query"]
    sub = inp.get("path", "")
    search_dir = _safe_path(repo_dir, sub) if sub else repo_dir

    cmd = ["grep", "-rn", "-i", "--include=*"]
    file_pattern = inp.get("file_pattern")
    if file_pattern:
        cmd = ["grep", "-rn", "-i", f"--include={file_pattern}"]
    cmd += [query, str(search_dir)]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    raw = stdout.decode(errors="replace")

    if not raw.strip():
        return f"No matches found for '{query}'."

    results = []
    for line in raw.strip().split("\n")[: settings.REPO_MAX_SEARCH_RESULTS]:
        parts = line.split(":", 2)
        if len(parts) >= 3:
            fpath = parts[0]
            try:
                rel = str(Path(fpath).relative_to(repo_dir))
            except ValueError:
                rel = fpath
            results.append({
                "file": rel,
                "line": int(parts[1]) if parts[1].isdigit() else parts[1],
                "content": parts[2].strip()[:200],
            })

    total_lines = raw.count("\n")
    header = f"Found {total_lines} matches"
    if total_lines > settings.REPO_MAX_SEARCH_RESULTS:
        header += f" (showing first {settings.REPO_MAX_SEARCH_RESULTS})"

    return header + "\n" + json_mod.dumps(results, indent=2)
