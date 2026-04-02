"""Organizations the current user belongs to (for project workspace selection)."""

from __future__ import annotations

import re
import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.organization import Organization, Team, TeamMember, TeamMemberRole
from app.models.user import User

router = APIRouter()


def _slugify_org_name(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")[:200]
    return s or "org"


class OrganizationSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    is_personal: bool


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(
        default=None,
        max_length=255,
        description="URL-safe id; generated from name if omitted.",
    )


async def _create_organization(
    body: OrganizationCreate,
    current: User,
    db: AsyncSession,
) -> OrganizationSummaryResponse:
    """Create a team organization and add the current user as admin on the default team."""
    base = _slugify_org_name((body.slug or body.name).strip())
    slug = base
    for _ in range(24):
        existing = await db.execute(
            select(Organization.id).where(Organization.slug == slug).limit(1)
        )
        if existing.scalar_one_or_none() is None:
            break
        slug = f"{base}-{uuid.uuid4().hex[:8]}"
    else:
        slug = f"org-{uuid.uuid4().hex[:12]}"

    org = Organization(name=body.name.strip(), slug=slug)
    db.add(org)
    await db.flush()
    team = Team(name="default", org_id=org.id)
    db.add(team)
    await db.flush()
    db.add(
        TeamMember(
            team_id=team.id,
            user_id=current.id,
            role=TeamMemberRole.admin,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not create organization; try a different name.",
        ) from None
    await db.refresh(org)
    personal_slug = f"personal-{current.id}"
    return OrganizationSummaryResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        is_personal=(org.slug == personal_slug),
    )


@router.post(
    "/organizations/create",
    response_model=OrganizationSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization_create(
    body: OrganizationCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationSummaryResponse:
    """Preferred create URL (avoids proxies that only allow GET on `/organizations`)."""
    return await _create_organization(body, current, db)


@router.post(
    "/organizations",
    response_model=OrganizationSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization(
    body: OrganizationCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationSummaryResponse:
    """Create team org (alias of POST `/organizations/create`)."""
    return await _create_organization(body, current, db)


@router.get("/organizations", response_model=list[OrganizationSummaryResponse])
async def list_my_organizations(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[OrganizationSummaryResponse]:
    """Organizations where the user has team membership (for creating projects)."""
    from app.api.routes.projects import get_or_create_personal_org

    await get_or_create_personal_org(db, current)
    await db.commit()

    personal_slug = f"personal-{current.id}"
    org_ids_subq = (
        select(Team.org_id)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == current.id)
        .distinct()
    )
    stmt = (
        select(Organization)
        .where(Organization.id.in_(org_ids_subq))
        .order_by(Organization.name.asc())
    )
    result = await db.execute(stmt)
    orgs = list(result.scalars().all())
    return [
        OrganizationSummaryResponse(
            id=o.id,
            name=o.name,
            slug=o.slug,
            is_personal=(o.slug == personal_slug),
        )
        for o in orgs
    ]
