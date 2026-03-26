"""Anthropic tool definitions for live Kubernetes cluster interaction.

Defines tool schemas in Anthropic's format and a dispatcher that resolves
cluster names to ProjectCluster objects, calls kube_client, and returns
string results for the AI to consume.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cluster import ClusterRole, ProjectCluster
from app.services import cluster_service, kube_client

logger = logging.getLogger(__name__)

RESOURCE_TYPES = sorted(kube_client.RESOURCE_PATHS.keys())

# ---------------------------------------------------------------------------
# Tool definitions (Anthropic format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "k8s_list_clusters",
        "description": (
            "List all Kubernetes clusters attached to this project. "
            "Returns each cluster's name, role (context=read-only, test=read-write), "
            "status, and API server URL. Call this first to discover available clusters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "k8s_get_namespaces",
        "description": "List all namespaces in a cluster.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster_name": {
                    "type": "string",
                    "description": "Name of the cluster to query",
                },
            },
            "required": ["cluster_name"],
        },
    },
    {
        "name": "k8s_get_resources",
        "description": (
            "List Kubernetes resources of a specific type. "
            "Returns a summary of each resource (name, namespace, status, age). "
            f"Supported types: {', '.join(RESOURCE_TYPES)}"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster_name": {
                    "type": "string",
                    "description": "Name of the cluster to query",
                },
                "resource_type": {
                    "type": "string",
                    "description": "Type of resource to list",
                    "enum": RESOURCE_TYPES,
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace to filter by. Omit for all namespaces (cluster-scoped resources) or specify a namespace.",
                },
                "label_selector": {
                    "type": "string",
                    "description": "Label selector to filter resources (e.g. 'app=nginx')",
                },
            },
            "required": ["cluster_name", "resource_type"],
        },
    },
    {
        "name": "k8s_get_logs",
        "description": (
            "Fetch logs from a specific pod. Returns the last N lines of log output. "
            "Useful for debugging crashes, errors, or understanding pod behavior."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster_name": {
                    "type": "string",
                    "description": "Name of the cluster",
                },
                "pod": {
                    "type": "string",
                    "description": "Name of the pod",
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace of the pod (default: 'default')",
                },
                "container": {
                    "type": "string",
                    "description": "Container name (for multi-container pods)",
                },
                "tail_lines": {
                    "type": "integer",
                    "description": "Number of lines from the end to return (default: 100)",
                },
            },
            "required": ["cluster_name", "pod"],
        },
    },
    {
        "name": "k8s_get_events",
        "description": (
            "Fetch recent Kubernetes events. Useful for understanding "
            "scheduling issues, resource problems, or recent changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster_name": {
                    "type": "string",
                    "description": "Name of the cluster",
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace to filter events. Omit for all namespaces.",
                },
            },
            "required": ["cluster_name"],
        },
    },
    {
        "name": "k8s_list_crds",
        "description": "List all Custom Resource Definitions (CRDs) installed in the cluster.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster_name": {
                    "type": "string",
                    "description": "Name of the cluster",
                },
            },
            "required": ["cluster_name"],
        },
    },
    {
        "name": "k8s_apply_manifest",
        "description": (
            "Apply a Kubernetes manifest (create or update a resource). "
            "Only works on TEST clusters (role=test). Will be rejected on context clusters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster_name": {
                    "type": "string",
                    "description": "Name of the TEST cluster",
                },
                "manifest": {
                    "type": "object",
                    "description": "Full Kubernetes manifest as JSON (with apiVersion, kind, metadata, spec)",
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace to apply in (default: 'default')",
                },
            },
            "required": ["cluster_name", "manifest"],
        },
    },
    {
        "name": "k8s_run_command",
        "description": (
            "Run a shell command on a TEST cluster via an ephemeral Job. "
            "The command runs in a container, output is captured and returned. "
            "Only works on TEST clusters. "
            "IMPORTANT: Prefer using k8s_get_resources, k8s_get_logs, k8s_get_events for read-only "
            "queries — they are faster and don't require pulling images. Only use k8s_run_command "
            "when you need to execute something that the other tools cannot do. "
            "The image MUST be pullable by the cluster. For OpenShift/restricted registries, "
            "use images from registry.access.redhat.com (e.g. registry.access.redhat.com/ubi9/ubi-minimal:latest) "
            "or images already present in the cluster. Never use Docker Hub images like bitnami/* "
            "unless the user confirms the cluster can pull from Docker Hub."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster_name": {
                    "type": "string",
                    "description": "Name of the TEST cluster",
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace to run in (default: 'default')",
                },
                "image": {
                    "type": "string",
                    "description": "Container image to use. Use registry.access.redhat.com/ubi9/ubi-minimal:latest for general commands, or a project-specific image if available.",
                },
            },
            "required": ["cluster_name", "command"],
        },
    },
    {
        "name": "k8s_delete_resource",
        "description": (
            "Delete a Kubernetes resource by type and name. "
            "Only works on TEST clusters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster_name": {
                    "type": "string",
                    "description": "Name of the TEST cluster",
                },
                "resource_type": {
                    "type": "string",
                    "description": "Type of resource to delete",
                    "enum": RESOURCE_TYPES,
                },
                "name": {
                    "type": "string",
                    "description": "Name of the resource to delete",
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace of the resource (default: 'default')",
                },
            },
            "required": ["cluster_name", "resource_type", "name"],
        },
    },
]


def get_tool_definitions() -> list[dict[str, Any]]:
    """Return the full list of K8s tool definitions."""
    return TOOL_DEFINITIONS


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

async def execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    project_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    """Execute a K8s tool call and return a string result for the AI."""
    try:
        if tool_name == "k8s_list_clusters":
            return await _list_clusters(project_id, db)
        elif tool_name == "k8s_get_namespaces":
            return await _get_namespaces(tool_input, project_id, db)
        elif tool_name == "k8s_get_resources":
            return await _get_resources(tool_input, project_id, db)
        elif tool_name == "k8s_get_logs":
            return await _get_logs(tool_input, project_id, db)
        elif tool_name == "k8s_get_events":
            return await _get_events(tool_input, project_id, db)
        elif tool_name == "k8s_list_crds":
            return await _list_crds(tool_input, project_id, db)
        elif tool_name == "k8s_apply_manifest":
            return await _apply_manifest(tool_input, project_id, db)
        elif tool_name == "k8s_run_command":
            return await _run_command(tool_input, project_id, db)
        elif tool_name == "k8s_delete_resource":
            return await _delete_resource(tool_input, project_id, db)
        else:
            return f"Error: Unknown tool '{tool_name}'"
    except kube_client.ReadOnlyViolation as exc:
        return f"Error: {exc}"
    except kube_client.KubeClientError as exc:
        return f"Error querying cluster: {exc}"
    except Exception as exc:
        logger.exception("Tool execution failed: %s", tool_name)
        return f"Error: {exc}"


def get_tool_activity_label(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Generate a human-readable activity label for an SSE event."""
    cluster = tool_input.get("cluster_name", "")
    labels: dict[str, str] = {
        "k8s_list_clusters": "Listing attached clusters",
        "k8s_get_namespaces": f"Listing namespaces on {cluster}",
        "k8s_get_resources": f"Querying {tool_input.get('resource_type', 'resources')} on {cluster}",
        "k8s_get_logs": f"Fetching logs for {tool_input.get('pod', 'pod')} on {cluster}",
        "k8s_get_events": f"Fetching events from {cluster}",
        "k8s_list_crds": f"Listing CRDs on {cluster}",
        "k8s_apply_manifest": f"Applying manifest to {cluster}",
        "k8s_run_command": f"Running command on {cluster}",
        "k8s_delete_resource": f"Deleting {tool_input.get('resource_type', 'resource')} on {cluster}",
    }
    return labels.get(tool_name, f"Executing {tool_name}")


# ---------------------------------------------------------------------------
# Cluster resolution helper
# ---------------------------------------------------------------------------

async def _resolve_cluster(
    cluster_name: str, project_id: uuid.UUID, db: AsyncSession
) -> ProjectCluster:
    """Find a cluster by name within a project."""
    stmt = select(ProjectCluster).where(
        ProjectCluster.project_id == project_id,
        ProjectCluster.name == cluster_name,
    )
    result = await db.execute(stmt)
    cluster = result.scalar_one_or_none()
    if cluster is None:
        raise kube_client.KubeClientError(
            f"Cluster '{cluster_name}' not found. Use k8s_list_clusters to see available clusters."
        )
    return cluster


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _list_clusters(project_id: uuid.UUID, db: AsyncSession) -> str:
    clusters = await cluster_service.list_clusters(db, project_id)
    if not clusters:
        return "No clusters are attached to this project."
    rows = []
    for c in clusters:
        rows.append({
            "name": c.name,
            "role": c.role.value,
            "status": c.status.value,
            "api_server_url": c.api_server_url or "N/A",
            "namespaces": c.namespace_filter or "all",
        })
    return json.dumps(rows, indent=2)


async def _get_namespaces(
    inp: dict[str, Any], project_id: uuid.UUID, db: AsyncSession
) -> str:
    cluster = await _resolve_cluster(inp["cluster_name"], project_id, db)
    namespaces = await kube_client.get_namespaces(cluster)
    return json.dumps(namespaces)


async def _get_resources(
    inp: dict[str, Any], project_id: uuid.UUID, db: AsyncSession
) -> str:
    cluster = await _resolve_cluster(inp["cluster_name"], project_id, db)
    data = await kube_client.get_resources(
        cluster,
        inp["resource_type"],
        namespace=inp.get("namespace"),
        label_selector=inp.get("label_selector"),
        limit=50,
    )
    items = data.get("items", [])
    summary = _summarise_resources(items, inp["resource_type"])
    return json.dumps(summary, indent=2, default=str)


async def _get_logs(
    inp: dict[str, Any], project_id: uuid.UUID, db: AsyncSession
) -> str:
    cluster = await _resolve_cluster(inp["cluster_name"], project_id, db)
    logs = await kube_client.get_logs(
        cluster,
        inp["pod"],
        namespace=inp.get("namespace", "default"),
        container=inp.get("container"),
        tail_lines=inp.get("tail_lines", 100),
    )
    if len(logs) > 8000:
        logs = logs[-8000:]
        logs = "...(truncated)\n" + logs
    return logs


async def _get_events(
    inp: dict[str, Any], project_id: uuid.UUID, db: AsyncSession
) -> str:
    cluster = await _resolve_cluster(inp["cluster_name"], project_id, db)
    data = await kube_client.get_events(
        cluster, namespace=inp.get("namespace"), limit=50
    )
    items = data.get("items", [])
    events = []
    for e in items[-30:]:
        events.append({
            "type": e.get("type"),
            "reason": e.get("reason"),
            "message": e.get("message", "")[:200],
            "object": f"{e.get('involvedObject', {}).get('kind', '')}/{e.get('involvedObject', {}).get('name', '')}",
            "count": e.get("count"),
            "last_seen": e.get("lastTimestamp"),
        })
    return json.dumps(events, indent=2, default=str)


async def _list_crds(
    inp: dict[str, Any], project_id: uuid.UUID, db: AsyncSession
) -> str:
    cluster = await _resolve_cluster(inp["cluster_name"], project_id, db)
    data = await kube_client.list_crds(cluster)
    items = data.get("items", [])
    crds = []
    for crd in items:
        spec = crd.get("spec", {})
        crds.append({
            "name": crd.get("metadata", {}).get("name"),
            "group": spec.get("group"),
            "scope": spec.get("scope"),
            "kind": spec.get("names", {}).get("kind"),
        })
    return json.dumps(crds, indent=2)


async def _apply_manifest(
    inp: dict[str, Any], project_id: uuid.UUID, db: AsyncSession
) -> str:
    cluster = await _resolve_cluster(inp["cluster_name"], project_id, db)
    result = await kube_client.apply_manifest(
        cluster,
        inp["manifest"],
        namespace=inp.get("namespace", "default"),
    )
    kind = result.get("kind", "Resource")
    name = result.get("metadata", {}).get("name", "unknown")
    return f"Successfully applied {kind}/{name}"


async def _run_command(
    inp: dict[str, Any], project_id: uuid.UUID, db: AsyncSession
) -> str:
    cluster = await _resolve_cluster(inp["cluster_name"], project_id, db)
    if cluster.role != ClusterRole.test:
        return "Error: Commands can only be run on test clusters (role=test)"

    namespace = inp.get("namespace", "default")
    image = inp.get("image", "registry.access.redhat.com/ubi9/ubi-minimal:latest")
    command = inp["command"]

    job_name = f"orbit-tool-{uuid.uuid4().hex[:8]}"
    job_manifest: dict[str, Any] = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": namespace,
            "labels": {"app.kubernetes.io/managed-by": "orbit"},
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 120,
            "ttlSecondsAfterFinished": 60,
            "template": {
                "metadata": {
                    "labels": {"app.kubernetes.io/managed-by": "orbit"},
                },
                "spec": {
                    "restartPolicy": "Never",
                    "containers": [
                        {
                            "name": "run",
                            "image": image,
                            "command": ["sh", "-c", command],
                        }
                    ],
                },
            },
        },
    }

    try:
        await kube_client.apply_manifest(cluster, job_manifest, namespace=namespace)
        output = await _wait_for_job_logs(cluster, job_name, namespace)
        return output
    finally:
        try:
            await kube_client.delete_resource(cluster, "jobs", job_name, namespace=namespace)
        except Exception:
            pass


async def _delete_resource(
    inp: dict[str, Any], project_id: uuid.UUID, db: AsyncSession
) -> str:
    cluster = await _resolve_cluster(inp["cluster_name"], project_id, db)
    await kube_client.delete_resource(
        cluster,
        inp["resource_type"],
        inp["name"],
        namespace=inp.get("namespace", "default"),
    )
    return f"Successfully deleted {inp['resource_type']}/{inp['name']}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summarise_resources(items: list[dict[str, Any]], resource_type: str) -> list[dict[str, Any]]:
    """Extract a compact summary from raw K8s resource items."""
    summaries = []
    for item in items:
        meta = item.get("metadata", {})
        status = item.get("status", {})
        spec = item.get("spec", {})

        summary: dict[str, Any] = {
            "name": meta.get("name"),
            "namespace": meta.get("namespace"),
            "created": meta.get("creationTimestamp"),
        }

        if resource_type == "pods":
            summary["phase"] = status.get("phase")
            containers = status.get("containerStatuses", [])
            summary["ready"] = f"{sum(1 for c in containers if c.get('ready'))}/{len(containers)}"
            summary["restarts"] = sum(c.get("restartCount", 0) for c in containers)
            if any(c.get("state", {}).get("waiting") for c in containers):
                waiting = next(
                    (c["state"]["waiting"] for c in containers if c.get("state", {}).get("waiting")),
                    {},
                )
                summary["waiting_reason"] = waiting.get("reason")
        elif resource_type in ("deployments", "statefulsets", "daemonsets", "replicasets"):
            summary["replicas"] = status.get("replicas", 0)
            summary["ready_replicas"] = status.get("readyReplicas", 0)
            summary["available"] = status.get("availableReplicas", 0)
        elif resource_type == "services":
            summary["type"] = spec.get("type")
            summary["cluster_ip"] = spec.get("clusterIP")
            ports = spec.get("ports", [])
            summary["ports"] = [
                f"{p.get('port')}/{p.get('protocol', 'TCP')}" for p in ports
            ]
        elif resource_type == "events":
            summary["type"] = item.get("type")
            summary["reason"] = item.get("reason")
            summary["message"] = item.get("message", "")[:150]
            summary["count"] = item.get("count")
        elif resource_type == "nodes":
            conditions = status.get("conditions", [])
            ready = next((c for c in conditions if c.get("type") == "Ready"), {})
            summary["ready"] = ready.get("status")
            summary["roles"] = [
                k.replace("node-role.kubernetes.io/", "")
                for k in meta.get("labels", {})
                if k.startswith("node-role.kubernetes.io/")
            ]

        summaries.append(summary)
    return summaries


async def _wait_for_job_logs(
    cluster: ProjectCluster,
    job_name: str,
    namespace: str,
    timeout: float = 120.0,
) -> str:
    """Poll until a Job's pod completes, then return its logs."""
    import asyncio
    import time

    deadline = time.monotonic() + timeout
    pod_name: str | None = None

    while time.monotonic() < deadline:
        try:
            pods = await kube_client.get_resources(
                cluster, "pods", namespace=namespace,
                label_selector=f"job-name={job_name}",
            )
            items = pods.get("items", [])
            if items:
                pod_name = items[0]["metadata"]["name"]
                phase = items[0].get("status", {}).get("phase", "")
                if phase in ("Succeeded", "Failed"):
                    break
        except Exception:
            pass
        await asyncio.sleep(2)

    if not pod_name:
        raise kube_client.KubeClientError(
            f"Job {job_name} did not create a pod within timeout"
        )

    logs = await kube_client.get_logs(cluster, pod_name, namespace=namespace, tail_lines=500)
    if len(logs) > 8000:
        logs = logs[-8000:]
        logs = "...(truncated)\n" + logs
    return logs
