"""Lightweight async Kubernetes API client using httpx.

All write operations are role-gated — they raise if called on a context cluster.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.models.cluster import ClusterRole, ProjectCluster
from app.services.cluster_service import _build_http_params, decrypt_credentials

logger = logging.getLogger(__name__)


def _default_httpx_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        settings.KUBE_HTTP_READ_TIMEOUT_SEC,
        connect=settings.KUBE_HTTP_CONNECT_TIMEOUT_SEC,
    )

CORE_RESOURCES = {
    "pods": "/api/v1/{ns_path}pods",
    "services": "/api/v1/{ns_path}services",
    "configmaps": "/api/v1/{ns_path}configmaps",
    "secrets": "/api/v1/{ns_path}secrets",
    "events": "/api/v1/{ns_path}events",
    "nodes": "/api/v1/nodes",
    "namespaces": "/api/v1/namespaces",
    "persistentvolumeclaims": "/api/v1/{ns_path}persistentvolumeclaims",
}

APPS_RESOURCES = {
    "deployments": "/apis/apps/v1/{ns_path}deployments",
    "statefulsets": "/apis/apps/v1/{ns_path}statefulsets",
    "daemonsets": "/apis/apps/v1/{ns_path}daemonsets",
    "replicasets": "/apis/apps/v1/{ns_path}replicasets",
}

BATCH_RESOURCES = {
    "jobs": "/apis/batch/v1/{ns_path}jobs",
    "cronjobs": "/apis/batch/v1/{ns_path}cronjobs",
}

NETWORKING_RESOURCES = {
    "ingresses": "/apis/networking.k8s.io/v1/{ns_path}ingresses",
}

RESOURCE_PATHS = {**CORE_RESOURCES, **APPS_RESOURCES, **BATCH_RESOURCES, **NETWORKING_RESOURCES}


class KubeClientError(Exception):
    pass


class ReadOnlyViolation(KubeClientError):
    """Raised when a write operation is attempted on a context cluster."""
    pass


def _require_write(cluster: ProjectCluster) -> None:
    if cluster.role == ClusterRole.context:
        raise ReadOnlyViolation(
            f"Cluster '{cluster.name}' has role=context — write operations are forbidden"
        )


def _ns_path(namespace: str | None) -> str:
    if namespace:
        return f"namespaces/{namespace}/"
    return ""


async def _make_client(
    cluster: ProjectCluster,
) -> tuple[httpx.AsyncClient, str]:
    """Build an httpx client configured for a cluster."""
    creds = decrypt_credentials(cluster)
    headers, verify_ssl, base_url = _build_http_params(cluster, creds)
    client = httpx.AsyncClient(
        headers=headers,
        verify=verify_ssl,
        timeout=_default_httpx_timeout(),
    )
    return client, base_url


async def _get(
    cluster: ProjectCluster, path: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    client, base_url = await _make_client(cluster)
    async with client:
        resp = await client.get(f"{base_url}{path}", params=params)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Read operations (context + test clusters)
# ---------------------------------------------------------------------------

async def get_resources(
    cluster: ProjectCluster,
    resource_type: str,
    namespace: str | None = None,
    label_selector: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List resources of a given type."""
    path_template = RESOURCE_PATHS.get(resource_type)
    if not path_template:
        raise KubeClientError(f"Unknown resource type: {resource_type}")

    path = path_template.format(ns_path=_ns_path(namespace))
    params: dict[str, Any] = {}
    if label_selector:
        params["labelSelector"] = label_selector
    if limit:
        params["limit"] = limit

    return await _get(cluster, path, params or None)


async def get_events(
    cluster: ProjectCluster,
    namespace: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    if limit is None:
        limit = settings.KUBE_EVENTS_DEFAULT_LIMIT
    ns = _ns_path(namespace)
    return await _get(cluster, f"/api/v1/{ns}events", {"limit": limit})


async def get_logs(
    cluster: ProjectCluster,
    pod: str,
    namespace: str = "default",
    container: str | None = None,
    tail_lines: int = 200,
) -> str:
    """Get pod logs as plain text."""
    params: dict[str, Any] = {"tailLines": tail_lines}
    if container:
        params["container"] = container

    path = f"/api/v1/namespaces/{namespace}/pods/{pod}/log"
    client, base_url = await _make_client(cluster)
    async with client:
        resp = await client.get(f"{base_url}{path}", params=params)
        resp.raise_for_status()
        return resp.text


async def list_crds(cluster: ProjectCluster) -> dict[str, Any]:
    return await _get(
        cluster,
        "/apis/apiextensions.k8s.io/v1/customresourcedefinitions",
    )


async def get_cr_instances(
    cluster: ProjectCluster,
    group: str,
    version: str,
    resource: str,
    namespace: str | None = None,
) -> dict[str, Any]:
    ns = _ns_path(namespace)
    path = f"/apis/{group}/{version}/{ns}{resource}"
    return await _get(cluster, path)


async def get_namespaces(cluster: ProjectCluster) -> list[str]:
    data = await _get(cluster, "/api/v1/namespaces")
    return [
        item["metadata"]["name"]
        for item in data.get("items", [])
    ]


async def get_server_version(cluster: ProjectCluster) -> dict[str, Any]:
    return await _get(cluster, "/version")


# ---------------------------------------------------------------------------
# Write operations (test clusters only)
# ---------------------------------------------------------------------------

async def apply_manifest(
    cluster: ProjectCluster,
    manifest: dict[str, Any],
    namespace: str = "default",
) -> dict[str, Any]:
    """Apply a manifest to a test cluster (POST or PUT)."""
    _require_write(cluster)

    api_version = manifest.get("apiVersion", "v1")
    kind = manifest.get("kind", "").lower()
    name = manifest.get("metadata", {}).get("name")

    path = _resolve_api_path(api_version, kind, namespace)

    client, base_url = await _make_client(cluster)
    async with client:
        if name:
            check = await client.get(f"{base_url}{path}/{name}")
            if check.status_code == 200:
                resp = await client.put(
                    f"{base_url}{path}/{name}",
                    json=manifest,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                return resp.json()

        resp = await client.post(
            f"{base_url}{path}",
            json=manifest,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


async def delete_resource(
    cluster: ProjectCluster,
    resource_type: str,
    name: str,
    namespace: str = "default",
) -> dict[str, Any]:
    """Delete a named resource on a test cluster."""
    _require_write(cluster)

    path_template = RESOURCE_PATHS.get(resource_type)
    if not path_template:
        raise KubeClientError(f"Unknown resource type: {resource_type}")

    path = path_template.format(ns_path=_ns_path(namespace))
    client, base_url = await _make_client(cluster)
    async with client:
        resp = await client.delete(f"{base_url}{path}/{name}")
        resp.raise_for_status()
        return resp.json()


async def exec_command(
    cluster: ProjectCluster,
    pod: str,
    command: list[str],
    namespace: str = "default",
    container: str | None = None,
    timeout: float | None = None,
) -> str:
    """Execute a command in a pod on a test cluster.

    Uses the pod exec subresource via POST with stdin/stdout.
    For simplicity this does a synchronous exec (not WebSocket upgrade)
    which works for short-lived commands.
    """
    _require_write(cluster)

    if timeout is None:
        timeout = settings.KUBE_LOG_STREAM_TIMEOUT_SEC

    params: dict[str, Any] = {
        "stdout": "true",
        "stderr": "true",
    }
    if container:
        params["container"] = container
    for part in command:
        params.setdefault("command", [])
        # httpx handles list params correctly
    # Build command params for httpx
    param_list: list[tuple[str, str]] = [
        ("stdout", "true"),
        ("stderr", "true"),
    ]
    if container:
        param_list.append(("container", container))
    for part in command:
        param_list.append(("command", part))

    path = f"/api/v1/namespaces/{namespace}/pods/{pod}/exec"
    client, base_url = await _make_client(cluster)
    async with client:
        client.timeout = httpx.Timeout(
            timeout, connect=settings.KUBE_HTTP_CONNECT_TIMEOUT_SEC
        )
        resp = await client.post(f"{base_url}{path}", params=param_list)
        if resp.status_code >= 400:
            raise KubeClientError(
                f"Exec failed ({resp.status_code}): {resp.text[:500]}"
            )
        return resp.text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_api_path(api_version: str, kind: str, namespace: str) -> str:
    """Resolve a K8s API path from apiVersion and kind."""
    kind_to_resource = {
        "pod": "pods",
        "service": "services",
        "deployment": "deployments",
        "configmap": "configmaps",
        "secret": "secrets",
        "ingress": "ingresses",
        "statefulset": "statefulsets",
        "daemonset": "daemonsets",
        "job": "jobs",
        "cronjob": "cronjobs",
        "namespace": "namespaces",
    }

    resource = kind_to_resource.get(kind, f"{kind}s")

    if "/" in api_version:
        group_version = api_version
        prefix = f"/apis/{group_version}"
    else:
        prefix = f"/api/{api_version}"

    if kind in ("namespace", "node", "persistentvolume"):
        return f"{prefix}/{resource}"

    return f"{prefix}/namespaces/{namespace}/{resource}"
