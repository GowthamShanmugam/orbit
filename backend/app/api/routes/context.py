from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.projects import require_project_access
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.context import SessionLayerType
from app.models.session import Session as OrbitSession
from app.models.user import User
from app.services import context_engine as ctx_svc

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ContextSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    type: str
    name: str
    url: str | None = None
    config: dict[str, Any] | None = None
    auto_attach: bool
    last_indexed: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ContextSourceCreate(BaseModel):
    type: str
    name: str = Field(min_length=1, max_length=512)
    url: str | None = None
    config: dict[str, Any] | None = None
    auto_attach: bool = True


class SessionLayerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    type: SessionLayerType
    reference_url: str | None = None
    label: str
    cached_content: dict[str, Any] | None = None
    token_count: int
    created_at: datetime


class SessionLayerCreate(BaseModel):
    type: SessionLayerType
    label: str = Field(min_length=1, max_length=512)
    reference_url: str | None = None
    cached_content: dict[str, Any] | None = None
    token_count: int = 0



# ---------------------------------------------------------------------------
# Context sources (project-level)
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/context-sources",
    response_model=list[ContextSourceResponse],
)
async def list_context_sources(
    project_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(0, ge=0),
    limit: int = Query(
        default=settings.API_PAGE_LARGE_DEFAULT,
        ge=1,
        le=settings.API_PAGE_LARGE_MAX,
    ),
) -> list:
    await require_project_access(db, current.id, project_id)
    return await ctx_svc.list_context_sources(db, project_id, skip=skip, limit=limit)


@router.post(
    "/projects/{project_id}/context-sources",
    response_model=ContextSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_context_source(
    project_id: UUID,
    body: ContextSourceCreate,
    background_tasks: BackgroundTasks,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    await require_project_access(db, current.id, project_id, min_access="write")
    source = await ctx_svc.add_context_source(
        db,
        project_id=project_id,
        type=body.type,
        name=body.name,
        url=body.url,
        config=body.config,
        auto_attach=body.auto_attach,
    )

    if body.type in ("github_repo", "gitlab_repo") and body.url:
        background_tasks.add_task(_clone_repo_in_background, source.id, project_id, body.url)

    return source


@router.delete(
    "/projects/{project_id}/context-sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_context_source(
    project_id: UUID,
    source_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await require_project_access(db, current.id, project_id, min_access="write")
    source = await ctx_svc.get_context_source(db, source_id)
    if source is None or source.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    clone_path = (source.config or {}).get("clone_path")
    await ctx_svc.remove_context_source(db, source)

    if clone_path:
        repo_dir = Path(clone_path)
    else:
        repo_dir = Path(settings.REPO_CLONE_DIR) / str(project_id) / str(source_id)
    if repo_dir.exists():
        try:
            shutil.rmtree(repo_dir)
            logger.info("Cleaned up clone at %s", repo_dir)
        except Exception:
            logger.warning("Failed to clean up %s", repo_dir, exc_info=True)


# ---------------------------------------------------------------------------
# Git clone (background task)
# ---------------------------------------------------------------------------

async def _clone_repo_in_background(source_id: UUID, project_id: UUID, url: str) -> None:
    """Shallow-clone a repo to disk so the AI can browse it via repo tools."""
    from datetime import timezone
    from app.core.database import AsyncSessionLocal
    from app.services.github_service import branch_from_context_config, clone_repo

    clone_dir = Path(settings.REPO_CLONE_DIR) / str(project_id) / str(source_id)
    token = getattr(settings, "GITHUB_TOKEN", None)

    async with AsyncSessionLocal() as db:
        source = await ctx_svc.get_context_source(db, source_id)
        if source is None:
            return

        branch = branch_from_context_config(source.config)

        source.config = {
            **(source.config or {}),
            "clone_status": "cloning",
            "clone_path": str(clone_dir),
        }
        await db.commit()

        try:
            await clone_repo(url, clone_dir, token=token, branch=branch)
            source.config = {
                **(source.config or {}),
                "clone_status": "done",
                "clone_path": str(clone_dir),
            }
            source.last_indexed = datetime.now(timezone.utc)
            await db.commit()
            logger.info("Cloned %s → %s", url, clone_dir)
        except Exception as exc:
            logger.exception("Clone failed for %s", url)
            source.config = {
                **(source.config or {}),
                "clone_status": "error",
                "clone_error": str(exc)[:500],
            }
            await db.commit()


@router.post(
    "/context-sources/{source_id}/clone",
    status_code=status.HTTP_202_ACCEPTED,
)
async def clone_source_repo(
    source_id: UUID,
    background_tasks: BackgroundTasks,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Trigger a git clone for an existing repo context source."""
    source = await ctx_svc.get_context_source(db, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    await require_project_access(db, current.id, source.project_id, min_access="write")
    if source.type not in ("github_repo", "gitlab_repo"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only repo sources can be cloned",
        )
    if not source.url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source has no URL",
        )

    current_status = (source.config or {}).get("clone_status")
    if current_status == "cloning":
        return {"status": "already_running"}

    background_tasks.add_task(_clone_repo_in_background, source_id, source.project_id, source.url)
    return {"status": "started"}


# ---------------------------------------------------------------------------
# Session layers (session-level context layering)
# ---------------------------------------------------------------------------

@router.get(
    "/sessions/{session_id}/layers",
    response_model=list[SessionLayerResponse],
)
async def list_session_layers(
    session_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list:
    row = await db.execute(select(OrbitSession).where(OrbitSession.id == session_id))
    sess = row.scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    await require_project_access(db, current.id, sess.project_id)
    return await ctx_svc.list_session_layers(db, session_id)


@router.post(
    "/sessions/{session_id}/layers",
    response_model=SessionLayerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_session_layer(
    session_id: UUID,
    body: SessionLayerCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    row = await db.execute(select(OrbitSession).where(OrbitSession.id == session_id))
    sess = row.scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    await require_project_access(db, current.id, sess.project_id, min_access="write")
    return await ctx_svc.add_session_layer(
        db,
        session_id=session_id,
        type=body.type,
        label=body.label,
        reference_url=body.reference_url,
        cached_content=body.cached_content,
        token_count=body.token_count,
    )


@router.delete(
    "/sessions/{session_id}/layers/{layer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_session_layer(
    session_id: UUID,
    layer_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    layer = await ctx_svc.get_session_layer(db, layer_id)
    if layer is None or layer.session_id != session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layer not found")
    row = await db.execute(select(OrbitSession).where(OrbitSession.id == session_id))
    sess = row.scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    await require_project_access(db, current.id, sess.project_id, min_access="write")
    await ctx_svc.remove_session_layer(db, layer)
