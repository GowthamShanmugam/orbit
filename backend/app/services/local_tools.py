"""Anthropic tool definitions for running local commands in cloned repos.

This gives the AI the ability to execute build commands, test runners, and
scripts locally on the backend server — within the project's cloned repo
directories. Cluster credentials are injected into the environment so that
tools like `kubectl`, `oc`, `go test`, and `make` can connect to attached
clusters.

Safety measures:
  - Commands run with a hard timeout (default 300s).
  - Output is capped to prevent memory exhaustion.
  - Working directory is restricted to the repo clone path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.cluster import ProjectCluster
from app.services.runtime_settings import eff_int
from app.models.context import ContextSource, ContextSourceType
from app.services import cluster_service

logger = logging.getLogger(__name__)

def _tool_definitions() -> list[dict[str, Any]]:
    lt = eff_int("LOCAL_TOOL_DEFAULT_TIMEOUT_SEC")
    lt_max = eff_int("LOCAL_TOOL_MAX_TIMEOUT_SEC")
    return [
        {
            "name": "local_run_command",
            "description": (
                "Run a shell command locally on the server inside a cloned repository directory. "
                "Use this to build code, run tests (e2e, unit, integration), execute Makefiles, "
                "or any command that needs the repo source code and a connection to a cluster. "
                "Cluster credentials are automatically injected into the environment as KUBECONFIG "
                "so tools like kubectl, oc, go test, and make can connect to the cluster. "
                "You MUST specify which repo to run in (by name). "
                "Optionally specify a cluster_name to inject its credentials; if omitted and "
                "only one cluster is attached, that cluster is used automatically. "
                f"Commands time out after {lt} seconds by default."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "repo_name": {
                        "type": "string",
                        "description": "Name of the cloned repository to run the command in (use repo_list_sources to find names).",
                    },
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute (runs via /bin/sh -c).",
                    },
                    "cluster_name": {
                        "type": "string",
                        "description": "Name of the cluster whose credentials to inject. If omitted, the first available cluster is used.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": f"Max seconds to wait (default {lt}, max {lt_max}).",
                    },
                    "subdirectory": {
                        "type": "string",
                        "description": "Subdirectory within the repo to use as working directory (e.g. 'tests/e2e').",
                    },
                },
                "required": ["repo_name", "command"],
            },
        },
    ]


def get_tool_definitions() -> list[dict[str, Any]]:
    return list(_tool_definitions())


def get_tool_activity_label(tool_name: str, tool_input: dict[str, Any]) -> str:
    repo = tool_input.get("repo_name", "repo")
    cmd = tool_input.get("command", "")
    short_cmd = cmd[:60] + ("…" if len(cmd) > 60 else "")
    return f"Running in {repo}: {short_cmd}"


async def execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    project_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    if tool_name != "local_run_command":
        return f"Error: Unknown tool '{tool_name}'"
    try:
        return await _run_command(tool_input, project_id, db)
    except Exception as exc:
        logger.exception("local_run_command failed")
        return f"Error: {exc}"


async def _run_command(
    inp: dict[str, Any],
    project_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    repo_name = inp["repo_name"]
    command = inp["command"]
    timeout = min(
        inp.get("timeout", eff_int("LOCAL_TOOL_DEFAULT_TIMEOUT_SEC")),
        eff_int("LOCAL_TOOL_MAX_TIMEOUT_SEC"),
    )
    subdirectory = inp.get("subdirectory", "")

    clone_path = await _resolve_repo_path(repo_name, project_id, db)
    if clone_path is None:
        return f"Error: Repository '{repo_name}' not found or not cloned. Use repo_list_sources."

    work_dir = clone_path / subdirectory if subdirectory else clone_path
    if not work_dir.is_dir():
        return f"Error: Directory '{work_dir}' does not exist."

    env = _build_env()
    kubeconfig_path = await _inject_cluster_credentials(
        inp.get("cluster_name"), project_id, db, env
    )

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(work_dir),
            env=env,
        )

        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Error: Command timed out after {timeout}s."

        output = stdout.decode(errors="replace")
        max_out = settings.LOCAL_TOOL_MAX_OUTPUT_CHARS
        head = settings.LOCAL_TOOL_TRUNCATE_HEAD_CHARS
        if len(output) > max_out:
            output = (
                output[:head]
                + "\n\n…(truncated middle)…\n\n"
                + output[-(max_out - head) :]
            )

        exit_code = proc.returncode
        header = f"Exit code: {exit_code}\n{'─' * 40}\n"
        return header + output

    finally:
        if kubeconfig_path and os.path.exists(kubeconfig_path):
            try:
                os.unlink(kubeconfig_path)
            except OSError:
                pass


async def _resolve_repo_path(
    repo_name: str, project_id: uuid.UUID, db: AsyncSession
) -> Path | None:
    result = await db.execute(
        select(ContextSource).where(
            ContextSource.project_id == project_id,
            ContextSource.type.in_([
                ContextSourceType.github_repo,
                ContextSourceType.gitlab_repo,
            ]),
        )
    )
    sources = result.scalars().all()
    for source in sources:
        if source.name == repo_name or (source.url and repo_name in source.url):
            clone_path = (source.config or {}).get("clone_path")
            if clone_path:
                p = Path(clone_path)
                if p.is_dir():
                    return p
    return None


def _build_env() -> dict[str, str]:
    """Start from current env, add PATH essentials."""
    env = dict(os.environ)
    extra_paths = [
        "/usr/local/go/bin",
        "/usr/local/bin",
        "/opt/homebrew/bin",
        os.path.expanduser("~/go/bin"),
    ]
    env["PATH"] = ":".join(extra_paths) + ":" + env.get("PATH", "")
    env["HOME"] = os.path.expanduser("~")
    return env


async def _inject_cluster_credentials(
    cluster_name: str | None,
    project_id: uuid.UUID,
    db: AsyncSession,
    env: dict[str, str],
) -> str | None:
    """Write a temporary kubeconfig and set KUBECONFIG in env. Returns the temp file path."""
    cluster = await _pick_cluster(cluster_name, project_id, db)
    if cluster is None:
        return None

    try:
        creds = cluster_service.decrypt_credentials(cluster)
    except Exception as exc:
        logger.warning("Failed to decrypt cluster credentials: %s", exc)
        return None

    api_url = cluster.api_server_url or creds.get("api_server_url", "")
    token = creds.get("token", "")

    if not api_url:
        return None

    kubeconfig = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{
            "name": "orbit-cluster",
            "cluster": {
                "server": api_url,
                "insecure-skip-tls-verify": not creds.get("verify_ssl", True),
            },
        }],
        "users": [{
            "name": "orbit-user",
            "user": {"token": token} if token else {},
        }],
        "contexts": [{
            "name": "orbit-ctx",
            "context": {"cluster": "orbit-cluster", "user": "orbit-user"},
        }],
        "current-context": "orbit-ctx",
    }

    fd, path = tempfile.mkstemp(prefix="orbit-kube-", suffix=".yaml")
    try:
        import yaml
        with os.fdopen(fd, "w") as f:
            yaml.dump(kubeconfig, f)
    except Exception:
        with os.fdopen(fd, "w") as f:
            json.dump(kubeconfig, f)

    env["KUBECONFIG"] = path
    return path


async def _pick_cluster(
    cluster_name: str | None, project_id: uuid.UUID, db: AsyncSession
) -> ProjectCluster | None:
    clusters = await cluster_service.list_clusters(db, project_id)
    if not clusters:
        return None
    if cluster_name:
        return next((c for c in clusters if c.name == cluster_name), None)
    return clusters[0]
