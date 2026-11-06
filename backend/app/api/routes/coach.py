"""Daily Coach (Today) API — watchlists, brief, standup drafts, Focus sessions."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.projects import require_project_access
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services import coach_service

router = APIRouter(prefix="/coach", tags=["coach"])


class WatchlistsPut(BaseModel):
    watchlists: dict[str, Any] | None = None
    reminder_prefs: dict[str, Any] | None = None


class FocusRequest(BaseModel):
    orbit_project_id: UUID
    issue_key: str | None = Field(default=None, max_length=64)
    issue_url: str | None = Field(default=None, max_length=2048)
    issue_summary: str | None = Field(default=None, max_length=1024)
    mr: dict[str, Any] | None = None
    brief: str | None = Field(default=None, max_length=8000)


@router.get("/options/jira-projects")
async def jira_project_options(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Jira projects the current user can see (for watchlist dropdown)."""
    return await coach_service.list_jira_projects(db, current.id)


@router.get("/options/meetings")
async def meeting_options(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Upcoming Google Calendar events (for meeting watchlist dropdown)."""
    return await coach_service.list_calendar_meetings(db, current.id)


@router.get("/watchlists")
async def get_watchlists(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    return await coach_service.get_watchlists(db, current.id)


@router.put("/watchlists")
async def put_watchlists(
    body: WatchlistsPut,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    if body.watchlists is None and body.reminder_prefs is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide watchlists and/or reminder_prefs",
        )
    return await coach_service.put_watchlists(
        db,
        current.id,
        watchlists=body.watchlists,
        reminder_prefs=body.reminder_prefs,
    )


@router.post("/hooks/gitlab/{profile_id}")
async def gitlab_hook(
    profile_id: UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    from app.services import coach_runtime

    payload = await request.json()
    await coach_runtime.handle_gitlab(db, profile_id, payload if isinstance(payload, dict) else {})
    return {"ok": True}


@router.post("/hooks/github/{profile_id}")
async def github_hook(
    profile_id: UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    from app.services import coach_runtime

    payload = await request.json()
    event = request.headers.get("X-GitHub-Event") or ""
    await coach_runtime.handle_github(
        db, profile_id, event, payload if isinstance(payload, dict) else {}
    )
    return {"ok": True}


@router.post("/hooks/jira/{profile_id}")
async def jira_hook(
    profile_id: UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    from app.services import coach_runtime

    payload = await request.json()
    await coach_runtime.handle_jira(db, profile_id, payload if isinstance(payload, dict) else {})
    return {"ok": True}


class AttentionClear(BaseModel):
    key: str = Field(min_length=1, max_length=300)


@router.post("/attention/clear")
async def clear_attention(
    body: AttentionClear,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    from app.services import coach_runtime

    await coach_runtime.clear_attention(db, current, body.key)
    return {"ok": True}


@router.get("/today")
async def get_today(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    refresh: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    return await coach_service.assemble_today(db, current, refresh=refresh)


@router.post("/standup/{meeting_id}/draft")
async def standup_draft(
    meeting_id: str,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    try:
        return await coach_service.regenerate_standup_draft(db, current, meeting_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/focus", status_code=status.HTTP_201_CREATED)
async def focus(
    body: FocusRequest,
    background_tasks: BackgroundTasks,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    if not body.issue_key and not body.mr:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide issue_key and/or mr",
        )
    await require_project_access(db, current.id, body.orbit_project_id, min_access="write")
    result = await coach_service.create_focus_session(
        db,
        current,
        orbit_project_id=body.orbit_project_id,
        issue_key=body.issue_key,
        issue_url=body.issue_url,
        issue_summary=body.issue_summary,
        mr=body.mr,
        brief=body.brief,
    )
    layer_id = result.pop("pr_layer_id", None)
    if layer_id:
        from uuid import UUID as _UUID

        from app.services.pr_checkout_service import checkout_layer_in_background

        background_tasks.add_task(
            checkout_layer_in_background,
            layer_id=_UUID(layer_id),
            project_id=body.orbit_project_id,
            session_id=_UUID(result["session_id"]),
            user_id=current.id,
        )
    return result
