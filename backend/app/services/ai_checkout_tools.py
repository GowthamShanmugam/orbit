"""Optional read/search tools scoped to a PR/MR checkout tree.

Used by AI Review and CI Debug so the model can open repo files only when
log/diff/artifacts are not enough. Not the full chat agent tool set.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.ai_client import get_ai_client
from app.services.ai_service import (
    AVAILABLE_MODELS,
    _create_message,
    _extract_tool_uses,
    _resolve_model_for_provider,
    _serialize_content_blocks,
)
from app.services.repo_tools import SKIP_DIRS

logger = logging.getLogger(__name__)

_MAX_TOOL_ROUNDS = 8
_MAX_READ_CHARS = 40_000
_MAX_SEARCH_HITS = 40

CHECKOUT_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": (
            "Read a source file from the PR/MR head checkout. "
            "Use only when the diff/log/artifacts are not enough "
            "(e.g. open a failing test, helper, or import)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repo-relative path (e.g. 'e2e/test_foo.py')",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Optional 1-based start line",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Optional 1-based end line (inclusive)",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_code",
        "description": (
            "Search text in the PR/MR head checkout. "
            "Use to locate a symbol, test name, or error string when the path is unknown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text to search for (case-insensitive)",
                },
                "path": {
                    "type": "string",
                    "description": "Optional subdirectory to limit the search",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Optional glob like '*.py' or '*_test.go'",
                },
            },
            "required": ["query"],
        },
    },
]


def _safe_path(root: Path, relative: str) -> Path:
    rel = (relative or "").lstrip("/").replace("\\", "/")
    if not rel or ".." in Path(rel).parts:
        raise FileNotFoundError("Invalid path")
    target = (root / rel).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise FileNotFoundError("Path traversal not allowed")
    return target


def _read_file(root: Path, inp: dict[str, Any]) -> str:
    target = _safe_path(root, str(inp.get("path") or ""))
    if not target.is_file():
        return f"Error: '{inp.get('path')}' is not a file or does not exist."
    content = target.read_text(errors="replace")
    if len(content) > _MAX_READ_CHARS:
        content = content[:_MAX_READ_CHARS] + "\n…(truncated)"
    start = inp.get("start_line")
    end = inp.get("end_line")
    if start or end:
        lines = content.split("\n")
        s = max(0, (int(start) if start else 1) - 1)
        e = int(end) if end else len(lines)
        selected = lines[s:e]
        return "\n".join(f"{s + i + 1:4d} | {line}" for i, line in enumerate(selected))
    return content


async def _search_code(root: Path, inp: dict[str, Any]) -> str:
    query = str(inp.get("query") or "").strip()
    if not query:
        return "Error: query is required."
    sub = str(inp.get("path") or "").strip()
    search_dir = _safe_path(root, sub) if sub else root
    if not search_dir.is_dir():
        return f"Error: '{sub}' is not a directory."

    file_pattern = str(inp.get("file_pattern") or "").strip()
    cmd = ["grep", "-rn", "-i"]
    if file_pattern:
        cmd.append(f"--include={file_pattern}")
    else:
        cmd.append("--include=*")
    cmd += [query, str(search_dir)]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    raw = stdout.decode(errors="replace")
    if not raw.strip():
        return f"No matches for '{query}'."

    results: list[dict[str, Any]] = []
    for line in raw.strip().split("\n"):
        if len(results) >= _MAX_SEARCH_HITS:
            break
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        fpath, lineno, text = parts[0], parts[1], parts[2]
        try:
            rel = str(Path(fpath).relative_to(root))
        except ValueError:
            rel = fpath
        # Skip noisy dirs if grep walked into them somehow.
        if any(part in SKIP_DIRS for part in Path(rel).parts):
            continue
        results.append(
            {
                "file": rel,
                "line": int(lineno) if lineno.isdigit() else lineno,
                "content": text.strip()[:200],
            }
        )

    header = f"Found matches (showing up to {_MAX_SEARCH_HITS})"
    return header + "\n" + json.dumps(results, indent=2)


async def execute_checkout_tool(
    name: str,
    tool_input: dict[str, Any],
    checkout_root: Path,
) -> str:
    try:
        if name == "read_file":
            return _read_file(checkout_root, tool_input)
        if name == "search_code":
            return await _search_code(checkout_root, tool_input)
        return f"Error: unknown tool '{name}'"
    except FileNotFoundError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        logger.exception("Checkout tool %s failed", name)
        return f"Error: {exc}"


def _extract_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts).strip()


async def run_with_checkout_tools(
    *,
    system: str,
    user_message: str,
    checkout_path: str | None,
    model_id: str,
    max_tokens: int = 4096,
    max_rounds: int = _MAX_TOOL_ROUNDS,
) -> tuple[str, list[str]]:
    """One-shot or short tool loop. Returns (final_text, files_touched).

    If *checkout_path* is missing/invalid, runs without tools.
    """
    mid = model_id if model_id in AVAILABLE_MODELS else "claude-sonnet-4-6"
    info = AVAILABLE_MODELS[mid]
    wire = _resolve_model_for_provider(mid)
    client = get_ai_client()

    root: Path | None = None
    if checkout_path:
        p = Path(checkout_path)
        if p.is_dir():
            root = p

    tools = CHECKOUT_TOOL_DEFINITIONS if root is not None else None
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    used_paths: list[str] = []

    create_kwargs: dict[str, Any] = {
        "model": wire,
        "max_tokens": min(max_tokens, int(info.get("max_tokens") or max_tokens)),
        "system": system,
        "messages": messages,
    }
    if tools:
        create_kwargs["tools"] = tools

    response = await _create_message(client, mid, create_kwargs)
    rounds = 0
    while root is not None and rounds < max_rounds:
        tool_uses = _extract_tool_uses(response)
        if not tool_uses:
            break
        rounds += 1
        messages.append(
            {"role": "assistant", "content": _serialize_content_blocks(response.content)}
        )
        results: list[dict[str, Any]] = []
        for tu in tool_uses:
            name = str(tu.get("name") or "")
            inp = tu.get("input") if isinstance(tu.get("input"), dict) else {}
            if name == "read_file":
                path = str(inp.get("path") or "").strip()
                if path and path not in used_paths:
                    used_paths.append(path)
            elif name == "search_code":
                q = str(inp.get("query") or "").strip()
                label = f"search:{q}" if q else "search"
                if label not in used_paths:
                    used_paths.append(label)
            out = await execute_checkout_tool(name, inp, root)
            # Cap tool result size for the model.
            if len(out) > settings.AI_TOOL_RESULT_TRIM_CHARS:
                half = settings.AI_TOOL_RESULT_TRIM_CHARS // 2
                out = out[:half] + "\n…(trimmed)…\n" + out[-half:]
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": out,
                }
            )
        messages.append({"role": "user", "content": results})
        response = await _create_message(
            client,
            mid,
            {
                "model": wire,
                "max_tokens": min(max_tokens, int(info.get("max_tokens") or max_tokens)),
                "system": system,
                "messages": messages,
                "tools": tools,
            },
        )

    # If we hit the round cap still asking for tools, force a text-only finish.
    if root is not None and _extract_tool_uses(response):
        messages.append(
            {"role": "assistant", "content": _serialize_content_blocks(response.content)}
        )
        pending = _extract_tool_uses(response)
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": "Tool limit reached. Answer now with what you have.",
                    }
                    for tu in pending
                ],
            }
        )
        messages.append(
            {
                "role": "user",
                "content": "Do not call tools. Return your final answer now.",
            }
        )
        response = await _create_message(
            client,
            mid,
            {
                "model": wire,
                "max_tokens": min(max_tokens, int(info.get("max_tokens") or max_tokens)),
                "system": system,
                "messages": messages,
            },
        )

    return _extract_text(response), used_paths
