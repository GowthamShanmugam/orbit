from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.organization import Organization, Team, TeamMember, TeamMemberRole
from app.models.project import Project
from app.models.user import User

router = APIRouter()


async def user_has_org_access(db: AsyncSession, user_id: UUID, org_id: UUID) -> bool:
    stmt = (
        select(TeamMember.id)
        .join(Team, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user_id, Team.org_id == org_id)
        .limit(1)
    )
    row = await db.execute(stmt)
    return row.scalar_one_or_none() is not None


async def get_or_create_personal_org(db: AsyncSession, user: User) -> UUID:
    """Return the user's personal org, creating one if it doesn't exist."""
    slug = f"personal-{user.id}"
    result = await db.execute(
        select(Organization).where(Organization.slug == slug)
    )
    org = result.scalar_one_or_none()
    if org is not None:
        return org.id

    org = Organization(name=f"{user.email}'s workspace", slug=slug)
    db.add(org)
    await db.flush()

    team = Team(name="default", org_id=org.id)
    db.add(team)
    await db.flush()

    db.add(TeamMember(team_id=team.id, user_id=user.id, role=TeamMemberRole.admin))
    await db.flush()

    return org.id


async def require_project_access(db: AsyncSession, user_id: UUID, project_id: UUID) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if not await user_has_org_access(db, user_id, project.org_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed for this organization")
    return project


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    org_id: UUID | None = None
    default_ai_config: dict[str, Any] | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    default_ai_config: dict[str, Any] | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    org_id: UUID
    default_ai_config: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


def _accessible_projects_query(user_id: UUID) -> Select[tuple[Project]]:
    orgs = (
        select(Team.org_id)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user_id)
        .distinct()
    )
    return select(Project).where(Project.org_id.in_(orgs)).order_by(Project.created_at.desc())


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> list[Project]:
    stmt = _accessible_projects_query(current.id).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Project:
    org_id = body.org_id or await get_or_create_personal_org(db, current)
    if not await user_has_org_access(db, current.id, org_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed for this organization")
    project = Project(
        name=body.name,
        description=body.description,
        org_id=org_id,
        default_ai_config=body.default_ai_config,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Project:
    return await require_project_access(db, current.id, project_id)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Project:
    project = await require_project_access(db, current.id, project_id)
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.default_ai_config is not None:
        project.default_ai_config = body.default_ai_config
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    project = await require_project_access(db, current.id, project_id)
    await db.delete(project)
    await db.commit()
