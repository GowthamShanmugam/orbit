"""Secret Vault API routes — CRUD, scanning, and audit log."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.projects import require_project_access
from app.core.config import settings
from app.core.database import get_db
from app.core.secret_scanner import ScanMatch, is_sensitive_file, scan_text
from app.core.secret_vault import make_placeholder
from app.core.security import get_current_user
from app.models.secret import SecretScope
from app.models.user import User
from app.services import secret_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class SecretCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    value: str = Field(min_length=1)
    scope: SecretScope = SecretScope.project
    description: str | None = None


class SecretUpdate(BaseModel):
    value: str = Field(min_length=1)


class SecretResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    scope: SecretScope
    placeholder: str
    vault_backend: str
    description: str | None
    created_by: UUID | None
    last_rotated: datetime | None
    created_at: datetime
    updated_at: datetime


class AuditLogResponse(BaseModel):
    id: UUID
    secret_id: UUID
    user_id: UUID | None
    action: str
    details: str | None
    created_at: datetime


class ScanRequest(BaseModel):
    text: str


class ScanMatchResponse(BaseModel):
    pattern_name: str
    matched_text: str
    start: int
    end: int
    severity: str
    suggestion: str


class ScanResponse(BaseModel):
    matches: list[ScanMatchResponse]
    has_secrets: bool


class FileCheckRequest(BaseModel):
    paths: list[str]


class FileCheckResponse(BaseModel):
    sensitive: list[str]
    safe: list[str]


def _to_response(secret) -> SecretResponse:
    return SecretResponse(
        id=secret.id,
        project_id=secret.project_id,
        name=secret.name,
        scope=secret.scope,
        placeholder=make_placeholder(secret.name),
        vault_backend=secret.vault_backend.value,
        description=secret.description,
        created_by=secret.created_by,
        last_rotated=secret.last_rotated,
        created_at=secret.created_at,
        updated_at=secret.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/secrets", response_model=list[SecretResponse])
async def list_secrets(
    project_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(0, ge=0),
    limit: int = Query(
        default=settings.API_PAGE_LARGE_DEFAULT,
        ge=1,
        le=settings.API_PAGE_LARGE_MAX,
    ),
) -> list[SecretResponse]:
    await require_project_access(db, current.id, project_id)
    secrets = await secret_service.list_secrets(db, project_id, skip=skip, limit=limit)
    return [_to_response(s) for s in secrets]


@router.post(
    "/projects/{project_id}/secrets",
    response_model=SecretResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_secret(
    project_id: UUID,
    body: SecretCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SecretResponse:
    await require_project_access(db, current.id, project_id, min_access="write")
    secret = await secret_service.create_secret(
        db,
        project_id=project_id,
        name=body.name,
        value=body.value,
        scope=body.scope,
        description=body.description,
        created_by=current.id,
    )
    return _to_response(secret)


@router.put("/projects/{project_id}/secrets/{secret_id}", response_model=SecretResponse)
async def rotate_secret(
    project_id: UUID,
    secret_id: UUID,
    body: SecretUpdate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SecretResponse:
    await require_project_access(db, current.id, project_id, min_access="write")
    secret = await secret_service.get_secret(db, secret_id)
    if secret is None or secret.project_id != project_id:
        raise HTTPException(status_code=404, detail="Secret not found")
    updated = await secret_service.update_secret_value(db, secret, body.value, user_id=current.id)
    return _to_response(updated)


@router.delete(
    "/projects/{project_id}/secrets/{secret_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_secret(
    project_id: UUID,
    secret_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await require_project_access(db, current.id, project_id, min_access="write")
    secret = await secret_service.get_secret(db, secret_id)
    if secret is None or secret.project_id != project_id:
        raise HTTPException(status_code=404, detail="Secret not found")
    await secret_service.delete_secret(db, secret, user_id=current.id)


@router.get(
    "/projects/{project_id}/secrets/{secret_id}/audit",
    response_model=list[AuditLogResponse],
)
async def get_audit_log(
    project_id: UUID,
    secret_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(0, ge=0),
    limit: int = Query(
        default=settings.API_PAGE_DEFAULT,
        ge=1,
        le=settings.API_PAGE_MAX,
    ),
) -> list[AuditLogResponse]:
    await require_project_access(db, current.id, project_id)
    secret = await secret_service.get_secret(db, secret_id)
    if secret is None or secret.project_id != project_id:
        raise HTTPException(status_code=404, detail="Secret not found")
    logs = await secret_service.get_audit_log(db, secret_id, skip=skip, limit=limit)
    return [
        AuditLogResponse(
            id=l.id,
            secret_id=l.secret_id,
            user_id=l.user_id,
            action=l.action,
            details=l.details,
            created_at=l.created_at,
        )
        for l in logs
    ]


@router.post("/scan-secrets", response_model=ScanResponse)
async def scan_secrets(
    body: ScanRequest,
    _current: Annotated[User, Depends(get_current_user)],
) -> ScanResponse:
    matches = scan_text(body.text)
    return ScanResponse(
        matches=[
            ScanMatchResponse(
                pattern_name=m.pattern_name,
                matched_text=m.matched_text,
                start=m.start,
                end=m.end,
                severity=m.severity,
                suggestion=m.suggestion,
            )
            for m in matches
        ],
        has_secrets=len(matches) > 0,
    )


@router.post("/check-sensitive-files", response_model=FileCheckResponse)
async def check_sensitive_files(
    body: FileCheckRequest,
    _current: Annotated[User, Depends(get_current_user)],
) -> FileCheckResponse:
    sensitive: list[str] = []
    safe: list[str] = []
    for p in body.paths:
        if is_sensitive_file(p):
            sensitive.append(p)
        else:
            safe.append(p)
    return FileCheckResponse(sensitive=sensitive, safe=safe)
