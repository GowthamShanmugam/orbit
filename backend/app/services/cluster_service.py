"""CRUD operations and connection testing for project clusters."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_vault import decrypt, encrypt
from app.models.cluster import (
    ClusterAuthMethod,
    ClusterRole,
    ClusterStatus,
    ProjectCluster,
    TestRun,
    TestRunStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def encrypt_credentials(credentials: dict[str, Any]) -> tuple[bytes, bytes, bytes]:
    """Encrypt a credentials dict using the shared vault key."""
    plaintext = json.dumps(credentials)
    return encrypt(plaintext)


def decrypt_credentials(cluster: ProjectCluster) -> dict[str, Any]:
    """Decrypt a cluster's stored credentials."""
    plaintext = decrypt(
        cluster.encrypted_credentials,
        cluster.credentials_nonce,
        cluster.credentials_tag,
    )
    return json.loads(plaintext)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def list_clusters(
    db: AsyncSession,
    project_id: uuid.UUID,
    role: ClusterRole | None = None,
) -> list[ProjectCluster]:
    stmt = (
        select(ProjectCluster)
        .where(ProjectCluster.project_id == project_id)
        .order_by(ProjectCluster.created_at.desc())
    )
    if role is not None:
        stmt = stmt.where(ProjectCluster.role == role)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_cluster(
    db: AsyncSession,
    project_id: uuid.UUID,
    cluster_id: uuid.UUID,
) -> ProjectCluster | None:
    stmt = select(ProjectCluster).where(
        ProjectCluster.id == cluster_id,
        ProjectCluster.project_id == project_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_cluster(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    name: str,
    role: ClusterRole,
    auth_method: ClusterAuthMethod,
    credentials: dict[str, Any],
    api_server_url: str | None = None,
    namespace_filter: list[str] | None = None,
    sync_config: dict[str, Any] | None = None,
) -> ProjectCluster:
    ct, nonce, tag = encrypt_credentials(credentials)

    cluster = ProjectCluster(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        role=role,
        auth_method=auth_method,
        api_server_url=api_server_url,
        encrypted_credentials=ct,
        credentials_nonce=nonce,
        credentials_tag=tag,
        namespace_filter=namespace_filter,
        status=ClusterStatus.pending,
        sync_config=sync_config or _default_sync_config(role),
        config={},
    )
    db.add(cluster)
    await db.commit()
    await db.refresh(cluster)
    return cluster


async def update_cluster(
    db: AsyncSession,
    cluster: ProjectCluster,
    *,
    name: str | None = None,
    namespace_filter: list[str] | None = ...,  # type: ignore[assignment]
    sync_config: dict[str, Any] | None = ...,  # type: ignore[assignment]
    credentials: dict[str, Any] | None = None,
    api_server_url: str | None = ...,  # type: ignore[assignment]
) -> ProjectCluster:
    if name is not None:
        cluster.name = name
    if namespace_filter is not ...:
        cluster.namespace_filter = namespace_filter  # type: ignore[assignment]
    if sync_config is not ...:
        cluster.sync_config = sync_config  # type: ignore[assignment]
    if api_server_url is not ...:
        cluster.api_server_url = api_server_url  # type: ignore[assignment]
    if credentials is not None:
        ct, nonce, tag = encrypt_credentials(credentials)
        cluster.encrypted_credentials = ct
        cluster.credentials_nonce = nonce
        cluster.credentials_tag = tag
        cluster.status = ClusterStatus.pending

    await db.commit()
    await db.refresh(cluster)
    return cluster


async def delete_cluster(db: AsyncSession, cluster: ProjectCluster) -> None:
    await db.delete(cluster)
    await db.commit()


# ---------------------------------------------------------------------------
# Connection testing
# ---------------------------------------------------------------------------

async def test_connection(cluster: ProjectCluster) -> tuple[bool, str]:
    """Decrypt credentials, hit the K8s /api endpoint, return (ok, message)."""
    try:
        creds = decrypt_credentials(cluster)
        headers, verify_ssl, base_url = _build_http_params(cluster, creds)

        async with httpx.AsyncClient(verify=verify_ssl, timeout=10.0) as client:
            resp = await client.get(f"{base_url}/api", headers=headers)
            if resp.status_code == 200:
                return True, "Connected successfully"
            return False, f"API returned {resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        logger.warning("Cluster connection test failed: %s", exc)
        return False, str(exc)


async def update_status(
    db: AsyncSession,
    cluster: ProjectCluster,
    status: ClusterStatus,
    message: str | None = None,
) -> None:
    cluster.status = status
    cluster.status_message = message
    await db.commit()
    await db.refresh(cluster)


# ---------------------------------------------------------------------------
# Test run helpers
# ---------------------------------------------------------------------------

async def list_test_runs(
    db: AsyncSession,
    cluster_id: uuid.UUID,
    limit: int = 50,
) -> list[TestRun]:
    stmt = (
        select(TestRun)
        .where(TestRun.cluster_id == cluster_id)
        .order_by(TestRun.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_test_run(
    db: AsyncSession, cluster_id: uuid.UUID, run_id: uuid.UUID
) -> TestRun | None:
    stmt = select(TestRun).where(
        TestRun.id == run_id, TestRun.cluster_id == cluster_id
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_test_run(
    db: AsyncSession,
    cluster_id: uuid.UUID,
    *,
    command: str,
    run_type: str = "command",
    triggered_by: uuid.UUID | None = None,
    config: dict[str, Any] | None = None,
) -> TestRun:
    run = TestRun(
        id=uuid.uuid4(),
        cluster_id=cluster_id,
        run_type=run_type,
        command=command,
        status=TestRunStatus.pending,
        triggered_by=triggered_by,
        config=config,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def finish_test_run(
    db: AsyncSession,
    run: TestRun,
    *,
    status: TestRunStatus,
    output: str | None = None,
    exit_code: int | None = None,
    duration_ms: int | None = None,
) -> TestRun:
    run.status = status
    run.output = output
    run.exit_code = exit_code
    run.duration_ms = duration_ms
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(run)
    return run


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_http_params(
    cluster: ProjectCluster, creds: dict[str, Any]
) -> tuple[dict[str, str], bool, str]:
    """Build (headers, verify_ssl, base_url) from cluster + decrypted creds."""
    headers: dict[str, str] = {}
    verify_ssl = creds.get("verify_ssl", True)

    if cluster.auth_method == ClusterAuthMethod.token:
        token = creds.get("token", "")
        headers["Authorization"] = f"Bearer {token}"
        base_url = cluster.api_server_url or creds.get("api_server_url", "")
    else:
        base_url = creds.get("api_server_url", "") or cluster.api_server_url or ""
        token = creds.get("token")
        if token:
            headers["Authorization"] = f"Bearer {token}"

    return headers, verify_ssl, base_url.rstrip("/")


def _default_sync_config(role: ClusterRole) -> dict[str, Any]:
    if role == ClusterRole.context:
        return {
            "resource_types": [
                "pods", "services", "deployments", "configmaps",
                "events", "ingresses", "statefulsets",
            ],
            "include_crds": True,
            "include_logs": False,
            "sync_interval_minutes": 30,
        }
    return {"resource_types": [], "include_crds": False}
