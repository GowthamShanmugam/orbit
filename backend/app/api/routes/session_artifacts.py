"""REST API for session-scoped AI documents (Explorer sidebar)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.files import FileContent, FileEntry, _language_from_ext
from app.api.routes.projects import require_orbit_session_in_project
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.session_artifact_tools import (
    artifact_root,
    ensure_artifact_root,
)

router = APIRouter()


def _safe_resolve(root: Path, relative: str) -> Path:
    rel = (relative or "").replace("\\", "/").lstrip("/")
    target = (root / rel).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Path traversal not allowed")
    return target


@router.get(
    "/projects/{project_id}/sessions/{session_id}/artifacts/tree",
    response_model=list[FileEntry],
)
async def list_artifact_directory(
    project_id: UUID,
    session_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    path: str = Query("", description="Directory relative to session artifact root"),
) -> list[FileEntry]:
    await require_orbit_session_in_project(
        db, current.id, project_id, session_id, min_access="read"
    )
    root = ensure_artifact_root(project_id, session_id)
    target = _safe_resolve(root, path)
    if not target.is_dir():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Directory not found")

    entries: list[FileEntry] = []
    for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if item.name.startswith("."):
            continue
        rel = str(item.relative_to(root))
        entries.append(
            FileEntry(
                name=item.name,
                type="dir" if item.is_dir() else "file",
                size=item.stat().st_size if item.is_file() else None,
                path=rel,
            )
        )
    return entries


@router.get(
    "/projects/{project_id}/sessions/{session_id}/artifacts/file",
    response_model=FileContent,
)
async def read_artifact_file(
    project_id: UUID,
    session_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    path: str = Query(..., description="File path relative to session artifact root"),
) -> FileContent:
    await require_orbit_session_in_project(
        db, current.id, project_id, session_id, min_access="read"
    )
    root = ensure_artifact_root(project_id, session_id)
    target = _safe_resolve(root, path)
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")

    size = target.stat().st_size
    if size > settings.ARTIFACT_MAX_FILE_CHARS:
        content = target.read_text(errors="replace")[: settings.ARTIFACT_MAX_FILE_CHARS]
        content += "\n\n// ... truncated (file too large)"
    else:
        content = target.read_text(errors="replace")

    return FileContent(
        path=path,
        content=content,
        language=_language_from_ext(target.name),
        size=size,
        total_lines=content.count("\n") + 1,
    )


@router.get("/projects/{project_id}/sessions/{session_id}/artifacts/download")
async def download_artifact_file(
    project_id: UUID,
    session_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    path: str = Query(..., description="File path relative to session artifact root"),
) -> FileResponse:
    await require_orbit_session_in_project(
        db, current.id, project_id, session_id, min_access="read"
    )
    root = artifact_root(project_id, session_id)
    target = _safe_resolve(root, path)
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")

    filename = os.path.basename(target.name) or "download"
    return FileResponse(
        path=str(target),
        filename=filename,
        media_type="application/octet-stream",
    )
