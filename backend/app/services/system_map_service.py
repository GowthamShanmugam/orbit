"""Service layer for the Live System Map feature.

Handles deployment discovery from K8s clusters, deterministic name-based
mapping, version gap computation, and CRUD for mappings/edges.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import uuid
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.cluster import ProjectCluster
from app.models.context import ContextSource, ContextSourceType
from app.models.system_map import ServiceEdge, ServiceMapping
from app.services import cluster_service, kube_client

logger = logging.getLogger(__name__)

REPO_SOURCE_TYPES = {ContextSourceType.github_repo, ContextSourceType.gitlab_repo}


# ---------------------------------------------------------------------------
# Deployment discovery
# ---------------------------------------------------------------------------


def _deployment_status(item: dict[str, Any]) -> str:
    """Derive a simple health string from a K8s deployment status block."""
    status = item.get("status", {})
    replicas = status.get("replicas", 0)
    ready = status.get("readyReplicas", 0)
    unavailable = status.get("unavailableReplicas", 0)
    if replicas == 0:
        return "failing"
    if unavailable and unavailable > 0:
        return "degraded"
    if ready and ready >= replicas:
        return "healthy"
    return "degraded"


def _extract_image(item: dict[str, Any]) -> str:
    """Pull the first container image from a deployment spec."""
    containers = (
        item.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    )
    if containers:
        return containers[0].get("image", "unknown")
    return "unknown"


async def get_live_deployments(
    db: AsyncSession, project_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Fetch deployments from all project clusters and return a flat list."""
    result = await db.execute(
        select(ProjectCluster).where(ProjectCluster.project_id == project_id)
    )
    clusters = list(result.scalars().all())

    deployments: list[dict[str, Any]] = []
    for cluster in clusters:
        api_url = getattr(cluster, "api_server_url", "") or ""
        if not api_url.startswith(("http://", "https://")):
            logger.warning("Skipping cluster %s: invalid API server URL", cluster.name)
            continue
        try:
            data = await kube_client.get_resources(cluster, "deployments")
            for item in data.get("items", []):
                meta = item.get("metadata", {})
                status_block = item.get("status", {})
                owner_refs = [
                    {
                        "api_version": ref.get("apiVersion", ""),
                        "kind": ref.get("kind", ""),
                        "name": ref.get("name", ""),
                        "uid": ref.get("uid", ""),
                    }
                    for ref in meta.get("ownerReferences", [])
                ]
                pod_spec = item.get("spec", {}).get("template", {}).get("spec", {})
                deployments.append(
                    {
                        "name": meta.get("name", "unknown"),
                        "namespace": meta.get("namespace", "default"),
                        "image": _extract_image(item),
                        "replicas": status_block.get("replicas", 0),
                        "ready_replicas": status_block.get("readyReplicas", 0),
                        "status": _deployment_status(item),
                        "cluster_id": str(cluster.id),
                        "cluster_name": cluster.name,
                        "uid": meta.get("uid", ""),
                        "owner_references": owner_refs,
                        "labels": meta.get("labels") or {},
                        "service_account": pod_spec.get("serviceAccountName", "default"),
                    }
                )
        except Exception:
            logger.warning("Failed to fetch deployments from cluster %s", cluster.name)

    return deployments


# ---------------------------------------------------------------------------
# Repo scanning: find image/service references inside cloned repos
# ---------------------------------------------------------------------------

_IMAGE_PATTERNS = [
    re.compile(r"image:\s*['\"]?([a-zA-Z0-9._\-]+/[a-zA-Z0-9._\-]+/[a-zA-Z0-9._\-]+)", re.MULTILINE),
    re.compile(r"['\"]([a-zA-Z0-9._\-]+\.[a-z]+/[a-zA-Z0-9._\-]+/[a-zA-Z0-9._\-]+)[:'\"@]", re.MULTILINE),
    re.compile(r"RELATED_IMAGE_\w+\s*=\s*['\"]?([a-zA-Z0-9._\-]+/[a-zA-Z0-9._\-]+/[a-zA-Z0-9._\-]+)", re.MULTILINE),
]


def _extract_image_base(full_image: str) -> str:
    """Strip tag/digest from image to get base name: quay.io/org/name."""
    img = full_image.split("@")[0]
    img = img.rsplit(":", 1)[0] if ":" in img.rsplit("/", 1)[-1] else img
    return img.lower()


def _image_org(image_base: str) -> str:
    """Extract the org segment: quay.io/opendatahub/foo -> opendatahub."""
    parts = image_base.split("/")
    return parts[1].lower() if len(parts) >= 3 else ""


def _normalize_org(name: str) -> str:
    """Normalize an org/repo name for comparison: opendatahub-io -> opendatahub."""
    name = name.lower()
    for suffix in ("-io", "-dev", "-org", "-inc", "-oss", "-apps"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.replace("-", "").replace("_", "")


def _github_org_from_url(url: str) -> str:
    """Extract the org from a GitHub/GitLab URL."""
    parts = url.rstrip("/").split("/")
    return parts[-2].lower() if len(parts) >= 2 else ""


def _is_project_image(image_base: str, github_org: str) -> bool:
    """True if image belongs to the same org as the repo (not a generic dep)."""
    norm_gh = _normalize_org(github_org)
    norm_img = _image_org(image_base).replace("-", "").replace("_", "")
    if not norm_gh or not norm_img:
        return False
    return norm_gh in norm_img or norm_img in norm_gh


def _scan_repo_for_images(clone_path: str) -> set[str]:
    """Scan a cloned repo for container image references.

    Uses grep for speed -- looks in YAML, Go, Python, Makefile, etc.
    Returns a set of base image names (without tags).
    """
    images: set[str] = set()
    try:
        result = subprocess.run(
            [
                "grep", "-rIh",
                "--exclude-dir=.git", "--exclude-dir=vendor",
                "--exclude-dir=node_modules", "--exclude-dir=.tox",
                "--include=*.yaml", "--include=*.yml",
                "--include=*.go", "--include=*.py", "--include=*.json",
                "--include=*.env", "--include=Makefile", "--include=*.mk",
                "--include=*.toml", "--include=*.cfg",
                "-E",
                r"(image:|RELATED_IMAGE_|quay\.io/|registry\.redhat\.io/|gcr\.io/|ghcr\.io/|docker\.io/)",
            ],
            cwd=clone_path, capture_output=True, text=True, timeout=30,
        )
        text = result.stdout
        for pattern in _IMAGE_PATTERNS:
            for match in pattern.finditer(text):
                base = _extract_image_base(match.group(1))
                if base:
                    images.add(base)
    except Exception:
        logger.debug("Failed to scan repo at %s for images", clone_path)

    return images


def _image_name(full_image: str) -> str:
    """Get the short name from an image: quay.io/org/foo -> foo."""
    base = _extract_image_base(full_image)
    return base.rsplit("/", 1)[-1]


_DEPLOY_SUFFIXES = (
    "", "-controller-manager", "-operator-controller-manager",
    "-controller", "-webhook", "-operator", "-deployment", "-manager",
)


_COMPONENT_REF_RE = re.compile(r"[/:]([a-zA-Z0-9._-]+)")

_BRANCH_NAMES = frozenset({
    "main", "master", "develop", "dev", "stable", "release",
    "latest", "head", "trunk", "staging", "production", "prod",
    "rhoai", "incubation", "incubating",
})


def _scan_repo_for_component_refs(clone_path: str, github_org: str) -> set[str]:
    """Find references to sibling repos in the same GitHub org.

    Uses a single regex that catches any ``<org>/<name>`` or
    ``<org>:<name>`` pattern.  This covers GitHub/GitLab URLs,
    manifest formats like ``org:repo:ref``, Go imports, and more --
    all in one grep pass.
    """
    refs: set[str] = set()
    org_escaped = re.escape(github_org)

    try:
        result = subprocess.run(
            [
                "grep", "-rIhEo",
                "--exclude-dir=.git", "--exclude-dir=vendor",
                "--exclude-dir=node_modules", "--exclude-dir=.tox",
                rf"{org_escaped}[/:][a-zA-Z0-9._-]+",
            ],
            cwd=clone_path, capture_output=True, text=True, timeout=30,
        )
        for line in result.stdout.splitlines():
            m = _COMPONENT_REF_RE.search(line.strip())
            if m:
                repo = m.group(1).lower().removesuffix(".git")
                if len(repo) >= 3 and repo not in _BRANCH_NAMES:
                    refs.add(repo)
    except Exception:
        logger.debug("grep for component refs failed at %s", clone_path)

    return refs


def _match_dep_to_component_ref(dep_name: str, ref_name: str) -> str | None:
    """Check if a deployment name matches a component repo name.

    Returns the match type ('exact' or 'contains') or None.
    """
    dep = dep_name.lower()

    for suffix in _DEPLOY_SUFFIXES:
        if dep == ref_name + suffix:
            return "exact"

    if len(ref_name) >= 5 and ref_name in dep:
        idx = dep.find(ref_name)
        before_ok = idx == 0 or dep[idx - 1] == "-"
        after_end = idx + len(ref_name)
        after_ok = after_end == len(dep) or dep[after_end] == "-"
        if before_ok and after_ok:
            return "contains"

    return None


async def suggest_mappings(
    db: AsyncSession, project_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Match cluster deployments to project repos by scanning repo code.

    Matching priority (highest wins):
      1. Deployment name == context-source repo name (with suffixes)
      2. Exact project-owned image match
      3. Short project-owned image name match
      4. Component-reference match -- the repo references sibling repos
         (via GitHub URLs or manifest entries like get_all_manifests.sh)
         and a deployment name matches one of those referenced repos.
    """
    deployments = await get_live_deployments(db, project_id)

    result = await db.execute(
        select(ContextSource).where(
            ContextSource.project_id == project_id,
            ContextSource.type.in_(REPO_SOURCE_TYPES),
        )
    )
    sources = list(result.scalars().all())

    if not deployments or not sources:
        return []

    # -- Pre-scan all repos --
    source_by_id: dict[str, Any] = {}
    project_images: dict[str, str] = {}
    project_image_names: dict[str, str] = {}
    source_component_refs: dict[str, set[str]] = {}  # source_id -> set of repo names

    for src in sources:
        sid = str(src.id)
        source_by_id[sid] = src
        clone_path = (src.config or {}).get("clone_path")
        if not clone_path:
            continue

        github_org = _github_org_from_url(src.url or "")
        own_repo_name = (
            (src.url or "").rstrip("/").rsplit("/", 1)[-1]
            .removesuffix(".git").lower()
            if src.url else src.name.lower()
        )

        # Image scan (project-owned only)
        raw_images = await asyncio.to_thread(_scan_repo_for_images, clone_path)
        kept = 0
        for img in raw_images:
            if not github_org or _is_project_image(img, github_org):
                project_images[img] = sid
                project_image_names[img.rsplit("/", 1)[-1]] = sid
                kept += 1

        # Component reference scan
        comp_refs: set[str] = set()
        if github_org:
            comp_refs = await asyncio.to_thread(
                _scan_repo_for_component_refs, clone_path, github_org,
            )
            comp_refs.discard(own_repo_name)

        source_component_refs[sid] = comp_refs

        logger.info(
            "Repo %s (org=%s): %d images (%d project-owned), %d component refs",
            src.name, github_org, len(raw_images), kept, len(comp_refs),
        )

    # -- Match deployments to sources --
    suggestions: list[dict[str, Any]] = []
    matched_deps: set[str] = set()

    # Pass 1: name-based (deployment name == context-source repo name)
    for dep in deployments:
        dep_key = f"{dep['name']}|{dep['namespace']}"
        dep_lower = dep["name"].lower()
        for src in sources:
            src_name = src.name.lower()
            repo_name = (
                (src.url or "").rstrip("/").rsplit("/", 1)[-1]
                .removesuffix(".git").lower()
                if src.url else src_name
            )
            for suffix in _DEPLOY_SUFFIXES:
                if dep_lower == repo_name + suffix or dep_lower == src_name + suffix:
                    suggestions.append(
                        _make_suggestion(dep, src, "high", f"Name matches {src.name}"),
                    )
                    matched_deps.add(dep_key)
                    break
            if dep_key in matched_deps:
                break

    # Pass 2: exact project-image match
    for dep in deployments:
        dep_key = f"{dep['name']}|{dep['namespace']}"
        if dep_key in matched_deps:
            continue
        dep_image_base = _extract_image_base(dep["image"])
        if dep_image_base in project_images:
            src = source_by_id[project_images[dep_image_base]]
            suggestions.append(
                _make_suggestion(dep, src, "high", f"Image found in {src.name}"),
            )
            matched_deps.add(dep_key)

    # Pass 3: short image-name match (project images only)
    for dep in deployments:
        dep_key = f"{dep['name']}|{dep['namespace']}"
        if dep_key in matched_deps:
            continue
        dep_image_name = _image_name(dep["image"])
        if dep_image_name in project_image_names:
            src = source_by_id[project_image_names[dep_image_name]]
            suggestions.append(
                _make_suggestion(dep, src, "medium", f"Image name in {src.name}"),
            )
            matched_deps.add(dep_key)

    # Pass 4: component-reference match (repo references sibling repos)
    for src in sources:
        sid = str(src.id)
        comp_refs = source_component_refs.get(sid, set())
        if not comp_refs:
            continue
        for dep in deployments:
            dep_key = f"{dep['name']}|{dep['namespace']}"
            if dep_key in matched_deps:
                continue
            dep_lower = dep["name"].lower()
            for ref_name in comp_refs:
                match_type = _match_dep_to_component_ref(dep_lower, ref_name)
                if match_type == "exact":
                    suggestions.append(_make_suggestion(
                        dep, src, "high",
                        f"Component {ref_name} managed by {src.name}",
                    ))
                    matched_deps.add(dep_key)
                    break
                if match_type == "contains":
                    suggestions.append(_make_suggestion(
                        dep, src, "medium",
                        f"Component {ref_name} referenced in {src.name}",
                    ))
                    matched_deps.add(dep_key)
                    break

    return suggestions


def _make_suggestion(dep: dict, src: Any, confidence: str, reason: str) -> dict[str, Any]:
    return {
        "deployment_name": dep["name"],
        "deployment_namespace": dep["namespace"],
        "context_source_id": str(src.id),
        "cluster_id": dep["cluster_id"],
        "is_infrastructure": False,
        "confidence": confidence,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Strategy 4: RBAC-based operator discovery (product-agnostic)
# ---------------------------------------------------------------------------

_SYSTEM_NS_PREFIXES = (
    "kube-", "openshift-kube-", "openshift-authentication",
    "openshift-apiserver", "openshift-etcd", "openshift-controller",
)

_SKIP_API_GROUPS = frozenset({
    "", "authentication.k8s.io", "authorization.k8s.io",
    "rbac.authorization.k8s.io", "certificates.k8s.io",
    "coordination.k8s.io", "discovery.k8s.io", "events.k8s.io",
    "flowcontrol.apiserver.k8s.io", "node.k8s.io", "scheduling.k8s.io",
    "storage.k8s.io", "admissionregistration.k8s.io",
    "apiextensions.k8s.io", "apiregistration.k8s.io",
    "apps", "batch", "policy", "networking.k8s.io",
    "autoscaling", "v1",
})

_WRITE_VERBS = frozenset({"*", "create", "update", "patch"})


async def _build_rbac_crd_map(
    cluster: ProjectCluster,
    deployments: list[dict[str, Any]],
) -> dict[str, dict]:
    """Build a CRD-name → operator-deployment map via RBAC.

    Algorithm (3 lookups, all cacheable):
      1. ClusterRoleBinding → (ServiceAccount, ClusterRole)
      2. ClusterRole rules  → which custom CRDs the SA can *write* to
      3. Deployment spec    → which SA the deployment uses

    Returns ``{ "datascienceclusters.datasciencecluster.opendatahub.io":
                 { "name": "opendatahub-operator-controller-manager", ... } }``
    """
    # Step 1: ClusterRoleBindings → SA → ClusterRole names
    try:
        crb_data = await asyncio.wait_for(
            kube_client.list_cluster_role_bindings(cluster),
            timeout=15,
        )
    except Exception:
        logger.debug("RBAC: could not list ClusterRoleBindings on %s", cluster.name)
        return {}

    sa_roles: dict[tuple[str, str], list[str]] = {}
    for crb in crb_data.get("items", []):
        role_name = crb.get("roleRef", {}).get("name", "")
        if not role_name:
            continue
        for subj in crb.get("subjects", []):
            if subj.get("kind") != "ServiceAccount":
                continue
            key = (subj.get("namespace", ""), subj["name"])
            sa_roles.setdefault(key, []).append(role_name)

    # Step 2: for each ClusterRole, find custom CRDs the SA can write
    # Collect unique role names needed (skip system namespaces early)
    needed_roles: set[str] = set()
    filtered_sa_roles: dict[tuple[str, str], list[str]] = {}
    for (ns, sa_name), roles in sa_roles.items():
        if any(ns.startswith(p) for p in _SYSTEM_NS_PREFIXES):
            continue
        filtered_sa_roles[(ns, sa_name)] = roles
        needed_roles.update(roles)

    # Fetch all ClusterRoles in bulk (single HTTP client, connection reuse)
    bulk_roles = await kube_client.get_cluster_roles_bulk(
        cluster, list(needed_roles),
    )
    seen_roles: dict[str, list[dict] | None] = {
        name: data.get("rules", []) if data else None
        for name, data in bulk_roles.items()
    }

    crd_to_sas: dict[str, set[tuple[str, str]]] = {}
    for (ns, sa_name), roles in filtered_sa_roles.items():
        for role_name in roles:
            rules = seen_roles.get(role_name)
            if not rules:
                continue

            for rule in rules:
                verbs = set(rule.get("verbs", []))
                if not verbs & _WRITE_VERBS:
                    continue
                for grp in rule.get("apiGroups", []):
                    if grp in _SKIP_API_GROUPS:
                        continue
                    for res in rule.get("resources", []):
                        if "/" in res:
                            continue
                        crd_key = f"{res}.{grp}"
                        crd_to_sas.setdefault(crd_key, set()).add((ns, sa_name))

    # Step 3: map SA → deployment (using already-fetched deployment data)
    sa_to_dep: dict[tuple[str, str], dict] = {}
    for dep in deployments:
        sa = dep.get("service_account", "default")
        sa_key = (dep["namespace"], sa)
        sa_to_dep[sa_key] = dep

    # Build final map: CRD → operator deployment
    # Prefer the SA with the narrowest permissions (fewest CRDs)
    sa_crd_count: dict[tuple[str, str], int] = {}
    for sas in crd_to_sas.values():
        for sa_key in sas:
            sa_crd_count[sa_key] = sa_crd_count.get(sa_key, 0) + 1

    crd_to_operator: dict[str, dict] = {}
    for crd_key, sas in crd_to_sas.items():
        best_dep = None
        best_count = float("inf")
        for sa_key in sas:
            dep = sa_to_dep.get(sa_key)
            if not dep:
                continue
            count = sa_crd_count.get(sa_key, 0)
            if count < best_count:
                best_dep = dep
                best_count = count
        if best_dep:
            crd_to_operator[crd_key] = best_dep

    logger.info(
        "RBAC map for cluster %s: %d CRDs → %d unique operators",
        cluster.name,
        len(crd_to_operator),
        len({d["name"] for d in crd_to_operator.values()}),
    )
    return crd_to_operator


def _pluralize_kind(kind: str) -> str:
    """Best-effort English pluralization for a CRD kind name.

    Handles the common cases: -s/-es already present, -y→-ies, -s/-x/-ch/-sh→-es.
    """
    lower = kind.lower()
    if lower.endswith(("s", "es")):
        return lower
    if lower.endswith("y") and len(lower) > 1 and lower[-2] not in "aeiou":
        return lower[:-1] + "ies"
    if lower.endswith(("s", "x", "ch", "sh")):
        return lower + "es"
    return lower + "s"


def _crd_name_from_ref(api_version: str, kind: str) -> str:
    """Derive a CRD fully-qualified name from apiVersion + kind.

    Example: apiVersion="components.platform.opendatahub.io/v1alpha1", kind="Kserve"
    → "kserves.components.platform.opendatahub.io"
    """
    if "/" in api_version:
        group = api_version.split("/")[0]
    else:
        group = ""
    plural = _pluralize_kind(kind)
    return f"{plural}.{group}" if group else plural


# ---------------------------------------------------------------------------
# Hierarchy computation (direct + indirect parent-child edges)
# ---------------------------------------------------------------------------

_OWNERSHIP_LABELS = (
    "app.kubernetes.io/managed-by",
    "app.kubernetes.io/part-of",
)


async def compute_hierarchy_edges(
    db: AsyncSession, project_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Compute parent-child edges between deployments using K8s metadata.

    Strategy 1 – **Direct ownerRef**: child's ownerRef UID matches a parent
    deployment's UID.

    Strategy 2 – **Label-based**: child's ``managed-by`` / ``part-of`` label
    matches a deployment name.

    Strategy 3 – **Indirect ownerRef via CR**: child's ownerRef points to a
    Custom Resource.  Walk the CR's ownerRef chain (max 2 hops) looking for a
    known deployment.

    Strategy 4 – **RBAC-based** (fallback when Strategy 3 hits a dead end):
    Every operator must have RBAC write permissions on the CRDs it manages.
    Build a CRD → operator deployment map via
    ``ClusterRoleBinding → ClusterRole rules → ServiceAccount → Deployment``
    and look up the dead-end CR's CRD name in that map.
    """
    deployments = await get_live_deployments(db, project_id)
    if not deployments:
        return []

    # ---- lookup structures ----
    uid_to_dep: dict[str, dict] = {}
    for d in deployments:
        if d.get("uid"):
            uid_to_dep[d["uid"]] = d

    # name -> dep, including stripped-suffix variants
    name_to_dep: dict[str, dict] = {}
    for d in deployments:
        key = d["name"].lower()
        name_to_dep[key] = d
        for suffix in _DEPLOY_SUFFIXES:
            if suffix and key.endswith(suffix):
                name_to_dep[key[: -len(suffix)]] = d

    # Group deployments by cluster_id for the indirect fetch step
    cluster_map: dict[str, ProjectCluster] = {}
    result = await db.execute(
        select(ProjectCluster).where(ProjectCluster.project_id == project_id)
    )
    for c in result.scalars().all():
        cluster_map[str(c.id)] = c

    edges: list[dict[str, Any]] = []
    resolved: set[str] = set()

    # ownerRef UIDs that don't point to any deployment (candidates for step 3)
    unresolved_refs: list[tuple[dict, dict]] = []

    # ---- Strategy 1: direct ownerRef UID match ----
    for dep in deployments:
        dep_key = f"{dep['name']}|{dep['namespace']}"
        for ref in dep.get("owner_references", []):
            parent = uid_to_dep.get(ref["uid"])
            if parent and parent["name"] != dep["name"]:
                edges.append({
                    "parent_name": parent["name"],
                    "parent_namespace": parent["namespace"],
                    "child_name": dep["name"],
                    "child_namespace": dep["namespace"],
                    "relationship": "direct",
                    "label": f"ownerRef ({ref['kind']})",
                })
                resolved.add(dep_key)
                break
            if not parent and ref.get("uid"):
                unresolved_refs.append((dep, ref))

    # ---- Strategy 2: label-based ownership ----
    for dep in deployments:
        dep_key = f"{dep['name']}|{dep['namespace']}"
        if dep_key in resolved:
            continue
        labels = dep.get("labels", {})
        for lbl in _OWNERSHIP_LABELS:
            val = (labels.get(lbl) or "").lower()
            if not val:
                continue
            parent = name_to_dep.get(val)
            if parent and parent["name"] != dep["name"]:
                edges.append({
                    "parent_name": parent["name"],
                    "parent_namespace": parent["namespace"],
                    "child_name": dep["name"],
                    "child_namespace": dep["namespace"],
                    "relationship": "direct",
                    "label": f"label ({lbl.split('/')[-1]})",
                })
                resolved.add(dep_key)
                break

    # ---- Strategy 3 + 4: indirect via CR chain / RBAC fallback ----
    cr_cache: dict[tuple, dict | None] = {}

    async def _fetch_cr_meta(
        cluster_id: str, api_version: str, kind: str, name: str, namespace: str,
    ) -> dict | None:
        cache_key = (cluster_id, api_version, kind, name, namespace)
        if cache_key in cr_cache:
            return cr_cache[cache_key]
        cluster = cluster_map.get(cluster_id)
        if not cluster:
            cr_cache[cache_key] = None
            return None
        try:
            data = await asyncio.wait_for(
                kube_client.get_resource_by_ref(
                    cluster, api_version, kind, name, namespace,
                ),
                timeout=10,
            )
            cr_cache[cache_key] = data.get("metadata", {})
        except Exception:
            logger.debug(
                "Could not fetch %s/%s %s in %s", api_version, kind, name, namespace,
            )
            cr_cache[cache_key] = None
        return cr_cache[cache_key]

    # Pre-fetch all first-level CRs in bulk (single HTTP client per cluster)
    pending_refs = [
        (dep, ref) for dep, ref in unresolved_refs
        if f"{dep['name']}|{dep['namespace']}" not in resolved
    ]
    by_cluster: dict[str, list[tuple[int, dict, dict]]] = {}
    for i, (dep, ref) in enumerate(pending_refs):
        by_cluster.setdefault(dep["cluster_id"], []).append((i, dep, ref))

    async def _bulk_fetch_cluster(cluster_id: str, items: list) -> None:
        cluster = cluster_map.get(cluster_id)
        if not cluster:
            return
        requests = [
            (ref.get("api_version", ""), ref["kind"], ref["name"], dep["namespace"])
            for _, dep, ref in items
        ]
        results = await kube_client.get_resources_bulk(cluster, requests)
        for (_, dep, ref), result in zip(items, results):
            cache_key = (
                cluster_id, ref.get("api_version", ""),
                ref["kind"], ref["name"], dep["namespace"],
            )
            cr_cache[cache_key] = result.get("metadata", {}) if result else None

    await asyncio.gather(
        *[_bulk_fetch_cluster(cid, items) for cid, items in by_cluster.items()],
    )

    # Build RBAC maps eagerly and in parallel for all clusters that have unresolved refs
    rbac_cluster_ids = {
        dep["cluster_id"] for dep, _ in unresolved_refs
        if f"{dep['name']}|{dep['namespace']}" not in resolved
    }
    rbac_maps: dict[str, dict[str, dict]] = {}

    async def _build_one_rbac(cid: str) -> tuple[str, dict[str, dict]]:
        cluster = cluster_map.get(cid)
        if not cluster:
            return cid, {}
        try:
            m = await asyncio.wait_for(
                _build_rbac_crd_map(cluster, deployments), timeout=30,
            )
            return cid, m
        except asyncio.TimeoutError:
            logger.warning("RBAC map build timed out for cluster %s", cluster.name)
            return cid, {}

    rbac_results = await asyncio.gather(
        *[_build_one_rbac(cid) for cid in rbac_cluster_ids],
    )
    rbac_maps = dict(rbac_results)

    for dep, ref in unresolved_refs:
        dep_key = f"{dep['name']}|{dep['namespace']}"
        if dep_key in resolved:
            continue

        cr_api_version = ref.get("api_version", "")
        cr_kind = ref["kind"]

        cr_meta = await _fetch_cr_meta(
            dep["cluster_id"], cr_api_version, cr_kind, ref["name"], dep["namespace"],
        )

        # Strategy 3: walk up the CR's ownerReferences (up to 2 hops)
        found_parent = None
        via_path = f"{cr_kind}/{ref['name']}"
        if cr_meta:
            current_meta = cr_meta
            for _hop in range(2):
                cr_owner_refs = current_meta.get("ownerReferences", [])
                for cr_ref in cr_owner_refs:
                    parent = uid_to_dep.get(cr_ref.get("uid", ""))
                    if parent and parent["name"] != dep["name"]:
                        found_parent = parent
                        break
                if found_parent:
                    break

                if not cr_owner_refs:
                    break
                next_ref = cr_owner_refs[0]
                next_meta = await _fetch_cr_meta(
                    dep["cluster_id"],
                    next_ref.get("apiVersion", ""),
                    next_ref.get("kind", ""),
                    next_ref.get("name", ""),
                    current_meta.get("namespace", dep["namespace"]),
                )
                if not next_meta:
                    break
                via_path += f" → {next_ref.get('kind', '')}/{next_ref.get('name', '')}"
                current_meta = next_meta

            # Strategy 3b: check the CR's labels
            if not found_parent:
                cr_labels = cr_meta.get("labels", {})
                for lbl in _OWNERSHIP_LABELS:
                    val = (cr_labels.get(lbl) or "").lower()
                    if val:
                        found_parent = name_to_dep.get(val)
                        if found_parent and found_parent["name"] != dep["name"]:
                            break
                        found_parent = None

        # Strategy 4: RBAC-based lookup (dead-end CR → CRD name → operator)
        rbac_resolved = False
        if not found_parent:
            crd_name = _crd_name_from_ref(cr_api_version, cr_kind)
            rbac_map = rbac_maps.get(dep["cluster_id"], {})
            operator_dep = rbac_map.get(crd_name)
            if operator_dep and operator_dep["name"] != dep["name"]:
                found_parent = operator_dep
                via_path = f"RBAC ({crd_name})"
                rbac_resolved = True

        if found_parent:
            edges.append({
                "parent_name": found_parent["name"],
                "parent_namespace": found_parent["namespace"],
                "child_name": dep["name"],
                "child_namespace": dep["namespace"],
                "relationship": "indirect",
                "label": f"via {via_path}" if not rbac_resolved else via_path,
            })
            resolved.add(dep_key)

    return edges


# ---------------------------------------------------------------------------
# Mapping CRUD
# ---------------------------------------------------------------------------


async def list_mappings(
    db: AsyncSession, project_id: uuid.UUID
) -> list[ServiceMapping]:
    result = await db.execute(
        select(ServiceMapping)
        .where(ServiceMapping.project_id == project_id)
        .options(selectinload(ServiceMapping.context_source))
    )
    return list(result.scalars().all())


async def bulk_create_mappings(
    db: AsyncSession,
    project_id: uuid.UUID,
    items: list[dict[str, Any]],
) -> list[ServiceMapping]:
    """Create multiple mappings at once (from wizard)."""
    mappings = []
    for item in items:
        m = ServiceMapping(
            project_id=project_id,
            cluster_id=uuid.UUID(item["cluster_id"]),
            deployment_name=item["deployment_name"],
            deployment_namespace=item.get("deployment_namespace", "default"),
            context_source_id=(
                uuid.UUID(item["context_source_id"])
                if item.get("context_source_id")
                else None
            ),
            is_infrastructure=item.get("is_infrastructure", False),
            node_position_x=item.get("node_position_x", 0.0),
            node_position_y=item.get("node_position_y", 0.0),
        )
        db.add(m)
        mappings.append(m)
    await db.flush()
    await db.commit()
    for m in mappings:
        await db.refresh(m)
    return mappings


async def update_mapping(
    db: AsyncSession,
    mapping: ServiceMapping,
    **kwargs: Any,
) -> ServiceMapping:
    for k, v in kwargs.items():
        if hasattr(mapping, k):
            setattr(mapping, k, v)
    await db.flush()
    await db.commit()
    await db.refresh(mapping)
    return mapping


async def delete_mapping(db: AsyncSession, mapping: ServiceMapping) -> None:
    await db.delete(mapping)
    await db.commit()


async def get_mapping(
    db: AsyncSession, project_id: uuid.UUID, mapping_id: uuid.UUID
) -> ServiceMapping | None:
    result = await db.execute(
        select(ServiceMapping).where(
            ServiceMapping.id == mapping_id,
            ServiceMapping.project_id == project_id,
        )
    )
    return result.scalar_one_or_none()


async def delete_all_mappings(db: AsyncSession, project_id: uuid.UUID) -> None:
    """Remove all mappings (and cascaded edges) for a project."""
    await db.execute(
        delete(ServiceMapping).where(ServiceMapping.project_id == project_id)
    )
    await db.commit()


async def bulk_update_positions(
    db: AsyncSession,
    project_id: uuid.UUID,
    positions: list[dict[str, Any]],
) -> None:
    """Update node positions for multiple mappings."""
    for pos in positions:
        await db.execute(
            update(ServiceMapping)
            .where(
                ServiceMapping.id == uuid.UUID(pos["id"]),
                ServiceMapping.project_id == project_id,
            )
            .values(node_position_x=pos["x"], node_position_y=pos["y"])
        )
    await db.commit()


# ---------------------------------------------------------------------------
# Edge CRUD
# ---------------------------------------------------------------------------


async def list_edges(db: AsyncSession, project_id: uuid.UUID) -> list[ServiceEdge]:
    result = await db.execute(
        select(ServiceEdge).where(ServiceEdge.project_id == project_id)
    )
    return list(result.scalars().all())


async def create_edge(
    db: AsyncSession,
    project_id: uuid.UUID,
    source_mapping_id: uuid.UUID,
    target_mapping_id: uuid.UUID,
    label: str | None = None,
) -> ServiceEdge:
    edge = ServiceEdge(
        project_id=project_id,
        source_mapping_id=source_mapping_id,
        target_mapping_id=target_mapping_id,
        label=label,
    )
    db.add(edge)
    await db.flush()
    await db.commit()
    await db.refresh(edge)
    return edge


async def delete_edge(db: AsyncSession, project_id: uuid.UUID, edge_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(ServiceEdge).where(
            ServiceEdge.id == edge_id,
            ServiceEdge.project_id == project_id,
        )
    )
    edge = result.scalar_one_or_none()
    if not edge:
        return False
    await db.delete(edge)
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Version gap
# ---------------------------------------------------------------------------

_SHA_RE = re.compile(r"[0-9a-f]{7,40}")
_SEMVER_RE = re.compile(r"v?\d+\.\d+\.\d+")


def _extract_ref_from_image(image: str) -> tuple[str | None, str]:
    """Try to extract a git-usable ref from a container image tag.

    Returns (ref_or_none, strategy) where strategy is 'sha', 'tag', or 'unknown'.
    """
    tag = image.rsplit(":", 1)[-1] if ":" in image else None
    if not tag or tag == "latest":
        return None, "unknown"

    # sha-abc1234 or just a hex string
    if tag.startswith("sha-"):
        return tag[4:], "sha"
    if _SHA_RE.fullmatch(tag):
        return tag, "sha"

    # Check for SHA suffix after a dash (e.g., v2.15.0-abc1234)
    parts = tag.rsplit("-", 1)
    if len(parts) == 2 and _SHA_RE.fullmatch(parts[1]):
        return parts[1], "sha"

    # semver tag
    if _SEMVER_RE.fullmatch(tag):
        return tag, "tag"

    return None, "unknown"


def _git_gap(clone_path: str, ref: str, strategy: str) -> dict[str, Any]:
    """Count commits between a deployed ref and HEAD in a cloned repo."""
    try:
        if strategy == "tag":
            # Check tag exists
            subprocess.run(
                ["git", "rev-parse", ref],
                cwd=clone_path, capture_output=True, check=True, timeout=10,
            )
        result = subprocess.run(
            ["git", "log", f"{ref}..HEAD", "--oneline"],
            cwd=clone_path, capture_output=True, text=True, check=True, timeout=15,
        )
        lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
        return {"gap_count": len(lines), "status": "current" if len(lines) == 0 else "behind"}
    except Exception:
        logger.debug("git gap calculation failed for ref=%s at %s", ref, clone_path)
        return {"gap_count": None, "status": "unknown"}


async def compute_status_for_mappings(
    db: AsyncSession, project_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Compute live pod health + version gap for all mappings in a project."""
    mappings = await list_mappings(db, project_id)
    deployments = await get_live_deployments(db, project_id)
    dep_map = {(d["name"], d["namespace"], d["cluster_id"]): d for d in deployments}

    statuses: list[dict[str, Any]] = []
    for m in mappings:
        dep_key = (m.deployment_name, m.deployment_namespace, str(m.cluster_id))
        dep = dep_map.get(dep_key, {})

        gap: dict[str, Any] = {"deployed_ref": None, "gap_count": None, "status": "unknown"}

        if dep and m.context_source and not m.is_infrastructure:
            ref, strategy = _extract_ref_from_image(dep.get("image", ""))
            if ref and m.context_source.config:
                clone_path = m.context_source.config.get("clone_path")
                if clone_path:
                    gap_result = await asyncio.to_thread(_git_gap, clone_path, ref, strategy)
                    gap = {"deployed_ref": ref, **gap_result}

        statuses.append(
            {
                "mapping_id": str(m.id),
                "deployment": dep or {
                    "name": m.deployment_name,
                    "namespace": m.deployment_namespace,
                    "image": "unknown",
                    "replicas": 0,
                    "ready_replicas": 0,
                    "status": "failing",
                    "cluster_id": str(m.cluster_id),
                    "cluster_name": "",
                    "uid": "",
                    "owner_references": [],
                    "labels": {},
                },
                "gap": gap,
            }
        )

    return statuses


# ---------------------------------------------------------------------------
# AI context: compact text summary of the system map (DB-only, no live calls)
# ---------------------------------------------------------------------------


async def build_system_map_context(
    db: AsyncSession, project_id: uuid.UUID,
) -> str | None:
    """Build a compact, static summary of the system map for AI prompts.

    Reads only from the database (mappings + context sources). No K8s API
    calls, no hierarchy computation, no live status. This keeps every chat
    message fast and avoids rate-limit pressure on external APIs.

    Live data (health, hierarchy, gaps) is only fetched when the user
    opens the System Map UI or clicks refresh.
    """
    mappings = await list_mappings(db, project_id)
    if not mappings:
        return None

    # Group by context source (repo)
    by_repo: dict[str, list[Any]] = {}
    infra: list[Any] = []
    unlinked: list[Any] = []

    for m in mappings:
        if m.is_infrastructure:
            infra.append(m)
        elif m.context_source:
            key = m.context_source.name
            by_repo.setdefault(key, []).append(m)
        else:
            unlinked.append(m)

    lines: list[str] = []

    for repo_name in sorted(by_repo):
        group = by_repo[repo_name]
        cs = group[0].context_source
        url = f" ({cs.url})" if cs.url else ""
        lines.append(f"### {repo_name}{url}")
        for m in sorted(group, key=lambda x: x.deployment_name):
            lines.append(f"  - {m.deployment_name} ({m.deployment_namespace})")
        lines.append("")

    if unlinked:
        lines.append("### Unlinked Deployments")
        for m in sorted(unlinked, key=lambda x: x.deployment_name):
            lines.append(f"  - {m.deployment_name} ({m.deployment_namespace})")
        lines.append("")

    if infra:
        lines.append(f"### Infrastructure ({len(infra)} services, no source repo)")
        lines.append("")

    if not lines:
        return None

    return "## System Map\n\n" + "\n".join(lines)
