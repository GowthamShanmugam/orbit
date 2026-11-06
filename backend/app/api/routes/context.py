from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
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
        from app.services.github_service import bump_clone_generation

        clone_generation = bump_clone_generation(source.id)
        background_tasks.add_task(
            _clone_repo_in_background,
            source.id,
            project_id,
            body.url,
            current.id,
            clone_generation,
        )

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


async def _resolve_clone_token(
    db: Any, user_id: UUID | None, url: str
) -> tuple[str | None, bool]:
    """Return (token, ssl_verify) for cloning *url*."""
    from sqlalchemy import select

    from app.models.skill import SkillPlugin, UserPluginConfig
    from app.services.github_service import _ssh_to_https

    https = _ssh_to_https(url).lower()
    token = getattr(settings, "GITHUB_TOKEN", None)
    ssl_verify = True
    if user_id is None:
        return token, ssl_verify

    if "gitlab" in https or "github.com" not in https:
        result = await db.execute(
            select(UserPluginConfig)
            .join(SkillPlugin, SkillPlugin.id == UserPluginConfig.plugin_id)
            .where(
                SkillPlugin.slug == "gitlab",
                UserPluginConfig.user_id == user_id,
                UserPluginConfig.enabled,
            )
        )
        cfg = result.scalar_one_or_none()
        if cfg and cfg.config_values:
            gl_token = (cfg.config_values.get("GITLAB_PERSONAL_ACCESS_TOKEN") or "").strip()
            if gl_token:
                token = gl_token
            raw = cfg.config_values.get("GITLAB_SSL_VERIFY")
            if raw is not None and str(raw).strip() != "":
                ssl_verify = str(raw).strip().lower() in ("1", "true", "yes", "on")
            else:
                ssl_verify = "gitlab.com" in https
        return token, ssl_verify

    result = await db.execute(
        select(UserPluginConfig)
        .join(SkillPlugin, SkillPlugin.id == UserPluginConfig.plugin_id)
        .where(
            SkillPlugin.slug == "github",
            UserPluginConfig.user_id == user_id,
            UserPluginConfig.enabled,
        )
    )
    cfg = result.scalar_one_or_none()
    if cfg and cfg.config_values:
        gh = (cfg.config_values.get("GITHUB_PERSONAL_ACCESS_TOKEN") or "").strip()
        if gh:
            token = gh
    return token, ssl_verify


async def _flush_clone_progress(source_id: UUID, stop: Any) -> None:
    import asyncio

    from sqlalchemy.orm.attributes import flag_modified

    from app.core.database import AsyncSessionLocal
    from app.services.github_service import get_clone_progress

    last: tuple[int, str] | None = None
    while not stop.is_set():
        cur = get_clone_progress(source_id)
        if cur and cur != last:
            last = cur
            pct, stage = cur
            try:
                async with AsyncSessionLocal() as db:
                    source = await ctx_svc.get_context_source(db, source_id)
                    if source is not None:
                        source.config = {
                            **(source.config or {}),
                            "clone_status": "cloning",
                            "clone_progress": pct,
                            "clone_stage": stage,
                        }
                        flag_modified(source, "config")
                        await db.commit()
            except Exception:
                logger.debug("clone progress flush failed for %s", source_id, exc_info=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.4)
        except TimeoutError:
            pass


async def _clone_repo_in_background(
    source_id: UUID,
    project_id: UUID,
    url: str,
    user_id: UUID | None = None,
    clone_generation: int | None = None,
) -> None:
    """Shallow-clone a repo to disk so the AI can browse it via repo tools."""
    import asyncio
    from contextlib import suppress

    from sqlalchemy.orm.attributes import flag_modified

    from app.core.database import AsyncSessionLocal
    from app.services.github_service import (
        CloneCancelled,
        branch_from_context_config,
        clear_clone_progress,
        clone_repo,
        is_clone_generation_current,
        note_clone_progress,
    )

    clone_dir = Path(settings.REPO_CLONE_DIR) / str(project_id) / str(source_id)
    stop = asyncio.Event()
    flusher = asyncio.create_task(_flush_clone_progress(source_id, stop))

    def _still_current() -> bool:
        return is_clone_generation_current(source_id, clone_generation)

    try:
        async with AsyncSessionLocal() as db:
            source = await ctx_svc.get_context_source(db, source_id)
            if source is None:
                return
            if not _still_current():
                return

            branch = branch_from_context_config(source.config)
            token, ssl_verify = await _resolve_clone_token(db, user_id, url)
            note_clone_progress(source_id, 2, "Queued")
            source.config = {
                **(source.config or {}),
                "clone_status": "cloning",
                "clone_path": str(clone_dir),
                "clone_progress": 2,
                "clone_stage": "Queued",
            }
            source.config.pop("clone_error", None)
            flag_modified(source, "config")
            await db.commit()

            try:
                await clone_repo(
                    url,
                    clone_dir,
                    token=token,
                    branch=branch,
                    source_id=source_id,
                    ssl_verify=ssl_verify,
                    generation=clone_generation,
                )
                if not _still_current():
                    return
                source.config = {
                    **(source.config or {}),
                    "clone_status": "done",
                    "clone_path": str(clone_dir),
                    "clone_progress": 100,
                    "clone_stage": "Done",
                }
                source.config.pop("clone_error", None)
                flag_modified(source, "config")
                source.last_indexed = datetime.now(UTC)
                await db.commit()
                logger.info("Cloned %s → %s", url, clone_dir)
            except CloneCancelled:
                logger.info("Clone cancelled/superseded for %s", url)
            except Exception as exc:
                if not _still_current():
                    return
                logger.exception("Clone failed for %s", url)
                source.config = {
                    **(source.config or {}),
                    "clone_status": "error",
                    "clone_error": str(exc)[:500],
                }
                flag_modified(source, "config")
                await db.commit()
    finally:
        stop.set()
        with suppress(Exception):
            await flusher
        if _still_current():
            clear_clone_progress(source_id)


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

    from sqlalchemy.orm.attributes import flag_modified

    from app.services.github_service import bump_clone_generation

    was_cloning = (source.config or {}).get("clone_status") == "cloning"
    # Kill any in-flight git and start a fresh attempt (supports retry while cloning).
    clone_generation = bump_clone_generation(source_id)

    # Reset progress so the UI shows a fresh bar immediately.
    source.config = {
        **(source.config or {}),
        "clone_status": "cloning",
        "clone_progress": 0,
        "clone_stage": "Retrying…" if was_cloning else "Starting…",
    }
    source.config.pop("clone_error", None)
    flag_modified(source, "config")
    await db.commit()

    background_tasks.add_task(
        _clone_repo_in_background,
        source_id,
        source.project_id,
        source.url,
        current.id,
        clone_generation,
    )
    return {"status": "restarted" if was_cloning else "started"}


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
    background_tasks: BackgroundTasks,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    row = await db.execute(select(OrbitSession).where(OrbitSession.id == session_id))
    sess = row.scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    await require_project_access(db, current.id, sess.project_id, min_access="write")

    reference_url = body.reference_url
    cached = dict(body.cached_content or {})
    if body.type == SessionLayerType.pull_request:
        from app.services.session_layer_prompt import _parse_github_pr, _parse_gitlab_mr

        # Accept URL pasted in Label when Reference URL is empty.
        if not reference_url:
            label = (body.label or "").strip()
            if _parse_github_pr(label) or _parse_gitlab_mr(label):
                reference_url = label
        if reference_url:
            cached["pr_checkout_status"] = "fetching"

    layer = await ctx_svc.add_session_layer(
        db,
        session_id=session_id,
        type=body.type,
        label=body.label,
        reference_url=reference_url,
        cached_content=cached or None,
        token_count=body.token_count,
    )

    if body.type == SessionLayerType.pull_request and reference_url:
        from app.services.pr_checkout_service import checkout_layer_in_background

        background_tasks.add_task(
            checkout_layer_in_background,
            layer_id=layer.id,
            project_id=sess.project_id,
            session_id=session_id,
            user_id=current.id,
        )

    return layer


@router.post(
    "/sessions/{session_id}/layers/{layer_id}/retry-checkout",
    response_model=SessionLayerResponse,
)
async def retry_pr_layer_checkout(
    session_id: UUID,
    layer_id: UUID,
    background_tasks: BackgroundTasks,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """Re-trigger PR/MR head checkout without deleting the layer."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.services.pr_checkout_service import (
        checkout_layer_in_background,
        resolve_pr_layer_url,
    )
    from app.services.session_layer_prompt import _parse_github_pr, _parse_gitlab_mr

    layer = await ctx_svc.get_session_layer(db, layer_id)
    if layer is None or layer.session_id != session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layer not found")
    if layer.type != SessionLayerType.pull_request:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Retry checkout is only for pull request layers.",
        )

    row = await db.execute(select(OrbitSession).where(OrbitSession.id == session_id))
    sess = row.scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    await require_project_access(db, current.id, sess.project_id, min_access="write")

    # Heal label-only URL into reference_url.
    url = resolve_pr_layer_url(layer)
    if not url:
        label = (layer.label or "").strip()
        if _parse_github_pr(label) or _parse_gitlab_mr(label):
            url = label
            layer.reference_url = label
    if not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No PR/MR URL on this layer. Set Reference URL and retry.",
        )
    if not layer.reference_url:
        layer.reference_url = url

    cc = dict(layer.cached_content or {})
    for key in list(cc):
        if key.startswith("pr_checkout"):
            cc.pop(key)
    cc["pr_checkout_status"] = "fetching"
    cc["pr_checkout_progress"] = 0
    cc["pr_checkout_stage"] = "Retrying…"
    layer.cached_content = cc
    flag_modified(layer, "cached_content")
    await db.commit()
    await db.refresh(layer)

    background_tasks.add_task(
        checkout_layer_in_background,
        layer_id=layer.id,
        project_id=sess.project_id,
        session_id=session_id,
        user_id=current.id,
    )
    return layer


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
