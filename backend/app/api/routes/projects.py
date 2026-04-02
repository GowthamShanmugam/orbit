import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, and_, exists, func, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.organization import Organization, Team, TeamMember, TeamMemberRole
from app.models.project import Project, ProjectVisibility
from app.models.session import Session as OrbitSession
from app.models.project_share import (
    ProjectShare,
    ProjectShareRole,
    ProjectShareSubject,
)
from app.models.user import User
from app.services import runtime_settings as rs

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
    if settings.ENVIRONMENT == "development" and settings.DEV_RELAX_PROJECT_ACCESS:
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
    in require_project_access (except public read, which skips that gate).
    """
    if project.visibility == ProjectVisibility.public:
        if project.created_by_id == user_id:
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
        if role is not None:
            return _SHARE_ROLE_TIER[role]
        # Non-owners: default to write (sessions, chat). View-only applies only when
        # they have an explicit ProjectShare with role view (handled above).
        return 2
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
        if project.visibility == ProjectVisibility.public:
            tier = await user_project_access_tier(db, user_id, project)
            if tier >= 2:
                return True
            continue
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
    if settings.ENVIRONMENT == "development" and settings.DEV_RELAX_PROJECT_ACCESS:
        return True
    if project.visibility == ProjectVisibility.public:
        return False
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
    from app.core.config import settings

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    if settings.ENVIRONMENT == "development" and settings.DEV_RELAX_PROJECT_ACCESS:
        tier = await user_project_access_tier(db, user_id, project)
        if tier < _MIN_ACCESS_VALUE[min_access]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action on the project",
            )
        return project

    if project.visibility == ProjectVisibility.public:
        if min_access == "read":
            return project
        tier = await user_project_access_tier(db, user_id, project)
        if tier < _MIN_ACCESS_VALUE[min_access]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action on the project",
            )
        return project

    in_org = await user_has_org_access(db, user_id, project.org_id)
    has_shares = await project_has_any_shares(db, project.id)
    explicit_share = await user_has_explicit_project_share(db, user_id, project.id)
    is_org_admin = await user_is_org_team_admin(db, user_id, project.org_id)

    if not in_org:
        if has_shares and explicit_share:
            pass
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed for this organization",
            )
    elif has_shares:
        if not (is_org_admin or explicit_share):
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
    visibility: Literal["private", "public"] = "private"
    private_to_creator: bool = Field(
        default=False,
        description="If true, restrict visibility to org admins and explicit shares only.",
    )


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
    created_by_id: UUID | None = None
    """User who created the project; null for rows created before this field existed."""

    shared_with_me: bool = False
    """True when the project was created by someone else (explicit share / team visibility)."""

    created_by_display: str | None = None
    """Best label for the owner when `shared_with_me` (name or email)."""

    workspace_type: Literal["personal", "organization"] = "personal"
    """Personal workspace vs a team/organization workspace."""

    organization_name: str | None = None
    """Organization display name when `workspace_type` is organization."""

    visibility: Literal["private", "public"] = "private"
    """Private projects use sharing; public projects are readable by all signed-in users."""


class ProjectRuntimeSettingsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    values: dict[str, int | float]
    """Effective values for chats in this project (project layer on top of server global)."""

    global_values: dict[str, int | float]
    """Server-wide effective values (same idea as GET /settings/runtime)."""

    project_overrides: dict[str, int | float]
    """Keys this project overrides; omit or clear in PUT with null to use global for that key."""

    env_defaults: dict[str, int | float]
    """Environment defaults from server config (before any DB overrides)."""

    project_override_keys: list[str]
    allow_write: bool


def _creator_display_label(user: User | None) -> str | None:
    if user is None:
        return None
    if user.full_name and str(user.full_name).strip():
        return str(user.full_name).strip()
    return user.email


def _workspace_public_fields(
    project: Project,
    *,
    personal_org_id: UUID,
    org_display_name: str | None,
) -> tuple[Literal["personal", "organization"], str | None]:
    if project.org_id == personal_org_id:
        return "personal", None
    return "organization", org_display_name


async def project_to_response(
    db: AsyncSession,
    user_id: UUID,
    project: Project,
    *,
    session_count: int | None = None,
    creator: User | None = None,
    personal_org_id: UUID | None = None,
    org_display_name: str | None = None,
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
    if creator is None and project.created_by_id is not None:
        ur = await db.execute(select(User).where(User.id == project.created_by_id))
        creator = ur.scalar_one_or_none()
    explicit_share = await user_has_explicit_project_share(db, user_id, project.id)
    shared = explicit_share and (
        project.created_by_id is None or project.created_by_id != user_id
    )
    owner_label = _creator_display_label(creator) if shared else None
    if personal_org_id is None:
        ur = await db.execute(select(User).where(User.id == user_id))
        u = ur.scalar_one_or_none()
        if u is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User not found",
            )
        personal_org_id = await get_or_create_personal_org(db, u)
    if org_display_name is None:
        orow = await db.execute(
            select(Organization.name).where(Organization.id == project.org_id)
        )
        raw_name = orow.scalar_one_or_none()
        org_display_name = str(raw_name) if raw_name is not None else None
    wt, org_name = _workspace_public_fields(
        project,
        personal_org_id=personal_org_id,
        org_display_name=org_display_name,
    )
    vis: Literal["private", "public"] = (
        "public" if project.visibility == ProjectVisibility.public else "private"
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
        created_by_id=project.created_by_id,
        shared_with_me=shared,
        created_by_display=owner_label,
        workspace_type=wt,
        organization_name=org_name,
        visibility=vis,
    )


async def _project_to_response_for_user(
    db: AsyncSession,
    current: User,
    project: Project,
    *,
    session_count: int | None = None,
    creator: User | None = None,
) -> ProjectResponse:
    personal_org_id = await get_or_create_personal_org(db, current)
    org_row = await db.execute(
        select(Organization.name).where(Organization.id == project.org_id)
    )
    od = org_row.scalar_one_or_none()
    return await project_to_response(
        db,
        current.id,
        project,
        session_count=session_count,
        creator=creator,
        personal_org_id=personal_org_id,
        org_display_name=str(od) if od is not None else None,
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


class ShareableUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str | None


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

    if settings.ENVIRONMENT == "development" and settings.DEV_RELAX_PROJECT_ACCESS:
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
    in_org_visible = and_(
        Project.org_id.in_(orgs_subq),
        or_(not_(has_any_share), user_share, org_admin),
    )
    is_public = Project.visibility == ProjectVisibility.public
    return (
        select(Project)
        .where(or_(in_org_visible, user_share, is_public))
        .order_by(Project.created_at.desc())
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(0, ge=0),
    limit: int = Query(
        default=settings.API_PAGE_DEFAULT,
        ge=1,
        le=settings.API_PAGE_MAX,
    ),
) -> list[ProjectResponse]:
    stmt = (
        _accessible_projects_query(current.id)
        .add_columns(_session_count_scalar_subquery().label("session_count"))
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()
    personal_org_id = await get_or_create_personal_org(db, current)
    creator_ids = {row[0].created_by_id for row in rows if row[0].created_by_id}
    creators: dict[UUID, User] = {}
    if creator_ids:
        ur = await db.execute(select(User).where(User.id.in_(creator_ids)))
        for u in ur.scalars().all():
            creators[u.id] = u
    org_ids = {row[0].org_id for row in rows}
    org_names: dict[UUID, str] = {}
    if org_ids:
        org_res = await db.execute(
            select(Organization).where(Organization.id.in_(org_ids))
        )
        for o in org_res.scalars().all():
            org_names[o.id] = o.name
    out: list[ProjectResponse] = []
    for row in rows:
        project = row[0]
        cnt = int(row[1])
        cr = creators.get(project.created_by_id) if project.created_by_id else None
        od = org_names.get(project.org_id)
        out.append(
            await project_to_response(
                db,
                current.id,
                project,
                session_count=cnt,
                creator=cr,
                personal_org_id=personal_org_id,
                org_display_name=od,
            )
        )
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
        visibility=ProjectVisibility(body.visibility),
        default_ai_config=body.default_ai_config,
        created_by_id=current.id,
    )
    db.add(project)
    await db.flush()
    if body.private_to_creator:
        db.add(
            ProjectShare(
                id=uuid.uuid4(),
                project_id=project.id,
                subject_type=ProjectShareSubject.user,
                user_id=current.id,
                group_name=None,
                role=ProjectShareRole.admin,
            )
        )
    await db.commit()
    await db.refresh(project)
    return await _project_to_response_for_user(db, current, project, session_count=0)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    project = await require_project_access(db, current.id, project_id)
    return await _project_to_response_for_user(db, current, project)


@router.get("/{project_id}/runtime-settings", response_model=ProjectRuntimeSettingsResponse)
async def get_project_runtime_settings(
    project_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectRuntimeSettingsResponse:
    project = await require_project_access(db, current.id, project_id)
    merged = await rs.merged_runtime_for_project(db, project_id)
    proj_over, keys = rs.project_layer_snapshot(project)
    tier = await user_project_access_tier(db, current.id, project)
    allow_write = settings.RUNTIME_SETTINGS_ALLOW_WRITE and tier >= _MIN_ACCESS_VALUE["write"]
    return ProjectRuntimeSettingsResponse(
        values=merged,
        global_values=rs.effective_values_snapshot(),
        project_overrides=proj_over,
        env_defaults=rs.env_defaults_snapshot(),
        project_override_keys=keys,
        allow_write=allow_write,
    )


@router.put("/{project_id}/runtime-settings", response_model=ProjectRuntimeSettingsResponse)
async def put_project_runtime_settings(
    project_id: UUID,
    body: rs.RuntimeSettingsUpdate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectRuntimeSettingsResponse:
    if not settings.RUNTIME_SETTINGS_ALLOW_WRITE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Runtime settings writes are disabled (RUNTIME_SETTINGS_ALLOW_WRITE=false)",
        )
    project = await require_project_access(db, current.id, project_id, min_access="write")
    await rs.apply_project_runtime_updates(db, project_id, body)
    await db.refresh(project)
    merged = await rs.merged_runtime_for_project(db, project_id)
    proj_over, keys = rs.project_layer_snapshot(project)
    tier = await user_project_access_tier(db, current.id, project)
    allow_write = settings.RUNTIME_SETTINGS_ALLOW_WRITE and tier >= _MIN_ACCESS_VALUE["write"]
    return ProjectRuntimeSettingsResponse(
        values=merged,
        global_values=rs.effective_values_snapshot(),
        project_overrides=proj_over,
        env_defaults=rs.env_defaults_snapshot(),
        project_override_keys=keys,
        allow_write=allow_write,
    )


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
    return await _project_to_response_for_user(db, current, project)


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
    "/{project_id}/shareable-users",
    response_model=list[ShareableUserResponse],
)
async def list_shareable_users(
    project_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ShareableUserResponse]:
    """Users in this project's organization (other than you) who can receive shares."""
    project = await require_project_access(db, current.id, project_id)
    if project.visibility == ProjectVisibility.public:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Public projects do not use sharing",
        )
    if not await can_manage_project_shares(db, current.id, project):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to manage sharing for this project",
        )
    user_ids_subq = (
        select(TeamMember.user_id)
        .join(Team, TeamMember.team_id == Team.id)
        .where(
            Team.org_id == project.org_id,
            TeamMember.user_id != current.id,
        )
        .distinct()
    )
    stmt = select(User).where(User.id.in_(user_ids_subq)).order_by(User.email.asc())
    result = await db.execute(stmt)
    users = list(result.scalars().all())
    return [
        ShareableUserResponse(id=u.id, email=u.email, full_name=u.full_name)
        for u in users
    ]


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
    if project.visibility == ProjectVisibility.public:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Public projects do not use sharing",
        )
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
    if project.visibility == ProjectVisibility.public:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Public projects do not use sharing",
        )
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
    if project.visibility == ProjectVisibility.public:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Public projects do not use sharing",
        )
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
