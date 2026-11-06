"""Checkout PR/MR head into a temp tree without touching the main clone.

Main clone stays on the configured branch (usually main). Review reads use a
separate directory under ``REPO_CLONE_DIR/<project>/pr-checkouts/``.

GitHub: fetch ``pull/<n>/head`` from the base repo (works for fork PRs).
GitLab: fetch ``merge-requests/<iid>/head`` from the target project.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import re
import shutil
import subprocess
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.models.context import ContextSource, ContextSourceType, SessionLayer, SessionLayerType
from app.models.skill import SkillPlugin, UserPluginConfig
from app.services.github_service import _git_executable
from app.services.session_layer_prompt import _parse_github_pr, _parse_gitlab_mr

logger = logging.getLogger(__name__)

# session_id -> {repo_name: CheckoutInfo}
_SESSION_OVERLAYS: dict[uuid.UUID, dict[str, "CheckoutInfo"]] = {}
# layer_id -> (percent 0-100, stage label) while a checkout is in flight
_LAYER_PROGRESS: dict[uuid.UUID, tuple[int, str]] = {}
_GIT_PCT_RE = re.compile(r"(\d+)%")


@dataclass(frozen=True)
class CheckoutInfo:
    path: str
    sha: str
    provider: str
    number: int
    branch: str
    base_repo: str
    repo_name: str


def get_session_overlays(session_id: uuid.UUID) -> dict[str, CheckoutInfo]:
    return dict(_SESSION_OVERLAYS.get(session_id, {}))


def clear_session_overlays(session_id: uuid.UUID) -> None:
    _SESSION_OVERLAYS.pop(session_id, None)


def resolve_pr_layer_url(layer: SessionLayer) -> str | None:
    """Prefer reference_url; fall back to label when the user pasted the URL there."""
    for candidate in (layer.reference_url, layer.label):
        if not candidate or not str(candidate).strip():
            continue
        text = str(candidate).strip()
        if _parse_github_pr(text) or _parse_gitlab_mr(text):
            return text
    return None


def _set_layer_checkout_status(
    layer: SessionLayer,
    *,
    status: str,
    info: CheckoutInfo | None = None,
    error: str | None = None,
    progress: int | None = None,
    stage: str | None = None,
) -> None:
    cc = dict(layer.cached_content or {})
    cc["pr_checkout_status"] = status
    if progress is not None:
        cc["pr_checkout_progress"] = max(0, min(100, int(progress)))
    if stage is not None:
        cc["pr_checkout_stage"] = stage
    if status == "ready":
        cc["pr_checkout_progress"] = 100
        cc["pr_checkout_stage"] = "Ready"
    if status == "error":
        cc.pop("pr_checkout_progress", None)
    if error:
        cc["pr_checkout_error"] = error[:500]
    else:
        cc.pop("pr_checkout_error", None)
    if info:
        cc["pr_checkout"] = {
            "path": info.path,
            "sha": info.sha,
            "provider": info.provider,
            "number": info.number,
            "branch": info.branch,
            "base_repo": info.base_repo,
            "repo_name": info.repo_name,
        }
    layer.cached_content = cc
    flag_modified(layer, "cached_content")


def _note_progress(layer_id: uuid.UUID | None, percent: int, stage: str) -> None:
    if layer_id is None:
        return
    pct = max(0, min(100, int(percent)))
    prev = _LAYER_PROGRESS.get(layer_id)
    if prev and prev[0] > pct and pct < 100:
        # Don't jump backwards except when finishing.
        pct = prev[0]
    _LAYER_PROGRESS[layer_id] = (pct, stage)


def _map_git_progress(line: str) -> tuple[int, str] | None:
    """Map a git --progress stderr line to overall percent + stage."""
    text = line.strip()
    if not text:
        return None
    m = _GIT_PCT_RE.search(text)
    if not m:
        lower = text.lower()
        if "counting objects" in lower:
            return 22, "Counting objects"
        if "compressing objects" in lower:
            return 28, "Compressing objects"
        return None
    git_pct = int(m.group(1))
    lower = text.lower()
    if "receiving objects" in lower:
        # Keep headroom so 100% receiving is not a false "almost done" freeze.
        return 25 + int(git_pct * 0.55), "Downloading objects"
    if "resolving deltas" in lower:
        return 80 + int(git_pct * 0.1), "Resolving deltas"
    if "checking out" in lower or "updating files" in lower:
        return 90 + int(git_pct * 0.08), "Checking out files"
    return 25 + int(git_pct * 0.55), "Fetching"


def overlay_path_for_repo(session_id: uuid.UUID | None, repo_name: str) -> Path | None:
    if session_id is None:
        return None
    info = _SESSION_OVERLAYS.get(session_id, {}).get(repo_name)
    if not info:
        return None
    p = Path(info.path)
    return p if p.is_dir() else None


def _ssh_to_https(url: str) -> str:
    """Convert git@host:path or ssh:// URLs to https://host/path.git."""
    raw = (url or "").strip()
    m = re.match(r"^git@([^:]+):(.+)$", raw)
    if m:
        host, path = m.group(1), m.group(2).lstrip("/")
        if not path.endswith(".git"):
            path = f"{path}.git"
        return f"https://{host}/{path}"
    m = re.match(r"^ssh://(?:git@)?([^/]+)/(.+)$", raw)
    if m:
        host, path = m.group(1), m.group(2).lstrip("/")
        if not path.endswith(".git"):
            path = f"{path}.git"
        return f"https://{host}/{path}"
    return raw


def _auth_https_url(url: str, token: str | None) -> str:
    https = _ssh_to_https(url)
    if not token or not https.startswith("https://"):
        return https
    return https.replace("https://", f"https://oauth2:{token}@", 1)


def _normalize_repo_key(url_or_path: str) -> str:
    s = (url_or_path or "").strip().rstrip("/")
    s = re.sub(r"^https?://", "", s, flags=re.I)
    s = re.sub(r"^[^/]+/", "", s, count=1)  # drop host
    if s.endswith(".git"):
        s = s[:-4]
    return s.lower()


def _repo_keys_match(a: str, b: str) -> bool:
    ka, kb = _normalize_repo_key(a), _normalize_repo_key(b)
    if not ka or not kb:
        return False
    return ka == kb or ka.endswith("/" + kb) or kb.endswith("/" + ka) or ka in kb or kb in ka


async def _github_token(db: AsyncSession, user_id: uuid.UUID) -> str | None:
    result = await db.execute(
        select(UserPluginConfig)
        .join(SkillPlugin, SkillPlugin.id == UserPluginConfig.plugin_id)
        .where(
            SkillPlugin.slug == "github",
            UserPluginConfig.user_id == user_id,
            UserPluginConfig.enabled,
        )
    )
    cfg = result.scalar_one_or_none()
    if not cfg or not cfg.config_values:
        return getattr(settings, "GITHUB_TOKEN", None)
    return cfg.config_values.get("GITHUB_PERSONAL_ACCESS_TOKEN") or getattr(
        settings, "GITHUB_TOKEN", None
    )


async def _gitlab_config(db: AsyncSession, user_id: uuid.UUID) -> tuple[str | None, str, bool]:
    result = await db.execute(
        select(UserPluginConfig)
        .join(SkillPlugin, SkillPlugin.id == UserPluginConfig.plugin_id)
        .where(
            SkillPlugin.slug == "gitlab",
            UserPluginConfig.user_id == user_id,
            UserPluginConfig.enabled,
        )
    )
    cfg = result.scalar_one_or_none()
    api = "https://gitlab.com/api/v4"
    verify = True
    if not cfg or not cfg.config_values:
        return None, api, verify
    token = (cfg.config_values.get("GITLAB_PERSONAL_ACCESS_TOKEN") or "").strip() or None
    raw_api = (cfg.config_values.get("GITLAB_API_URL") or api).strip().rstrip("/")
    if "/api/" not in (urlparse(raw_api).path or ""):
        raw_api = f"{raw_api}/api/v4"
    api = raw_api
    raw_verify = cfg.config_values.get("GITLAB_SSL_VERIFY")
    if raw_verify is not None and str(raw_verify).strip() != "":
        verify = str(raw_verify).strip().lower() in ("1", "true", "yes", "on")
    else:
        verify = "gitlab.com" in api.lower()
    return token, api, verify


async def _find_matching_source(
    db: AsyncSession,
    project_id: uuid.UUID,
    base_repo: str,
    preferred_type: ContextSourceType | None = None,
) -> ContextSource | None:
    types = [ContextSourceType.github_repo, ContextSourceType.gitlab_repo]
    result = await db.execute(
        select(ContextSource).where(
            ContextSource.project_id == project_id,
            ContextSource.type.in_(types),
        )
    )
    sources = list(result.scalars().all())
    matches = [s for s in sources if s.url and _repo_keys_match(s.url, base_repo)]
    if not matches:
        matches = [s for s in sources if _repo_keys_match(s.name, base_repo.split("/")[-1])]
    if preferred_type:
        typed = [s for s in matches if s.type == preferred_type]
        if typed:
            return typed[0]
    return matches[0] if matches else None


def _checkout_dir(project_id: uuid.UUID, source_id: uuid.UUID | str, number: int, sha: str) -> Path:
    short = (sha or "unknown")[:12]
    return (
        Path(settings.REPO_CLONE_DIR)
        / str(project_id)
        / "pr-checkouts"
        / f"{source_id}-pr-{number}-{short}"
    )


def _find_pr_checkout(project_id: uuid.UUID, source_id: uuid.UUID | str, number: int) -> Path | None:
    """Return an existing MR checkout. A later Focus click reuses it."""
    root = Path(settings.REPO_CLONE_DIR) / str(project_id) / "pr-checkouts"
    if not root.is_dir():
        return None
    prefix = f"{source_id}-pr-{number}-"
    found = [
        path
        for path in root.iterdir()
        if path.is_dir() and path.name.startswith(prefix) and (path / ".git").exists()
    ]
    if not found:
        return None
    return max(found, key=lambda path: path.stat().st_mtime)


def _head_sha(repo_dir: Path) -> str | None:
    try:
        proc = subprocess.run(
            [_git_executable(), "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        logger.debug("rev-parse failed for %s", repo_dir, exc_info=True)
    return None


_GIT_FETCH_TIMEOUT_SEC = 180


def _run_git_with_progress(
    cmd: list[str],
    *,
    env: dict[str, str],
    layer_id: uuid.UUID | None,
    default_stage: str,
    timeout_sec: int = _GIT_FETCH_TIMEOUT_SEC,
) -> tuple[int, str]:
    """Run git, parse ``--progress`` on stderr, return (exit_code, stderr_tail)."""
    import os
    import select
    import time

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert proc.stderr is not None
    err_chunks: list[str] = []
    buf = b""
    started = time.monotonic()
    last_beat = started
    fd = proc.stderr.fileno()
    try:
        while True:
            if time.monotonic() - started > timeout_sec:
                proc.kill()
                proc.wait(timeout=5)
                return 124, f"timed out after {timeout_sec}s\n" + "\n".join(err_chunks[-20:])
            ready, _, _ = select.select([fd], [], [], 0.5)
            if not ready:
                # Heartbeat so UI does not look frozen while git is silent.
                if time.monotonic() - last_beat >= 2:
                    cur = _LAYER_PROGRESS.get(layer_id, (40, default_stage))[0]
                    _note_progress(
                        layer_id,
                        min(88, cur + 1),
                        f"{default_stage} (still working…)",
                    )
                    last_beat = time.monotonic()
                if proc.poll() is not None:
                    break
                continue
            chunk = os.read(fd, 256)
            if not chunk:
                break
            last_beat = time.monotonic()
            buf += chunk
            # Git progress uses carriage returns.
            parts = re.split(rb"[\r\n]", buf)
            buf = parts[-1]
            for raw in parts[:-1]:
                line = raw.decode(errors="replace").strip()
                if not line:
                    continue
                err_chunks.append(line)
                mapped = _map_git_progress(line)
                if mapped:
                    _note_progress(layer_id, mapped[0], mapped[1])
                else:
                    _note_progress(
                        layer_id,
                        _LAYER_PROGRESS.get(layer_id, (35, default_stage))[0],
                        default_stage,
                    )
        if buf.strip():
            err_chunks.append(buf.decode(errors="replace").strip())
        code = proc.wait(timeout=5)
        return code, "\n".join(err_chunks[-20:])
    finally:
        if proc.poll() is None:
            with suppress(Exception):
                proc.kill()


def _remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        with suppress(OSError):
            path.unlink()


def _checkout_via_existing_clone_sync(
    *,
    main_clone: Path,
    dest: Path,
    fetch_ref: str,
    expected_sha: str | None,
    layer_id: uuid.UUID | None,
    https_fetch_url: str | None = None,
    ssl_verify: bool = True,
) -> None:
    """Fetch MR/PR ref into the existing clone, then add a detached worktree at *dest*.

    Prefers HTTPS+token fetch into the local object store (SSH to corporate GitLab
    often resets). Falls back to ``origin`` only if HTTPS is unavailable.
    Does not change the main clone's checked-out branch.
    """
    import os

    git = _git_executable()
    main_clone = main_clone.resolve()
    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if not ssl_verify:
        env["GIT_SSL_NO_VERIFY"] = "1"

    if dest.exists() and (dest / ".git").exists():
        current = _head_sha(dest)
        if expected_sha and current and current.startswith(expected_sha[:12]):
            _note_progress(layer_id, 100, "Ready")
            return
        # Drop stale worktree / partial checkout.
        subprocess.run(
            [git, "-C", str(main_clone), "worktree", "remove", "--force", str(dest)],
            capture_output=True,
            check=False,
            env=env,
        )
        _remove_path(dest)

    # Clean leftover tmp from older HTTPS clone attempts.
    tmp = dest.parent / f".{dest.name}.tmp"
    _remove_path(tmp)

    fetch_errors: list[str] = []
    fetch_ok = False

    # 1) HTTPS URL fetch (works when SSH port 22 is blocked/reset).
    if https_fetch_url and https_fetch_url.startswith("https://"):
        _note_progress(layer_id, 20, "Fetching PR head (HTTPS)")
        code, err = _run_git_with_progress(
            [
                git,
                "-C",
                str(main_clone),
                "fetch",
                "--progress",
                "--force",
                https_fetch_url,
                fetch_ref,
            ],
            env=env,
            layer_id=layer_id,
            default_stage="Fetching PR head (HTTPS)",
        )
        if code == 0:
            fetch_ok = True
        else:
            fetch_errors.append(f"https: {err}")
            logger.warning("HTTPS fetch into local clone failed: %s", err[:300])

    # 2) Fall back to configured origin (often SSH).
    if not fetch_ok:
        _note_progress(layer_id, 25, "Fetching PR head (origin)")
        code, err = _run_git_with_progress(
            [
                git,
                "-C",
                str(main_clone),
                "fetch",
                "--progress",
                "--force",
                "origin",
                fetch_ref,
            ],
            env=env,
            layer_id=layer_id,
            default_stage="Fetching PR head (origin)",
        )
        if code == 0:
            fetch_ok = True
        else:
            fetch_errors.append(f"origin: {err}")

    if not fetch_ok:
        raise RuntimeError(
            f"git fetch {fetch_ref} in local clone failed: " + " | ".join(fetch_errors)
        )

    target = expected_sha or "FETCH_HEAD"
    _note_progress(layer_id, 92, "Creating worktree")
    add = subprocess.run(
        [git, "-C", str(main_clone), "worktree", "add", "--detach", str(dest), target],
        capture_output=True,
        check=False,
        text=True,
        env=env,
    )
    if add.returncode != 0:
        # Retry with FETCH_HEAD if sha tip was missing locally.
        if expected_sha:
            add = subprocess.run(
                [
                    git,
                    "-C",
                    str(main_clone),
                    "worktree",
                    "add",
                    "--detach",
                    str(dest),
                    "FETCH_HEAD",
                ],
                capture_output=True,
                check=False,
                text=True,
                env=env,
            )
        if add.returncode != 0:
            raise RuntimeError(f"git worktree add failed: {add.stderr.strip()}")

    _note_progress(layer_id, 100, "Ready")


def _clone_pr_ref_sync(
    *,
    clone_url: str,
    dest: Path,
    token: str | None,
    fetch_ref: str,
    expected_sha: str | None,
    ssl_verify: bool = True,
    layer_id: uuid.UUID | None = None,
    existing_clone: Path | None = None,
) -> None:
    """Checkout PR/MR head into *dest* without changing the main working tree."""
    import os

    auth_url = _auth_https_url(clone_url, token)

    if existing_clone and existing_clone.is_dir() and (existing_clone / ".git").exists():
        try:
            _checkout_via_existing_clone_sync(
                main_clone=existing_clone,
                dest=dest,
                fetch_ref=fetch_ref,
                expected_sha=expected_sha,
                layer_id=layer_id,
                https_fetch_url=auth_url if auth_url.startswith("https://") else None,
                ssl_verify=ssl_verify,
            )
            return
        except Exception as exc:
            logger.warning(
                "Local-clone PR checkout failed (%s); falling back to standalone HTTPS clone",
                exc,
            )

    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    lock_path = dest.parent / f".{dest.name}.orbit-pr.lock"
    # Standalone HTTPS + token clone (SSH often hangs / resets non-interactively).
    git = _git_executable()
    env = os.environ.copy()
    if not ssl_verify:
        env["GIT_SSL_NO_VERIFY"] = "1"

    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

        if dest.exists() and (dest / ".git").exists():
            current = _head_sha(dest)
            if expected_sha and current and current.startswith(expected_sha[:12]):
                _note_progress(layer_id, 100, "Ready")
                return
            _remove_path(dest)

        tmp = dest.parent / f".{dest.name}.tmp"
        _remove_path(tmp)
        tmp.mkdir(parents=True)

        _note_progress(layer_id, 15, "Preparing checkout")
        init = subprocess.run(
            [git, "init", str(tmp)],
            capture_output=True,
            check=False,
            text=True,
            env=env,
        )
        if init.returncode != 0:
            _remove_path(tmp)
            raise RuntimeError(f"git init failed: {init.stderr.strip()}")

        remote = subprocess.run(
            [git, "-C", str(tmp), "remote", "add", "origin", auth_url],
            capture_output=True,
            check=False,
            text=True,
            env=env,
        )
        if remote.returncode != 0:
            _remove_path(tmp)
            raise RuntimeError(f"git remote add failed: {remote.stderr.strip()}")

        _note_progress(layer_id, 20, "Downloading objects")
        code, err = _run_git_with_progress(
            [
                git,
                "-C",
                str(tmp),
                "fetch",
                "--progress",
                "--depth",
                "1",
                "origin",
                fetch_ref,
            ],
            env=env,
            layer_id=layer_id,
            default_stage="Downloading objects",
        )
        if code != 0:
            _remove_path(tmp)
            raise RuntimeError(f"git fetch {fetch_ref} failed: {err}")

        _note_progress(layer_id, 92, "Checking out files")
        checkout = subprocess.run(
            [git, "-C", str(tmp), "checkout", "--detach", "FETCH_HEAD"],
            capture_output=True,
            check=False,
            text=True,
            env=env,
        )
        if checkout.returncode != 0:
            _remove_path(tmp)
            raise RuntimeError(f"git checkout failed: {checkout.stderr.strip()}")

        if dest.exists():
            _remove_path(dest)
        tmp.rename(dest)
        _note_progress(layer_id, 100, "Ready")


async def _fetch_github_pr_meta(
    owner: str, repo: str, number: int, token: str | None
) -> dict[str, Any]:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"
    async with httpx.AsyncClient(timeout=45) as http:
        resp = await http.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _fetch_gitlab_mr_meta(
    project_path: str,
    iid: int,
    token: str | None,
    api_base: str,
    verify: bool,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["PRIVATE-TOKEN"] = token
    encoded = quote(project_path, safe="")
    url = f"{api_base}/projects/{encoded}/merge_requests/{iid}"
    async with httpx.AsyncClient(timeout=45, verify=verify, follow_redirects=True) as http:
        resp = await http.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _gitlab_web_host(api_base: str) -> str:
    parsed = urlparse(api_base)
    host = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else api_base
    return host.rstrip("/")


async def ensure_pr_checkout_for_ref(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    provider: str,
    owner: str,
    repo: str,
    number: int,
    layer_id: uuid.UUID | None = None,
) -> CheckoutInfo | None:
    """Ensure a temp PR/MR head checkout exists (no session layer required).

    Used by session chat (via layer), AI Review, and CI Debug.
    ``owner``/``repo`` are GitHub owner+repo, or GitLab path segments
    (``group`` + ``project``, or nested via ``owner`` containing slashes).
    """
    provider_l = (provider or "").strip().lower()
    if provider_l == "github":
        base_repo = f"{owner}/{repo}"
        token = await _github_token(db, user_id)
        _note_progress(layer_id, 8, "Reading MR details")
        try:
            pr = await _fetch_github_pr_meta(owner, repo, number, token)
        except Exception:
            logger.exception("Failed to fetch GitHub PR %s#%s", base_repo, number)
            return None
        head = pr.get("head") or {}
        sha = (head.get("sha") or "")[:40]
        branch = head.get("ref") or ""
        clone_url = f"https://github.com/{owner}/{repo}.git"
        fetch_ref = f"pull/{number}/head"
        ssl_verify = True
        source = await _find_matching_source(
            db, project_id, base_repo, ContextSourceType.github_repo
        )
        if source and source.url and source.url.endswith(".git"):
            clone_url = source.url
        elif source and source.url:
            clone_url = source.url if source.url.endswith(".git") else f"{source.url.rstrip('/')}.git"
        source_key = source.id if source else f"gh-{owner}-{repo}"
        repo_name = source.name if source else repo
        resolved_provider = "github"
    elif provider_l == "gitlab":
        # Prefer owner/repo; support owner already being "group/subgroup".
        project_path = f"{owner}/{repo}".strip("/") if repo else owner.strip("/")
        base_repo = project_path
        token, api_base, ssl_verify = await _gitlab_config(db, user_id)
        _note_progress(layer_id, 8, "Reading MR details")
        try:
            mr = await _fetch_gitlab_mr_meta(project_path, number, token, api_base, ssl_verify)
        except Exception:
            logger.exception("Failed to fetch GitLab MR %s!%s", project_path, number)
            return None
        diff_refs = mr.get("diff_refs") if isinstance(mr.get("diff_refs"), dict) else {}
        sha = (diff_refs.get("head_sha") or mr.get("sha") or "")[:40]
        branch = mr.get("source_branch") or ""
        host = _gitlab_web_host(api_base)
        clone_url = f"{host}/{project_path}.git"
        fetch_ref = f"merge-requests/{number}/head"
        source = await _find_matching_source(
            db, project_id, project_path, ContextSourceType.gitlab_repo
        )
        if source and source.url:
            u = source.url.rstrip("/")
            clone_url = u if u.endswith(".git") else f"{u}.git"
        source_key = source.id if source else f"gl-{project_path.replace('/', '-')}"
        repo_name = source.name if source else project_path.split("/")[-1]
        resolved_provider = "gitlab"
    else:
        return None

    if not sha:
        logger.warning(
            "PR/MR %s %s#%s has no head SHA; skipping checkout",
            resolved_provider,
            base_repo,
            number,
        )
        return None

    reused = _find_pr_checkout(project_id, source_key, number)
    if reused is not None:
        current = _head_sha(reused) or sha
        _note_progress(layer_id, 100, "Ready")
        if layer_id:
            _LAYER_PROGRESS.pop(layer_id, None)
        return CheckoutInfo(
            path=str(reused),
            sha=current,
            provider=resolved_provider,
            number=number,
            branch=branch,
            base_repo=base_repo,
            repo_name=repo_name,
        )

    existing_clone: Path | None = None
    if source:
        cp = (source.config or {}).get("clone_path")
        if cp:
            p = Path(str(cp))
            if p.is_dir() and (p / ".git").exists():
                existing_clone = p

    _note_progress(layer_id, 12, "Resolved MR head")

    dest = _checkout_dir(project_id, source_key, number, sha)
    # Fast path: already on disk at the expected SHA.
    if dest.is_dir() and (dest / ".git").exists():
        current = _head_sha(dest)
        if current and current.startswith(sha[:12]):
            _note_progress(layer_id, 100, "Ready")
            if layer_id:
                _LAYER_PROGRESS.pop(layer_id, None)
            return CheckoutInfo(
                path=str(dest),
                sha=sha,
                provider=resolved_provider,
                number=number,
                branch=branch,
                base_repo=base_repo,
                repo_name=repo_name,
            )

    try:
        await asyncio.to_thread(
            _clone_pr_ref_sync,
            clone_url=clone_url,
            dest=dest,
            token=token,
            fetch_ref=fetch_ref,
            expected_sha=sha,
            ssl_verify=ssl_verify,
            layer_id=layer_id,
            existing_clone=existing_clone,
        )
    except Exception:
        logger.exception(
            "PR checkout failed for %s %s#%s → %s",
            resolved_provider,
            base_repo,
            number,
            dest,
        )
        if layer_id:
            _LAYER_PROGRESS.pop(layer_id, None)
        return None

    if layer_id:
        _LAYER_PROGRESS.pop(layer_id, None)
    return CheckoutInfo(
        path=str(dest),
        sha=sha,
        provider=resolved_provider,
        number=number,
        branch=branch,
        base_repo=base_repo,
        repo_name=repo_name,
    )


async def ensure_pr_checkout_for_layer(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    layer: SessionLayer,
) -> CheckoutInfo | None:
    """Ensure a temp checkout exists for a pull_request session layer."""
    url = resolve_pr_layer_url(layer) or ""
    if url and not layer.reference_url:
        layer.reference_url = url
    gh = _parse_github_pr(url)
    gl = _parse_gitlab_mr(url)

    if gh:
        owner, repo, number = gh
        provider = "github"
    elif gl:
        project_path, number = gl
        # Split last segment as repo; rest as owner (supports nested groups).
        parts = project_path.strip("/").split("/")
        if len(parts) < 2:
            return None
        owner, repo = "/".join(parts[:-1]), parts[-1]
        provider = "gitlab"
    else:
        return None

    _set_layer_checkout_status(
        layer, status="fetching", progress=12, stage="Resolved MR head"
    )
    try:
        await db.commit()
    except Exception:
        await db.rollback()

    info = await ensure_pr_checkout_for_ref(
        db,
        project_id=project_id,
        user_id=user_id,
        provider=provider,
        owner=owner,
        repo=repo,
        number=number,
        layer_id=layer.id,
    )
    if info is None:
        return None
    _set_layer_checkout_status(layer, status="ready", info=info, progress=100, stage="Ready")
    return info


async def prepare_session_pr_checkouts(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[CheckoutInfo]:
    """Prepare temp checkouts for all PR layers on the session; set overlays."""
    result = await db.execute(
        select(SessionLayer).where(
            SessionLayer.session_id == session_id,
            SessionLayer.type == SessionLayerType.pull_request,
        )
    )
    layers = list(result.scalars().all())
    overlays: dict[str, CheckoutInfo] = {}
    prepared: list[CheckoutInfo] = []

    for layer in layers:
        # Fast path: reuse persisted checkout if still present and HEAD matches.
        cc = layer.cached_content or {}
        cached = cc.get("pr_checkout") if isinstance(cc, dict) else None
        info: CheckoutInfo | None = None
        if isinstance(cached, dict) and cached.get("path") and cached.get("repo_name"):
            path = Path(str(cached["path"]))
            want_sha = str(cached.get("sha") or "")
            if path.is_dir() and (path / ".git").exists():
                head = _head_sha(path)
                if want_sha and head and head.startswith(want_sha[:12]):
                    info = CheckoutInfo(
                        path=str(path),
                        sha=want_sha,
                        provider=str(cached.get("provider") or ""),
                        number=int(cached.get("number") or 0),
                        branch=str(cached.get("branch") or ""),
                        base_repo=str(cached.get("base_repo") or ""),
                        repo_name=str(cached["repo_name"]),
                    )
                    _set_layer_checkout_status(layer, status="ready", info=info)

        if info is None:
            _note_progress(layer.id, 5, "Reading MR details")
            _set_layer_checkout_status(
                layer, status="fetching", progress=5, stage="Reading MR details"
            )
            try:
                await db.commit()
            except Exception:
                await db.rollback()
            stop = asyncio.Event()
            flusher = asyncio.create_task(_flush_progress_to_db(layer.id, stop))
            try:
                info = await ensure_pr_checkout_for_layer(
                    db, project_id=project_id, user_id=user_id, layer=layer
                )
            finally:
                stop.set()
                with suppress(Exception):
                    await flusher
                _LAYER_PROGRESS.pop(layer.id, None)
            if info is None:
                _set_layer_checkout_status(
                    layer,
                    status="error",
                    error="Could not fetch PR/MR head. Check URL and GitHub/GitLab token.",
                )

        if info:
            overlays[info.repo_name] = info
            prepared.append(info)

    if overlays:
        _SESSION_OVERLAYS[session_id] = overlays
    else:
        _SESSION_OVERLAYS.pop(session_id, None)

    try:
        await db.commit()
    except Exception:
        logger.exception("Failed to persist pr_checkout on session layers")
        await db.rollback()

    return prepared


async def _flush_progress_to_db(layer_id: uuid.UUID, stop: asyncio.Event) -> None:
    """Persist in-memory git progress to the layer row so the UI can poll it."""
    from app.core.database import AsyncSessionLocal

    last: tuple[int, str] | None = None
    while not stop.is_set():
        cur = _LAYER_PROGRESS.get(layer_id)
        if cur and cur != last:
            last = cur
            pct, stage = cur
            try:
                async with AsyncSessionLocal() as db:
                    layer = await db.get(SessionLayer, layer_id)
                    if layer is not None:
                        _set_layer_checkout_status(
                            layer,
                            status="fetching",
                            progress=pct,
                            stage=stage,
                        )
                        await db.commit()
            except Exception:
                logger.debug("progress flush failed for %s", layer_id, exc_info=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.4)
        except TimeoutError:
            pass


async def checkout_layer_in_background(
    *,
    layer_id: uuid.UUID,
    project_id: uuid.UUID,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Background task: fetch PR/MR head after a layer is added."""
    from app.core.database import AsyncSessionLocal

    stop = asyncio.Event()
    flusher = asyncio.create_task(_flush_progress_to_db(layer_id, stop))
    try:
        async with AsyncSessionLocal() as db:
            layer = await db.get(SessionLayer, layer_id)
            if layer is None or layer.type != SessionLayerType.pull_request:
                return
            _note_progress(layer_id, 5, "Reading MR details")
            _set_layer_checkout_status(
                layer, status="fetching", progress=5, stage="Reading MR details"
            )
            await db.commit()

            # Mark meta-fetch stage before API call inside ensure_*.
            _note_progress(layer_id, 8, "Reading MR details")
            info = await ensure_pr_checkout_for_layer(
                db, project_id=project_id, user_id=user_id, layer=layer
            )
            if info is None:
                _LAYER_PROGRESS.pop(layer_id, None)
                _set_layer_checkout_status(
                    layer,
                    status="error",
                    error="Could not fetch PR/MR head. Check URL and GitHub/GitLab token.",
                )
                await db.commit()
                return

            overlays = dict(_SESSION_OVERLAYS.get(session_id, {}))
            overlays[info.repo_name] = info
            _SESSION_OVERLAYS[session_id] = overlays
            await db.commit()
            logger.info(
                "PR/MR checkout ready session=%s repo=%s sha=%s",
                session_id,
                info.repo_name,
                info.sha[:12],
            )
    finally:
        stop.set()
        with suppress(Exception):
            await flusher
        _LAYER_PROGRESS.pop(layer_id, None)


def format_checkout_context_lines(checkouts: list[CheckoutInfo]) -> str:
    if not checkouts:
        return ""
    lines = [
        "--- PR/MR local checkouts (repo_* tools read these trees, NOT the main clone) ---"
    ]
    for c in checkouts:
        lines.append(
            f"- repo_name={c.repo_name} provider={c.provider} "
            f"#{c.number} branch={c.branch or '?'} sha={c.sha[:12]} path={c.path}"
        )
    lines.append(
        "When reviewing, verify findings with repo_read_file / repo_search_code "
        "against these checkouts. Do not treat the main-branch clone as the PR head."
    )
    return "\n".join(lines)
