"""Session-scoped filesystem for AI-generated reports and documents.

Stored under SESSION_ARTIFACTS_DIR / {project_id} / {session_id} / — separate from
cloned repos. Deleted when the session is deleted.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "artifact_write_file",
        "description": (
            "Write or overwrite a file in this session's document area. "
            "Use this for reports, markdown documents, exported notes, summaries, "
            "and any deliverable the user should open in the Explorer. "
            "Paths are relative to the session root (e.g. 'reports/q1-summary.md', "
            "'notes/architecture.txt'). "
            "IMPORTANT: When the user asks for a report or document, save it here — "
            "do not only paste long content in chat. Prefer subfolders like 'reports/' "
            "or 'docs/' for organization."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative path under the session artifact root (use forward slashes).",
                },
                "content": {
                    "type": "string",
                    "description": "Full file contents as UTF-8 text.",
                },
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "artifact_list_directory",
        "description": (
            "List files and subdirectories in this session's document area. "
            "Pass an empty path for the root, or a subdirectory like 'reports'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory relative to session root; empty for root.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "artifact_read_file",
        "description": (
            "Read a text file from this session's document area. "
            "Use after writing or to inspect existing session documents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path relative to session root.",
                },
            },
            "required": ["file_path"],
        },
    },
]


def get_tool_definitions() -> list[dict[str, Any]]:
    return list(TOOL_DEFINITIONS)


def artifact_root(project_id: uuid.UUID, session_id: uuid.UUID) -> Path:
    base = Path(settings.SESSION_ARTIFACTS_DIR).resolve()
    return base / str(project_id) / str(session_id)


def ensure_artifact_root(project_id: uuid.UUID, session_id: uuid.UUID) -> Path:
    root = artifact_root(project_id, session_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_path(root: Path, relative: str) -> Path:
    rel = (relative or "").replace("\\", "/").lstrip("/")
    target = (root / rel).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise FileNotFoundError("Path traversal not allowed")
    return target


def delete_artifact_tree(project_id: uuid.UUID, session_id: uuid.UUID) -> None:
    p = artifact_root(project_id, session_id)
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)


def get_tool_activity_label(tool_name: str, tool_input: dict[str, Any]) -> str:
    labels: dict[str, str] = {
        "artifact_write_file": f"Writing {tool_input.get('file_path', 'file')}",
        "artifact_list_directory": f"Listing session documents /{tool_input.get('path', '')}",
        "artifact_read_file": f"Reading {tool_input.get('file_path', 'file')}",
    }
    return labels.get(tool_name, tool_name)


async def execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    project_id: uuid.UUID,
    session_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    del db  # filesystem only
    try:
        if tool_name == "artifact_write_file":
            return await _write_file(tool_input, project_id, session_id)
        if tool_name == "artifact_list_directory":
            return await _list_directory(tool_input, project_id, session_id)
        if tool_name == "artifact_read_file":
            return await _read_file(tool_input, project_id, session_id)
        return f"Error: Unknown tool '{tool_name}'"
    except FileNotFoundError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        logger.exception("Artifact tool failed: %s", tool_name)
        return f"Error: {exc}"


async def _write_file(
    inp: dict[str, Any], project_id: uuid.UUID, session_id: uuid.UUID
) -> str:
    import json as json_mod

    fp = (inp.get("file_path") or "").strip()
    content = inp.get("content")
    if not fp:
        return "Error: file_path is required."
    if not isinstance(content, str):
        return "Error: content must be a string."
    if len(content) > settings.ARTIFACT_MAX_WRITE_CHARS:
        return (
            f"Error: content too large (max {settings.ARTIFACT_MAX_WRITE_CHARS} characters)."
        )

    root = ensure_artifact_root(project_id, session_id)
    target = _safe_path(root, fp)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    rel = str(target.relative_to(root))
    return json_mod.dumps({"ok": True, "path": rel, "bytes": len(content.encode("utf-8"))})


async def _list_directory(
    inp: dict[str, Any], project_id: uuid.UUID, session_id: uuid.UUID
) -> str:
    import json as json_mod

    root = ensure_artifact_root(project_id, session_id)
    sub = (inp.get("path") or "").strip().replace("\\", "/")
    target = _safe_path(root, sub) if sub else root

    if not target.is_dir():
        return f"Error: '{sub or '/'}' is not a directory."

    entries = []
    for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if item.name.startswith("."):
            continue
        entry: dict[str, Any] = {
            "name": item.name,
            "type": "dir" if item.is_dir() else "file",
        }
        if item.is_file():
            entry["size"] = item.stat().st_size
        entries.append(entry)

    if not entries:
        return "(empty directory)"
    return json_mod.dumps(entries, indent=2)


async def _read_file(
    inp: dict[str, Any], project_id: uuid.UUID, session_id: uuid.UUID
) -> str:
    root = ensure_artifact_root(project_id, session_id)
    fp = (inp.get("file_path") or "").strip()
    if not fp:
        return "Error: file_path is required."

    target = _safe_path(root, fp)
    if not target.is_file():
        return f"Error: '{fp}' is not a file or does not exist."

    size = target.stat().st_size
    if size > settings.ARTIFACT_MAX_FILE_CHARS:
        text = target.read_text(errors="replace")[: settings.ARTIFACT_MAX_FILE_CHARS]
        return text + "\n\n... (truncated)"
    return target.read_text(errors="replace")
