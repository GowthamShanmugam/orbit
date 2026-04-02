"""REST endpoints for browsing cloned repository files.

These power the Explorer sidebar and the Editor panel — separate from
the AI tool-use endpoints which serve the same data to Claude.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.projects import require_project_access
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.context import ContextSource, ContextSourceType
from app.models.user import User
from app.services.repo_tools import SKIP_DIRS

router = APIRouter()


class RepoInfo(BaseModel):
    id: str
    name: str
    url: str | None
    cloned: bool


class FileEntry(BaseModel):
    name: str
    type: str  # "file" | "dir"
    size: int | None = None
    path: str


class FileContent(BaseModel):
    path: str
    content: str
    language: str
    size: int
    total_lines: int


async def _get_repos(db: AsyncSession, project_id: UUID) -> list[ContextSource]:
    result = await db.execute(
        select(ContextSource).where(
            ContextSource.project_id == project_id,
            ContextSource.type.in_([
                ContextSourceType.github_repo,
                ContextSourceType.gitlab_repo,
            ]),
        )
    )
    return list(result.scalars().all())


def _clone_path(source: ContextSource) -> Path | None:
    cp = (source.config or {}).get("clone_path")
    if cp:
        p = Path(cp).resolve()
        return p if p.is_dir() else None
    fallback = (Path(settings.REPO_CLONE_DIR) / str(source.project_id) / str(source.id)).resolve()
    return fallback if fallback.is_dir() else None


def _language_from_ext(name: str) -> str:
    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".tsx": "typescriptreact", ".jsx": "javascriptreact",
        ".go": "go", ".rs": "rust", ".java": "java",
        ".rb": "ruby", ".sh": "shell", ".bash": "shell",
        ".yaml": "yaml", ".yml": "yaml", ".json": "json",
        ".toml": "toml", ".md": "markdown", ".html": "html",
        ".css": "css", ".scss": "scss", ".sql": "sql",
        ".dockerfile": "dockerfile", ".tf": "hcl",
        ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
        ".xml": "xml", ".proto": "protobuf", ".graphql": "graphql",
        ".env": "dotenv", ".ini": "ini", ".cfg": "ini",
        ".txt": "plaintext", ".csv": "plaintext", ".log": "plaintext",
    }
    _, ext = os.path.splitext(name.lower())
    if name.lower() in ("makefile", "dockerfile", "jenkinsfile", "rakefile"):
        return name.lower()
    return ext_map.get(ext, "plaintext")


@router.get(
    "/projects/{project_id}/repos",
    response_model=list[RepoInfo],
)
async def list_repos(
    project_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[RepoInfo]:
    await require_project_access(db, current.id, project_id)
    sources = await _get_repos(db, project_id)
    return [
        RepoInfo(
            id=str(s.id),
            name=s.name,
            url=s.url,
            cloned=_clone_path(s) is not None,
        )
        for s in sources
    ]


@router.get(
    "/projects/{project_id}/repos/{repo_id}/tree",
    response_model=list[FileEntry],
)
async def list_directory(
    project_id: UUID,
    repo_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    path: str = Query("", description="Directory path relative to repo root"),
) -> list[FileEntry]:
    await require_project_access(db, current.id, project_id)
    source = await _require_source(db, project_id, repo_id)
    repo_dir = _clone_path(source)
    if not repo_dir:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Repository not cloned")

    target = _safe_resolve(repo_dir, path)
    if not target.is_dir():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Directory not found")

    entries: list[FileEntry] = []
    for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if item.name in SKIP_DIRS or item.name.startswith("."):
            continue
        rel = str(item.relative_to(repo_dir))
        entry = FileEntry(
            name=item.name,
            type="dir" if item.is_dir() else "file",
            size=item.stat().st_size if item.is_file() else None,
            path=rel,
        )
        entries.append(entry)
    return entries


@router.get(
    "/projects/{project_id}/repos/{repo_id}/file",
    response_model=FileContent,
)
async def read_file(
    project_id: UUID,
    repo_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    path: str = Query(..., description="File path relative to repo root"),
) -> FileContent:
    await require_project_access(db, current.id, project_id)
    source = await _require_source(db, project_id, repo_id)
    repo_dir = _clone_path(source)
    if not repo_dir:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Repository not cloned")

    target = _safe_resolve(repo_dir, path)
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


async def _require_source(
    db: AsyncSession, project_id: UUID, repo_id: UUID
) -> ContextSource:
    result = await db.execute(
        select(ContextSource).where(
            ContextSource.id == repo_id,
            ContextSource.project_id == project_id,
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Repository not found")
    return source


def _safe_resolve(repo_dir: Path, relative: str) -> Path:
    target = (repo_dir / relative).resolve()
    if not str(target).startswith(str(repo_dir.resolve())):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Path traversal not allowed")
    return target
