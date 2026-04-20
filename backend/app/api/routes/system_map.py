"""System Map API routes — deployment discovery, mapping CRUD, and debug sessions."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.projects import require_project_access
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.context import SessionLayer, SessionLayerType
from app.models.session import Session
from app.models.user import User
from app.services import kube_client, system_map_service
from app.services.cluster_service import get_cluster

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class OwnerReference(BaseModel):
    api_version: str = ""
    kind: str = ""
    name: str = ""
    uid: str = ""


class DeploymentInfo(BaseModel):
    name: str
    namespace: str
    image: str
    replicas: int
    ready_replicas: int
    status: str
    cluster_id: str
    cluster_name: str
    uid: str = ""
    owner_references: list[OwnerReference] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)


class MappingCreate(BaseModel):
    cluster_id: str
    deployment_name: str
    deployment_namespace: str = "default"
    context_source_id: str | None = None
    is_infrastructure: bool = False
    node_position_x: float = 0.0
    node_position_y: float = 0.0


class MappingUpdate(BaseModel):
    context_source_id: str | None = None
    is_infrastructure: bool | None = None
    node_position_x: float | None = None
    node_position_y: float | None = None


class MappingResponse(BaseModel):
    id: UUID
    project_id: UUID
    cluster_id: UUID
    deployment_name: str
    deployment_namespace: str
    context_source_id: UUID | None
    is_infrastructure: bool
    node_position_x: float
    node_position_y: float
    context_source_name: str | None = None
    context_source_url: str | None = None
    created_at: datetime
    updated_at: datetime


class BulkMappingsCreate(BaseModel):
    mappings: list[MappingCreate]


class EdgeCreate(BaseModel):
    source_mapping_id: str
    target_mapping_id: str
    label: str | None = None


class EdgeResponse(BaseModel):
    id: UUID
    project_id: UUID
    source_mapping_id: UUID
    target_mapping_id: UUID
    label: str | None
    created_at: datetime


class PositionUpdate(BaseModel):
    id: str
    x: float
    y: float


class BulkPositionsUpdate(BaseModel):
    positions: list[PositionUpdate]


class SuggestionItem(BaseModel):
    deployment_name: str
    deployment_namespace: str
    context_source_id: str | None = None
    cluster_id: str | None = None
    is_infrastructure: bool = False
    confidence: str = "low"
    reason: str = ""


def _mapping_resp(m) -> MappingResponse:
    cs = m.context_source
    return MappingResponse(
        id=m.id,
        project_id=m.project_id,
        cluster_id=m.cluster_id,
        deployment_name=m.deployment_name,
        deployment_namespace=m.deployment_namespace,
        context_source_id=m.context_source_id,
        is_infrastructure=m.is_infrastructure,
        node_position_x=m.node_position_x,
        node_position_y=m.node_position_y,
        context_source_name=cs.name if cs else None,
        context_source_url=cs.url if cs else None,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _edge_resp(e) -> EdgeResponse:
    return EdgeResponse(
        id=e.id,
        project_id=e.project_id,
        source_mapping_id=e.source_mapping_id,
        target_mapping_id=e.target_mapping_id,
        label=e.label,
        created_at=e.created_at,
    )


# ---------------------------------------------------------------------------
# Deployments (live from cluster)
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/system-map/deployments",
    response_model=list[DeploymentInfo],
)
async def get_deployments(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id)
    return await system_map_service.get_live_deployments(db, project_id)


# ---------------------------------------------------------------------------
# AI mapping suggestions
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/system-map/suggest",
    response_model=list[SuggestionItem],
)
async def suggest_mappings(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id)
    return await system_map_service.suggest_mappings(db, project_id)


# ---------------------------------------------------------------------------
# Mapping CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/system-map/mappings",
    response_model=list[MappingResponse],
)
async def list_mappings(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id)
    mappings = await system_map_service.list_mappings(db, project_id)
    return [_mapping_resp(m) for m in mappings]


@router.post(
    "/projects/{project_id}/system-map/mappings",
    response_model=list[MappingResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_mappings(
    project_id: UUID,
    body: BulkMappingsCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id, min_access="write")
    await system_map_service.delete_all_mappings(db, project_id)
    items = [m.model_dump() for m in body.mappings]
    mappings = await system_map_service.bulk_create_mappings(db, project_id, items)
    # Reload with relationships
    loaded = await system_map_service.list_mappings(db, project_id)
    created_ids = {m.id for m in mappings}
    return [_mapping_resp(m) for m in loaded if m.id in created_ids]


@router.put(
    "/projects/{project_id}/system-map/mappings/{mapping_id}",
    response_model=MappingResponse,
)
async def update_mapping(
    project_id: UUID,
    mapping_id: UUID,
    body: MappingUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id, min_access="write")
    mapping = await system_map_service.get_mapping(db, project_id, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    patch = body.model_dump(exclude_unset=True)
    if "context_source_id" in patch and patch["context_source_id"]:
        patch["context_source_id"] = UUID(patch["context_source_id"])
    updated = await system_map_service.update_mapping(db, mapping, **patch)
    # Reload with relationship
    loaded = await system_map_service.get_mapping(db, project_id, mapping_id)
    return _mapping_resp(loaded or updated)


@router.delete(
    "/projects/{project_id}/system-map/mappings/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_mapping(
    project_id: UUID,
    mapping_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id, min_access="write")
    mapping = await system_map_service.get_mapping(db, project_id, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    await system_map_service.delete_mapping(db, mapping)


@router.delete(
    "/projects/{project_id}/system-map",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_system_map(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    """Delete all mappings and edges for a project (reset the system map)."""
    await require_project_access(db, current.id, project_id, min_access="write")
    await system_map_service.delete_all_mappings(db, project_id)


# ---------------------------------------------------------------------------
# Positions (bulk save on drag)
# ---------------------------------------------------------------------------


@router.put("/projects/{project_id}/system-map/positions", status_code=status.HTTP_204_NO_CONTENT)
async def save_positions(
    project_id: UUID,
    body: BulkPositionsUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id, min_access="write")
    await system_map_service.bulk_update_positions(
        db, project_id, [p.model_dump() for p in body.positions]
    )


# ---------------------------------------------------------------------------
# Status (live health + version gap)
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/system-map/status")
async def get_status(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id)
    return await system_map_service.compute_status_for_mappings(db, project_id)


# ---------------------------------------------------------------------------
# Hierarchy (K8s-native parent-child edges)
# ---------------------------------------------------------------------------


class HierarchyEdge(BaseModel):
    parent_name: str
    parent_namespace: str
    child_name: str
    child_namespace: str
    relationship: str  # "direct" or "indirect"
    label: str


@router.get(
    "/projects/{project_id}/system-map/hierarchy",
    response_model=list[HierarchyEdge],
)
async def get_hierarchy(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    """Compute deployment-to-deployment hierarchy from K8s ownerRefs and labels."""
    await require_project_access(db, current.id, project_id)
    return await system_map_service.compute_hierarchy_edges(db, project_id)


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/system-map/edges",
    response_model=list[EdgeResponse],
)
async def list_edges(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id)
    edges = await system_map_service.list_edges(db, project_id)
    return [_edge_resp(e) for e in edges]


@router.post(
    "/projects/{project_id}/system-map/edges",
    response_model=EdgeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_edge(
    project_id: UUID,
    body: EdgeCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id, min_access="write")
    edge = await system_map_service.create_edge(
        db,
        project_id,
        source_mapping_id=UUID(body.source_mapping_id),
        target_mapping_id=UUID(body.target_mapping_id),
        label=body.label,
    )
    return _edge_resp(edge)


@router.delete(
    "/projects/{project_id}/system-map/edges/{edge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_edge(
    project_id: UUID,
    edge_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    await require_project_access(db, current.id, project_id, min_access="write")
    deleted = await system_map_service.delete_edge(db, project_id, edge_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Edge not found")


# ---------------------------------------------------------------------------
# Service detail (events, pods, logs)
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/system-map/mappings/{mapping_id}/detail")
async def get_service_detail(
    project_id: UUID,
    mapping_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    """Fetch live pod events and log tail for a mapped service."""
    await require_project_access(db, current.id, project_id)
    mapping = await system_map_service.get_mapping(db, project_id, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    cluster = await get_cluster(db, project_id, mapping.cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    events: list[dict[str, Any]] = []
    log_lines: str = ""
    pods: list[dict[str, Any]] = []

    try:
        raw_events = await kube_client.get_events(
            cluster, namespace=mapping.deployment_namespace, limit=50,
        )
        dep_name = mapping.deployment_name
        for e in raw_events.get("items", []):
            obj = e.get("involvedObject", {})
            obj_name = obj.get("name", "")
            if dep_name in obj_name:
                events.append({
                    "type": e.get("type"),
                    "reason": e.get("reason"),
                    "message": (e.get("message") or "")[:300],
                    "object": f"{obj.get('kind', '')}/{obj_name}",
                    "count": e.get("count"),
                    "last_seen": e.get("lastTimestamp"),
                })
        events = events[-15:]
    except Exception:
        logger.debug("Failed to fetch events for %s", mapping.deployment_name)

    try:
        pod_data = await kube_client.get_resources(
            cluster, "pods", namespace=mapping.deployment_namespace,
        )
        dep_name = mapping.deployment_name
        for p in pod_data.get("items", []):
            pod_name = p.get("metadata", {}).get("name", "")
            if dep_name in pod_name:
                phase = p.get("status", {}).get("phase", "Unknown")
                containers = p.get("status", {}).get("containerStatuses", [])
                restarts = sum(c.get("restartCount", 0) for c in containers)
                ready = sum(1 for c in containers if c.get("ready"))
                pods.append({
                    "name": pod_name,
                    "phase": phase,
                    "ready": ready,
                    "total": len(containers),
                    "restarts": restarts,
                })

        if pods:
            try:
                log_lines = await kube_client.get_logs(
                    cluster, pods[0]["name"],
                    namespace=mapping.deployment_namespace,
                    tail_lines=50,
                )
            except Exception:
                log_lines = "(unable to fetch logs)"
    except Exception:
        logger.debug("Failed to fetch pods for %s", mapping.deployment_name)

    return {"events": events, "pods": pods, "logs": log_lines}


# ---------------------------------------------------------------------------
# Debug session (Ask Orbi about a service)
# ---------------------------------------------------------------------------


class DebugSessionRequest(BaseModel):
    prompt: str = Field(
        default="Help me debug this service. Check its pod status, recent logs, and events.",
    )


@router.post("/projects/{project_id}/system-map/mappings/{mapping_id}/debug-session")
async def create_debug_session(
    project_id: UUID,
    mapping_id: UUID,
    body: DebugSessionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    """Create a chat session pre-loaded with service context.

    Returns the new session ID so the frontend can navigate to it.
    """
    await require_project_access(db, current.id, project_id, min_access="write")
    mapping = await system_map_service.get_mapping(db, project_id, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    # Gather live status
    status_items = await system_map_service.compute_status_for_mappings(db, project_id)
    st = next((s for s in status_items if s["mapping_id"] == str(mapping_id)), None)
    dep = st["deployment"] if st else {}
    gap = st["gap"] if st else {}

    repo_info = ""
    if mapping.context_source:
        cs = mapping.context_source
        repo_info = f"- Repository: {cs.name} ({cs.url})\n"

    context_text = (
        f"## Service Debug Context\n"
        f"- Deployment: {mapping.deployment_name}\n"
        f"- Namespace: {mapping.deployment_namespace}\n"
        f"- Cluster: {dep.get('cluster_name', 'unknown')}\n"
        f"- Status: {dep.get('status', 'unknown')} "
        f"({dep.get('ready_replicas', '?')}/{dep.get('replicas', '?')} pods ready)\n"
        f"- Image: {dep.get('image', 'unknown')}\n"
        f"{repo_info}"
        f"- Version gap: {gap.get('status', 'unknown')}"
        f"{' (' + str(gap.get('gap_count', '')) + ' commits behind)' if gap.get('gap_count') else ''}\n"
        f"\n"
        f"Use the k8s_get_logs, k8s_get_events, and k8s_get_resources tools "
        f"to investigate. The cluster name is **{dep.get('cluster_name', 'unknown')}**."
    )

    session = Session(
        title=f"Debug: {mapping.deployment_name}",
        project_id=project_id,
        user_id=current.id,
    )
    db.add(session)
    await db.flush()

    layer = SessionLayer(
        session_id=session.id,
        type=SessionLayerType.code_snippet,
        label=f"Service context: {mapping.deployment_name}",
        cached_content={"text": context_text},
        token_count=len(context_text.split()),
    )
    db.add(layer)
    await db.commit()

    return {"session_id": str(session.id)}
