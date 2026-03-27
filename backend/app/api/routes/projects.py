import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, exists, func, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.organization import Organization, Team, TeamMember, TeamMemberRole
from app.models.project import Project
from app.models.session import Session as OrbitSession
from app.models.project_share import (
    ProjectShare,
    ProjectShareRole,
    ProjectShareSubject,
)
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

ProjectAccessMin = Literal["read", "write", "admin"]

_SHARE_ROLE_TIER: dict[ProjectShareRole, int] = {
    ProjectShareRole.view: 1,
    ProjectShareRole.edit: 2,
    ProjectShareRole.admin: 3,
}

_MIN_ACCESS_VALUE: dict[ProjectAccessMin, int] = {
    "read": 1,
    "write": 2,
    "admin": 3,
}


async def user_has_org_access(db: AsyncSession, user_id: UUID, org_id: UUID) -> bool:
    from app.core.config import settings
    if settings.ENVIRONMENT == "development":
        return True
    stmt = (
        select(TeamMember.id)
        .join(Team, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user_id, Team.org_id == org_id)
        .limit(1)
    )
    row = await db.execute(stmt)
    return row.scalar_one_or_none() is not None


async def user_is_org_team_admin(db: AsyncSession, user_id: UUID, org_id: UUID) -> bool:
    stmt = (
        select(TeamMember.id)
        .join(Team, TeamMember.team_id == Team.id)
        .where(
            TeamMember.user_id == user_id,
            Team.org_id == org_id,
            TeamMember.role == TeamMemberRole.admin,
        )
        .limit(1)
    )
    row = await db.execute(stmt)
    return row.scalar_one_or_none() is not None


async def _ensure_granter_has_admin_share(
    db: AsyncSession,
    granter_id: UUID,
    project: Project,
) -> None:
    if await user_is_org_team_admin(db, granter_id, project.org_id):
        return
    row = await db.execute(
        select(ProjectShare.id).where(
            ProjectShare.project_id == project.id,
            ProjectShare.user_id == granter_id,
        ).limit(1)
    )
    if row.scalar_one_or_none() is not None:
        return
    db.add(
        ProjectShare(
            id=uuid.uuid4(),
            project_id=project.id,
            subject_type=ProjectShareSubject.user,
            user_id=granter_id,
            group_name=None,
            role=ProjectShareRole.admin,
        )
    )


async def project_has_any_shares(db: AsyncSession, project_id: UUID) -> bool:
    n = await db.scalar(
        select(func.count())
        .select_from(ProjectShare)
        .where(ProjectShare.project_id == project_id)
    )
    return (n or 0) > 0


async def user_has_explicit_project_share(db: AsyncSession, user_id: UUID, project_id: UUID) -> bool:
    row = await db.execute(
        select(ProjectShare.id)
        .where(
            ProjectShare.project_id == project_id,
            ProjectShare.user_id == user_id,
        )
        .limit(1)
    )
    return row.scalar_one_or_none() is not None


async def user_project_access_tier(db: AsyncSession, user_id: UUID, project: Project) -> int:
    """Numeric tier: 1=read (view share), 2=write (edit share), 3=admin-level.

    Caller must have already verified organization membership and share rules
    in require_project_access.
    """
    if not await project_has_any_shares(db, project.id):
        return 3
    if await user_is_org_team_admin(db, user_id, project.org_id):
        return 3
    row = await db.execute(
        select(ProjectShare.role)
        .where(
            ProjectShare.project_id == project.id,
            ProjectShare.user_id == user_id,
        )
        .limit(1)
    )
    role = row.scalar_one_or_none()
    if role is None:
        return 1
    return _SHARE_ROLE_TIER[role]


async def user_can_mutate_global_skills(db: AsyncSession, user_id: UUID) -> bool:
    """Whether the user may change workspace-wide MCP skills (configure, enable, etc.).

    If the user can only open projects via *view* shares (and is not an org team
    admin on those orgs), they are read-only for shared work and must not change
    global skill state. Users with no listed projects may still manage skills.
    """
    stmt = _accessible_projects_query(user_id)
    result = await db.execute(stmt)
    projects = list(result.scalars().all())
    if not projects:
        return True

    for project in projects:
        if not await project_has_any_shares(db, project.id):
            return True
        if await user_is_org_team_admin(db, user_id, project.org_id):
            return True
        row = await db.execute(
            select(ProjectShare.role)
            .where(
                ProjectShare.project_id == project.id,
                ProjectShare.user_id == user_id,
            )
            .limit(1)
        )
        role = row.scalar_one_or_none()
        if role in (ProjectShareRole.edit, ProjectShareRole.admin):
            return True
    return False


async def can_manage_project_shares(
    db: AsyncSession, user_id: UUID, project: Project
) -> bool:
    if settings.ENVIRONMENT == "development":
        return True
    if not await user_has_org_access(db, user_id, project.org_id):
        return False
    if not await project_has_any_shares(db, project.id):
        return True
    if await user_is_org_team_admin(db, user_id, project.org_id):
        return True
    row = await db.execute(
        select(ProjectShare.id)
        .where(
            ProjectShare.project_id == project.id,
            ProjectShare.user_id == user_id,
            ProjectShare.role == ProjectShareRole.admin,
        )
        .limit(1)
    )
    return row.scalar_one_or_none() is not None


_AMBIGUOUS_USER_MSG = (
    "Multiple users match that identifier; use a full email address."
)


async def resolve_user_by_identifier(db: AsyncSession, identifier: str) -> User | None:
    ident = identifier.strip().lstrip("@")
    if not ident:
        return None
    q = ident.lower()

    def _unique_or_raise(rows: list[User], ambiguous_detail: str) -> User | None:
        if len(rows) == 1:
            return rows[0]
        if len(rows) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ambiguous_detail,
            )
        return None

    # Full address, case-insensitive (unique in DB)
    r = await db.execute(select(User).where(func.lower(User.email) == q))
    u = _unique_or_raise(list(r.scalars().all()), _AMBIGUOUS_USER_MSG)
    if u is not None:
        return u

    # Prefix match: "alice" -> alice@any.domain (must be unique)
    r = await db.execute(select(User).where(func.lower(User.email).like(f"{q}@%")))
    rows = list(r.scalars().all())
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_AMBIGUOUS_USER_MSG,
        )

    # Local part only: alice@corp vs alice@other — error if more than one
    r = await db.execute(
        select(User).where(func.lower(func.split_part(User.email, "@", 1)) == q)
    )
    u = _unique_or_raise(list(r.scalars().all()), _AMBIGUOUS_USER_MSG)
    if u is not None:
        return u

    r = await db.execute(select(User).where(func.lower(User.full_name) == q))
    return _unique_or_raise(
        list(r.scalars().all()),
        "Multiple users share that display name; use a full email address.",
    )


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


async def require_project_access(
    db: AsyncSession,
    user_id: UUID,
    project_id: UUID,
    *,
    min_access: ProjectAccessMin = "read",
) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if not await user_has_org_access(db, user_id, project.org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed for this organization",
        )
    if await project_has_any_shares(db, project.id):
        if await user_is_org_team_admin(db, user_id, project.org_id):
            pass
        elif await user_has_explicit_project_share(db, user_id, project.id):
            pass
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this project",
            )
    tier = await user_project_access_tier(db, user_id, project)
    if tier < _MIN_ACCESS_VALUE[min_access]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action on the project",
        )
    return project


async def require_orbit_session_in_project(
    db: AsyncSession,
    user_id: UUID,
    project_id: UUID,
    session_id: UUID,
    *,
    min_access: ProjectAccessMin = "read",
) -> OrbitSession:
    await require_project_access(db, user_id, project_id, min_access=min_access)
    result = await db.execute(select(OrbitSession).where(OrbitSession.id == session_id))
    orbit_session = result.scalar_one_or_none()
    if orbit_session is None or orbit_session.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return orbit_session


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
    session_count: int = 0
    current_user_access: Literal["read", "write", "admin"]


async def project_to_response(
    db: AsyncSession,
    user_id: UUID,
    project: Project,
    *,
    session_count: int | None = None,
) -> ProjectResponse:
    if session_count is None:
        n = await db.scalar(
            select(func.count())
            .select_from(OrbitSession)
            .where(OrbitSession.project_id == project.id),
        )
        session_count = int(n or 0)
    tier = await user_project_access_tier(db, user_id, project)
    access: Literal["read", "write", "admin"] = (
        "read" if tier == 1 else "write" if tier == 2 else "admin"
    )
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        org_id=project.org_id,
        default_ai_config=project.default_ai_config,
        created_at=project.created_at,
        updated_at=project.updated_at,
        session_count=session_count,
        current_user_access=access,
    )


def _session_count_scalar_subquery():
    return (
        select(func.coalesce(func.count(OrbitSession.id), 0))
        .where(OrbitSession.project_id == Project.id)
        .scalar_subquery()
    )


class ProjectShareResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_type: str
    role: str
    user_id: UUID | None
    group_name: str | None
    display_name: str


class ProjectShareCreate(BaseModel):
    subject_type: Literal["user", "group"]
    role: Literal["view", "edit", "admin"]
    user_identifier: str | None = None
    group_name: str | None = None


class ProjectSharePatch(BaseModel):
    role: Literal["view", "edit", "admin"]


def _share_to_response(share: ProjectShare, user: User | None) -> ProjectShareResponse:
    if share.subject_type == ProjectShareSubject.group:
        gn = share.group_name or ""
        display = f"@{gn}" if gn else "Group"
    else:
        display = user.email if user else (str(share.user_id) if share.user_id else "User")
    return ProjectShareResponse(
        id=share.id,
        subject_type=share.subject_type.value,
        role=share.role.value,
        user_id=share.user_id,
        group_name=share.group_name,
        display_name=display,
    )


def _accessible_projects_query(user_id: UUID) -> Select[tuple[Project]]:
    from app.core.config import settings
    if settings.ENVIRONMENT == "development":
        return select(Project).order_by(Project.created_at.desc())
    orgs_subq = (
        select(Team.org_id)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user_id)
        .distinct()
    )
    has_any_share = exists(
        select(1).where(ProjectShare.project_id == Project.id)
    )
    user_share = exists(
        select(1).where(
            ProjectShare.project_id == Project.id,
            ProjectShare.user_id == user_id,
        )
    )
    org_admin = exists(
        select(1)
        .select_from(TeamMember)
        .join(Team, TeamMember.team_id == Team.id)
        .where(
            Team.org_id == Project.org_id,
            TeamMember.user_id == user_id,
            TeamMember.role == TeamMemberRole.admin,
        )
    )
    return (
        select(Project)
        .where(
            Project.org_id.in_(orgs_subq),
            or_(not_(has_any_share), user_share, org_admin),
        )
        .order_by(Project.created_at.desc())
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> list[ProjectResponse]:
    stmt = (
        _accessible_projects_query(current.id)
        .add_columns(_session_count_scalar_subquery().label("session_count"))
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    out: list[ProjectResponse] = []
    for row in result.all():
        project = row[0]
        cnt = int(row[1])
        out.append(await project_to_response(db, current.id, project, session_count=cnt))
    return out


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
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
    return await project_to_response(db, current.id, project, session_count=0)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    project = await require_project_access(db, current.id, project_id)
    return await project_to_response(db, current.id, project)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    project = await require_project_access(db, current.id, project_id, min_access="write")
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.default_ai_config is not None:
        project.default_ai_config = body.default_ai_config
    await db.commit()
    await db.refresh(project)
    return await project_to_response(db, current.id, project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    project = await require_project_access(db, current.id, project_id, min_access="admin")

    await db.delete(project)
    await db.commit()

    repo_dir = Path(settings.REPO_CLONE_DIR) / str(project_id)
    if repo_dir.exists():
        try:
            shutil.rmtree(repo_dir)
            logger.info("Cleaned up cloned repos at %s", repo_dir)
        except Exception:
            logger.warning("Failed to clean up %s", repo_dir, exc_info=True)


@router.get(
    "/{project_id}/shares",
    response_model=list[ProjectShareResponse],
)
async def list_project_shares(
    project_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectShareResponse]:
    project = await require_project_access(db, current.id, project_id)
    result = await db.execute(
        select(ProjectShare)
        .where(ProjectShare.project_id == project.id)
        .order_by(ProjectShare.created_at)
    )
    shares = list(result.scalars().all())
    out: list[ProjectShareResponse] = []
    for sh in shares:
        u: User | None = None
        if sh.user_id:
            ur = await db.execute(select(User).where(User.id == sh.user_id))
            u = ur.scalar_one_or_none()
        out.append(_share_to_response(sh, u))
    return out


@router.post(
    "/{project_id}/shares",
    response_model=ProjectShareResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_share(
    project_id: UUID,
    body: ProjectShareCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectShareResponse:
    project = await require_project_access(db, current.id, project_id)
    if not await can_manage_project_shares(db, current.id, project):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to manage sharing for this project",
        )

    if body.subject_type == "user":
        if not body.user_identifier or not body.user_identifier.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_identifier is required for user shares",
            )
        target = await resolve_user_by_identifier(db, body.user_identifier)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found. They must sign in to Orbit at least once.",
            )
        if not await user_has_org_access(db, target.id, project.org_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User must belong to this project's organization before being granted access.",
            )
        share = ProjectShare(
            id=uuid.uuid4(),
            project_id=project.id,
            subject_type=ProjectShareSubject.user,
            user_id=target.id,
            group_name=None,
            role=ProjectShareRole(body.role),
        )
    else:
        if not body.group_name or not body.group_name.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="group_name is required for group shares",
            )
        share = ProjectShare(
            id=uuid.uuid4(),
            project_id=project.id,
            subject_type=ProjectShareSubject.group,
            user_id=None,
            group_name=body.group_name.strip(),
            role=ProjectShareRole(body.role),
        )

    db.add(share)
    await _ensure_granter_has_admin_share(db, current.id, project)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This subject is already granted access on this project",
        ) from None
    await db.refresh(share)
    u = None
    if share.user_id:
        ur = await db.execute(select(User).where(User.id == share.user_id))
        u = ur.scalar_one_or_none()
    return _share_to_response(share, u)


@router.patch(
    "/{project_id}/shares/{share_id}",
    response_model=ProjectShareResponse,
)
async def patch_project_share(
    project_id: UUID,
    share_id: UUID,
    body: ProjectSharePatch,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectShareResponse:
    project = await require_project_access(db, current.id, project_id)
    if not await can_manage_project_shares(db, current.id, project):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to manage sharing for this project",
        )
    result = await db.execute(
        select(ProjectShare).where(
            ProjectShare.id == share_id,
            ProjectShare.project_id == project.id,
        )
    )
    share = result.scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    share.role = ProjectShareRole(body.role)
    await db.commit()
    await db.refresh(share)
    u = None
    if share.user_id:
        ur = await db.execute(select(User).where(User.id == share.user_id))
        u = ur.scalar_one_or_none()
    return _share_to_response(share, u)


@router.delete(
    "/{project_id}/shares/{share_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_share(
    project_id: UUID,
    share_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    project = await require_project_access(db, current.id, project_id)
    if not await can_manage_project_shares(db, current.id, project):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to manage sharing for this project",
        )
    result = await db.execute(
        select(ProjectShare).where(
            ProjectShare.id == share_id,
            ProjectShare.project_id == project.id,
        )
    )
    share = result.scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    await db.delete(share)
    await db.commit()
