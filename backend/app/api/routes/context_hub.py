from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.security import get_current_user
from app.models.context import ContextSource, PackVisibility
from app.models.organization import Team, TeamMember
from app.models.user import User
from app.services import context_hub_service as hub_svc

logger = logging.getLogger(__name__)


async def _user_org_ids(db: AsyncSession, user_id: UUID) -> list[UUID]:
    result = await db.execute(
        select(Team.org_id)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user_id)
        .distinct()
    )
    return [row[0] for row in result.all()]

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PackSourceSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pack_id: UUID
    type: str
    name: str
    url: str | None = None
    config: dict[str, Any] | None = None
    created_at: datetime


class PackSourceCreate(BaseModel):
    type: str
    name: str = Field(min_length=1, max_length=512)
    url: str | None = None
    config: dict[str, Any] | None = None


class PackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    icon: str | None = None
    description: str | None = None
    category: str | None = None
    version: str
    visibility: PackVisibility
    dependencies: dict[str, Any] | None = None
    maintainer_team: str | None = None
    org_id: UUID | None = None
    created_by: UUID | None = None
    repo_count: int
    sources: list[PackSourceSchema] = []
    created_at: datetime
    updated_at: datetime


class PackCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    icon: str | None = None
    category: str | None = None
    visibility: PackVisibility = PackVisibility.organization
    dependencies: dict[str, Any] | None = None
    maintainer_team: str | None = None
    org_id: UUID | None = None
    sources: list[PackSourceCreate] | None = None


class PackUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    icon: str | None = None
    category: str | None = None
    visibility: PackVisibility | None = None
    maintainer_team: str | None = None


class InstalledPackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    pack_id: UUID
    version: str
    auto_update: bool
    overrides: dict[str, Any] | None = None
    installed_at: datetime
    pack: PackResponse


class InstallPackRequest(BaseModel):
    pack_id: UUID
    auto_update: bool = True


# ---------------------------------------------------------------------------
# Pack catalog
# ---------------------------------------------------------------------------

@router.get("/packs", response_model=list[PackResponse])
async def list_packs(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: str | None = Query(default=None),
    search: str | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> list:
    org_ids = await _user_org_ids(db, current.id)
    return await hub_svc.list_packs(
        db,
        org_ids=org_ids,
        user_id=current.id,
        category=category,
        search=search,
        skip=skip,
        limit=limit,
    )


@router.get("/packs/categories", response_model=list[str])
async def list_categories(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[str]:
    return await hub_svc.get_pack_categories(db)


@router.post("/packs", response_model=PackResponse, status_code=status.HTTP_201_CREATED)
async def create_pack(
    body: PackCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    sources = [s.model_dump() for s in body.sources] if body.sources else None
    return await hub_svc.create_pack(
        db,
        name=body.name,
        description=body.description,
        icon=body.icon,
        category=body.category,
        visibility=body.visibility,
        dependencies=body.dependencies,
        maintainer_team=body.maintainer_team,
        org_id=body.org_id,
        created_by=current.id,
        sources=sources,
    )


@router.get("/packs/{pack_id}", response_model=PackResponse)
async def get_pack(
    pack_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    pack = await hub_svc.get_pack(db, pack_id)
    if pack is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pack not found")
    return pack


@router.put("/packs/{pack_id}", response_model=PackResponse)
async def update_pack(
    pack_id: UUID,
    body: PackUpdate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    pack = await hub_svc.get_pack(db, pack_id)
    if pack is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pack not found")
    return await hub_svc.update_pack(
        db,
        pack,
        name=body.name,
        description=body.description,
        icon=body.icon,
        category=body.category,
        visibility=body.visibility,
        maintainer_team=body.maintainer_team,
    )


@router.delete("/packs/{pack_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pack(
    pack_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    pack = await hub_svc.get_pack(db, pack_id)
    if pack is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pack not found")
    await hub_svc.delete_pack(db, pack)


# ---------------------------------------------------------------------------
# Pack sources
# ---------------------------------------------------------------------------

@router.post(
    "/packs/{pack_id}/sources",
    response_model=PackSourceSchema,
    status_code=status.HTTP_201_CREATED,
)
async def add_pack_source(
    pack_id: UUID,
    body: PackSourceCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    pack = await hub_svc.get_pack(db, pack_id)
    if pack is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pack not found")
    return await hub_svc.add_source_to_pack(
        db, pack, type=body.type, name=body.name, url=body.url, config=body.config
    )


@router.delete(
    "/packs/{pack_id}/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_pack_source(
    pack_id: UUID,
    source_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    pack = await hub_svc.get_pack(db, pack_id)
    if pack is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pack not found")
    source = next((s for s in pack.sources if s.id == source_id), None)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    await hub_svc.remove_source_from_pack(db, pack, source)


# ---------------------------------------------------------------------------
# Install / uninstall packs for a project
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/installed-packs", response_model=list[InstalledPackResponse]
)
async def list_installed_packs(
    project_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list:
    return await hub_svc.list_installed_packs(db, project_id)


async def _background_clone_sources(project_id: UUID) -> None:
    """Clone all uncloned repo sources for a project in the background."""
    from app.services.github_service import clone_repo

    token = getattr(settings, "GITHUB_TOKEN", None)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ContextSource).where(
                ContextSource.project_id == project_id,
                ContextSource.type.in_(["github_repo", "gitlab_repo"]),
                ContextSource.last_indexed.is_(None),
            )
        )
        sources = result.scalars().all()

        for source in sources:
            if not source.url:
                continue
            clone_dir = Path(settings.REPO_CLONE_DIR) / str(project_id) / str(source.id)
            logger.info("Cloning source: %s (%s) → %s", source.name, source.url, clone_dir)
            try:
                await clone_repo(source.url, clone_dir, token=token)
                source.config = {
                    **(source.config or {}),
                    "clone_status": "done",
                    "clone_path": str(clone_dir),
                }
                source.last_indexed = datetime.now(timezone.utc)
                await db.commit()
                logger.info("Cloned %s successfully", source.name)
            except Exception as exc:
                logger.exception("Clone failed for %s", source.name)
                source.config = {
                    **(source.config or {}),
                    "clone_status": "error",
                    "clone_error": str(exc)[:500],
                }
                await db.commit()


@router.post(
    "/projects/{project_id}/installed-packs",
    response_model=InstalledPackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def install_pack_to_project(
    project_id: UUID,
    body: InstallPackRequest,
    background_tasks: BackgroundTasks,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    try:
        installed = await hub_svc.install_pack(
            db,
            project_id=project_id,
            pack_id=body.pack_id,
            auto_update=body.auto_update,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    background_tasks.add_task(_background_clone_sources, project_id)

    result = await hub_svc.list_installed_packs(db, project_id)
    return next(i for i in result if i.id == installed.id)


@router.delete(
    "/projects/{project_id}/installed-packs/{pack_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def uninstall_pack_from_project(
    project_id: UUID,
    pack_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await hub_svc.uninstall_pack(db, project_id=project_id, pack_id=pack_id)
