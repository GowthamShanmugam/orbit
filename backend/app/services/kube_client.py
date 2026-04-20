"""Lightweight async Kubernetes API client using httpx.

All write operations are role-gated — they raise if called on a context cluster.
"""

from __future__ import annotations

import asyncio
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


async def list_cluster_role_bindings(cluster: ProjectCluster) -> dict[str, Any]:
    return await _get(
        cluster,
        "/apis/rbac.authorization.k8s.io/v1/clusterrolebindings",
    )


async def get_cluster_role(cluster: ProjectCluster, name: str) -> dict[str, Any]:
    return await _get(
        cluster,
        f"/apis/rbac.authorization.k8s.io/v1/clusterroles/{name}",
    )


async def get_cluster_roles_bulk(
    cluster: ProjectCluster, names: list[str],
) -> dict[str, dict[str, Any] | None]:
    """Fetch multiple ClusterRoles concurrently using a single HTTP client."""
    client, base_url = await _make_client(cluster)

    async def _one(name: str) -> tuple[str, dict[str, Any] | None]:
        try:
            resp = await client.get(
                f"{base_url}/apis/rbac.authorization.k8s.io/v1/clusterroles/{name}",
            )
            resp.raise_for_status()
            return name, resp.json()
        except Exception:
            return name, None

    async with client:
        pairs = await asyncio.gather(*[_one(n) for n in names])
    return dict(pairs)


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


async def get_resource_by_ref(
    cluster: ProjectCluster,
    api_version: str,
    kind: str,
    name: str,
    namespace: str | None = None,
) -> dict[str, Any]:
    """Fetch a single K8s resource by apiVersion/kind/name.

    Works for any resource type including Custom Resources.
    Tries the namespaced path first; falls back to cluster-scoped if 404.
    """
    ns = namespace or "default"
    path = _resolve_api_path(api_version, kind.lower(), ns)
    try:
        return await _get(cluster, f"{path}/{name}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404 and "/" in api_version:
            cluster_path = _resolve_cluster_scoped_path(api_version, kind.lower())
            return await _get(cluster, f"{cluster_path}/{name}")
        raise


async def get_resources_bulk(
    cluster: ProjectCluster,
    requests: list[tuple[str, str, str, str]],
) -> list[dict[str, Any] | None]:
    """Fetch multiple heterogeneous resources concurrently via a single HTTP client.

    Each request is (api_version, kind, name, namespace).
    Returns list of results in same order; None for failed fetches.
    """
    client, base_url = await _make_client(cluster)

    async def _one(
        api_version: str, kind: str, name: str, namespace: str,
    ) -> dict[str, Any] | None:
        ns = namespace or "default"
        path = _resolve_api_path(api_version, kind.lower(), ns)
        try:
            resp = await client.get(f"{base_url}{path}/{name}")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404 and "/" in api_version:
                cluster_path = _resolve_cluster_scoped_path(
                    api_version, kind.lower(),
                )
                try:
                    resp = await client.get(f"{base_url}{cluster_path}/{name}")
                    resp.raise_for_status()
                    return resp.json()
                except Exception:
                    pass
            return None
        except Exception:
            return None

    async with client:
        results = await asyncio.gather(
            *[_one(av, k, n, ns) for av, k, n, ns in requests],
        )
    return list(results)


async def get_namespaces(cluster: ProjectCluster) -> list[str]:
    data = await _get(cluster, "/api/v1/namespaces")
    return [item["metadata"]["name"] for item in data.get("items", [])]


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
        client.timeout = httpx.Timeout(timeout, connect=settings.KUBE_HTTP_CONNECT_TIMEOUT_SEC)
        resp = await client.post(f"{base_url}{path}", params=param_list)
        if resp.status_code >= 400:
            raise KubeClientError(f"Exec failed ({resp.status_code}): {resp.text[:500]}")
        return resp.text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_cluster_scoped_path(api_version: str, kind: str) -> str:
    """Resolve a cluster-scoped K8s API path (no namespace segment)."""
    kind_to_resource = {
        "pod": "pods", "service": "services", "deployment": "deployments",
        "configmap": "configmaps", "secret": "secrets", "ingress": "ingresses",
        "statefulset": "statefulsets", "daemonset": "daemonsets",
        "job": "jobs", "cronjob": "cronjobs", "namespace": "namespaces",
    }
    resource = kind_to_resource.get(kind, f"{kind}s")
    if "/" in api_version:
        return f"/apis/{api_version}/{resource}"
    return f"/api/{api_version}/{resource}"


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
