"""Cluster management API routes — CRUD and connection testing.

Live cluster queries (resources, logs, tests) are handled by the AI via
tool-use in the chat loop, not through REST endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.projects import require_project_access
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.cluster import (
    ClusterAuthMethod,
    ClusterRole,
    ClusterStatus,
)
from app.models.user import User
from app.services import cluster_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ClusterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    role: ClusterRole
    auth_method: ClusterAuthMethod
    credentials: dict[str, Any]
    api_server_url: str | None = None
    namespace_filter: list[str] | None = None
    sync_config: dict[str, Any] | None = None


class ClusterUpdate(BaseModel):
    """Partial update: only fields present in the JSON body are applied."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    namespace_filter: list[str] | None = None
    sync_config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None
    api_server_url: str | None = None


class ClusterResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    role: ClusterRole
    auth_method: ClusterAuthMethod
    api_server_url: str | None
    namespace_filter: list[str] | None
    status: ClusterStatus
    status_message: str | None
    last_synced: datetime | None
    sync_config: dict[str, Any] | None
    config: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


def _cluster_resp(c) -> ClusterResponse:
    return ClusterResponse(
        id=c.id,
        project_id=c.project_id,
        name=c.name,
        role=c.role,
        auth_method=c.auth_method,
        api_server_url=c.api_server_url,
        namespace_filter=c.namespace_filter,
        status=c.status,
        status_message=c.status_message,
        last_synced=c.last_synced,
        sync_config=c.sync_config,
        config=c.config,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/clusters", response_model=list[ClusterResponse])
async def list_clusters(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
    role: ClusterRole | None = Query(None),
):
    await require_project_access(db, current.id, project_id)
    clusters = await cluster_service.list_clusters(db, project_id, role=role)
    return [_cluster_resp(c) for c in clusters]


@router.post(
    "/projects/{project_id}/clusters",
    response_model=ClusterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_cluster(
    project_id: UUID,
    body: ClusterCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id, min_access="write")
    cluster = await cluster_service.create_cluster(
        db,
        project_id,
        name=body.name,
        role=body.role,
        auth_method=body.auth_method,
        credentials=body.credentials,
        api_server_url=body.api_server_url,
        namespace_filter=body.namespace_filter,
        sync_config=body.sync_config,
    )

    ok, message = await cluster_service.test_connection(cluster)
    new_status = ClusterStatus.connected if ok else ClusterStatus.error
    await cluster_service.update_status(db, cluster, new_status, message)

    return _cluster_resp(cluster)


@router.get(
    "/projects/{project_id}/clusters/{cluster_id}",
    response_model=ClusterResponse,
)
async def get_cluster(
    project_id: UUID,
    cluster_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id)
    cluster = await cluster_service.get_cluster(db, project_id, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return _cluster_resp(cluster)


@router.put(
    "/projects/{project_id}/clusters/{cluster_id}",
    response_model=ClusterResponse,
)
async def update_cluster(
    project_id: UUID,
    cluster_id: UUID,
    body: ClusterUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id, min_access="write")
    cluster = await cluster_service.get_cluster(db, project_id, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    patch = body.model_dump(exclude_unset=True)
    try:
        updated = await cluster_service.update_cluster(db, cluster, **patch)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if "credentials" in patch or "api_server_url" in patch:
        ok, message = await cluster_service.test_connection(updated)
        new_status = ClusterStatus.connected if ok else ClusterStatus.error
        await cluster_service.update_status(db, updated, new_status, message)
        await db.refresh(updated)
    return _cluster_resp(updated)


@router.delete(
    "/projects/{project_id}/clusters/{cluster_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_cluster(
    project_id: UUID,
    cluster_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id, min_access="write")
    cluster = await cluster_service.get_cluster(db, project_id, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    await cluster_service.delete_cluster(db, cluster)


@router.post(
    "/projects/{project_id}/clusters/{cluster_id}/test-connection",
)
async def test_connection(
    project_id: UUID,
    cluster_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id, min_access="write")
    cluster = await cluster_service.get_cluster(db, project_id, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    ok, message = await cluster_service.test_connection(cluster)
    if ok:
        await cluster_service.update_status(db, cluster, ClusterStatus.connected, message)
    else:
        await cluster_service.update_status(db, cluster, ClusterStatus.error, message)

    return {"connected": ok, "message": message}
