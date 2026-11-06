"""GitHub API client for fetching repository trees, file contents, and cloning repos.

Uses the REST API v3 for tree listing and raw.githubusercontent.com for
file content.  Supports optional GITHUB_TOKEN for higher rate limits.
Also provides ``clone_repo`` which uses ``git clone --depth 1`` to create
a shallow local clone that the AI can browse via file tools.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import re
import select
import shutil
import subprocess
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# source_id -> (percent, stage) while a repo clone is in flight
_CLONE_PROGRESS: dict[uuid.UUID, tuple[int, str]] = {}
# Monotonic per-source attempt id so a retry can supersede an in-flight clone.
_CLONE_GENERATION: dict[uuid.UUID, int] = {}
_CLONE_PROCS: dict[uuid.UUID, subprocess.Popen] = {}
_GIT_PCT_RE = re.compile(r"(\d+)%")
_CLONE_TIMEOUT_SEC = 600
ProgressCb = Callable[[int, str], None]


class CloneCancelled(RuntimeError):
    """Raised when a clone is killed because the user started a retry."""

GITHUB_API = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"

DEFAULT_REPO_BRANCH = "main"
REPO_STREAM_VALUES = frozenset({"upstream", "midstream", "downstream"})


def branch_from_context_config(config: dict[str, Any] | None) -> str:
    """Branch passed to ``git clone --branch``; defaults when unset in config."""
    raw = (config or {}).get("branch")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return DEFAULT_REPO_BRANCH
    return str(raw).strip()


def repo_stream_from_context_config(config: dict[str, Any] | None) -> str | None:
    raw = (config or {}).get("repo_stream")
    if raw is None or not isinstance(raw, str):
        return None
    s = raw.strip().lower()
    return s if s in REPO_STREAM_VALUES else None


SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "vendor",
        "dist",
        "build",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".venv",
        "venv",
        "env",
        ".next",
        ".nuxt",
        "target",
        "out",
        "coverage",
        ".terraform",
        ".eggs",
        "site-packages",
    }
)

INDEXABLE_EXTENSIONS = frozenset(
    {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".go",
        ".rs",
        ".rb",
        ".java",
        ".kt",
        ".scala",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".swift",
        ".md",
        ".mdx",
        ".rst",
        ".txt",
        ".yaml",
        ".yml",
        ".toml",
        ".json",
        ".xml",
        ".html",
        ".css",
        ".scss",
        ".less",
        ".sql",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".ps1",
        ".dockerfile",
        ".tf",
        ".hcl",
        ".makefile",
        ".cmake",
        ".gradle",
        ".sbt",
        ".cabal",
        ".proto",
        ".graphql",
        ".gql",
        ".env.example",
    }
)


@dataclass
class RepoFile:
    path: str
    size: int
    content: str = ""


@dataclass
class RepoTree:
    owner: str
    repo: str
    branch: str
    files: list[RepoFile] = field(default_factory=list)
    truncated: bool = False
    total_files: int = 0
    fetched_files: int = 0


def parse_github_url(url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a GitHub URL."""
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)", url)
    if m:
        return m.group(1), m.group(2)
    raise ValueError(f"Cannot parse GitHub URL: {url}")


def _should_index(path: str, size: int) -> bool:
    parts = path.split("/")
    for part in parts[:-1]:
        if part in SKIP_DIRS:
            return False

    if size > settings.GITHUB_MAX_FILE_BYTES:
        return False

    filename = parts[-1].lower()

    if filename in {
        "makefile",
        "dockerfile",
        "cmakelists.txt",
        "rakefile",
        "gemfile",
        "procfile",
        "justfile",
    }:
        return True

    dot_pos = filename.rfind(".")
    if dot_pos == -1:
        return False
    ext = filename[dot_pos:]
    return ext in INDEXABLE_EXTENSIONS


def _headers(token: str | None = None) -> dict[str, str]:
    h: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def fetch_repo_tree(
    owner: str,
    repo: str,
    *,
    token: str | None = None,
    branch: str | None = None,
) -> RepoTree:
    """Fetch the full file tree for a GitHub repo."""
    async with httpx.AsyncClient(timeout=settings.HTTP_CLIENT_TIMEOUT_SEC) as client:
        if not branch:
            resp = await client.get(
                f"{GITHUB_API}/repos/{owner}/{repo}",
                headers=_headers(token),
            )
            resp.raise_for_status()
            branch = resp.json()["default_branch"]

        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}",
            params={"recursive": "1"},
            headers=_headers(token),
        )
        resp.raise_for_status()
        data = resp.json()

    tree = RepoTree(
        owner=owner,
        repo=repo,
        branch=branch,
        truncated=data.get("truncated", False),
    )

    for item in data.get("tree", []):
        if item["type"] != "blob":
            continue
        size = item.get("size", 0)
        if _should_index(item["path"], size):
            tree.files.append(RepoFile(path=item["path"], size=size))

    tree.total_files = len(tree.files)
    return tree


async def fetch_file_contents(
    tree: RepoTree,
    *,
    token: str | None = None,
    on_progress: Any | None = None,
) -> RepoTree:
    """Fetch raw content for every file in the tree (concurrently)."""
    sem = asyncio.Semaphore(settings.GITHUB_FETCH_CONCURRENCY)

    async def _fetch_one(f: RepoFile) -> None:
        async with sem:
            url = f"{RAW_BASE}/{tree.owner}/{tree.repo}/{tree.branch}/{f.path}"
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            try:
                async with httpx.AsyncClient(timeout=settings.HTTP_CLIENT_TIMEOUT_SEC) as client:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    f.content = resp.text
                    tree.fetched_files += 1
            except Exception:
                logger.warning("Failed to fetch %s/%s:%s", tree.owner, tree.repo, f.path)
                tree.fetched_files += 1

            if on_progress:
                await on_progress(tree.fetched_files, tree.total_files)

    await asyncio.gather(*[_fetch_one(f) for f in tree.files])
    return tree


# ---------------------------------------------------------------------------
# Local shallow clone
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _git_executable() -> str:
    """Resolve git binary. Prefer absolute paths — OpenShift/minimal images often have a tiny PATH."""
    for candidate in ("/usr/bin/git", "/bin/git"):
        if Path(candidate).is_file():
            return candidate
    found = shutil.which("git")
    if found:
        return found
    raise RuntimeError(
        "git is not available in this environment; add `git` to the API container image."
    )


def note_clone_progress(
    source_id: uuid.UUID | None, percent: int, stage: str
) -> None:
    if source_id is None:
        return
    pct = max(0, min(100, int(percent)))
    prev = _CLONE_PROGRESS.get(source_id)
    if prev and prev[0] > pct and pct < 100:
        pct = prev[0]
    _CLONE_PROGRESS[source_id] = (pct, stage)


def get_clone_progress(source_id: uuid.UUID) -> tuple[int, str] | None:
    return _CLONE_PROGRESS.get(source_id)


def clear_clone_progress(source_id: uuid.UUID) -> None:
    _CLONE_PROGRESS.pop(source_id, None)


def bump_clone_generation(source_id: uuid.UUID) -> int:
    """Start a new clone attempt; kill any in-flight git for this source."""
    gen = _CLONE_GENERATION.get(source_id, 0) + 1
    _CLONE_GENERATION[source_id] = gen
    proc = _CLONE_PROCS.get(source_id)
    if proc is not None and proc.poll() is None:
        with suppress(Exception):
            proc.kill()
    clear_clone_progress(source_id)
    return gen


def current_clone_generation(source_id: uuid.UUID) -> int:
    return _CLONE_GENERATION.get(source_id, 0)


def is_clone_generation_current(source_id: uuid.UUID | None, generation: int | None) -> bool:
    if source_id is None or generation is None:
        return True
    return _CLONE_GENERATION.get(source_id, 0) == generation


def _ssh_to_https(url: str) -> str:
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


def _auth_clone_url(url: str, token: str | None) -> str:
    https = _ssh_to_https(url)
    if not token or not https.startswith("https://"):
        return https
    # GitHub PAT and GitLab PAT both work with oauth2:token or x-access-token.
    host = https.split("/")[2].lower() if "://" in https else ""
    if "github.com" in host:
        return https.replace("https://", f"https://x-access-token:{token}@", 1)
    return https.replace("https://", f"https://oauth2:{token}@", 1)


def _map_clone_git_progress(line: str) -> tuple[int, str] | None:
    text = line.strip()
    if not text:
        return None
    m = _GIT_PCT_RE.search(text)
    lower = text.lower()
    if not m:
        if "counting objects" in lower:
            return 15, "Counting objects"
        if "compressing objects" in lower:
            return 25, "Compressing objects"
        if "cloning into" in lower:
            return 8, "Starting clone"
        return None
    git_pct = int(m.group(1))
    if "receiving objects" in lower:
        return 30 + int(git_pct * 0.55), "Downloading objects"
    if "resolving deltas" in lower:
        return 85 + int(git_pct * 0.1), "Resolving deltas"
    if "checking out" in lower or "updating files" in lower:
        return 95 + int(git_pct * 0.04), "Checking out files"
    return 30 + int(git_pct * 0.55), "Cloning"


def _run_clone_with_progress(
    cmd: list[str],
    *,
    env: dict[str, str],
    source_id: uuid.UUID | None,
    on_progress: ProgressCb | None,
    generation: int | None = None,
    timeout_sec: int = _CLONE_TIMEOUT_SEC,
) -> tuple[int, str]:
    def _emit(pct: int, stage: str) -> None:
        note_clone_progress(source_id, pct, stage)
        if on_progress:
            on_progress(pct, stage)

    def _superseded() -> bool:
        return not is_clone_generation_current(source_id, generation)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert proc.stderr is not None
    if source_id is not None:
        _CLONE_PROCS[source_id] = proc
    err_chunks: list[str] = []
    buf = b""
    started = time.monotonic()
    last_beat = started
    fd = proc.stderr.fileno()
    try:
        while True:
            if _superseded():
                with suppress(Exception):
                    proc.kill()
                with suppress(Exception):
                    proc.wait(timeout=5)
                raise CloneCancelled("clone superseded by retry")
            if time.monotonic() - started > timeout_sec:
                proc.kill()
                proc.wait(timeout=5)
                return 124, f"timed out after {timeout_sec}s\n" + "\n".join(err_chunks[-20:])
            ready, _, _ = select.select([fd], [], [], 0.5)
            if not ready:
                if time.monotonic() - last_beat >= 2:
                    cur = _CLONE_PROGRESS.get(source_id, (40, "Cloning"))[0] if source_id else 40
                    _emit(min(92, cur + 1), "Cloning (still working…)")
                    last_beat = time.monotonic()
                if proc.poll() is not None:
                    break
                continue
            chunk = os.read(fd, 256)
            if not chunk:
                break
            last_beat = time.monotonic()
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts[-1]
            for raw in parts[:-1]:
                line = raw.decode(errors="replace").strip()
                if not line:
                    continue
                err_chunks.append(line)
                mapped = _map_clone_git_progress(line)
                if mapped:
                    _emit(mapped[0], mapped[1])
        if buf.strip():
            err_chunks.append(buf.decode(errors="replace").strip())
        if _superseded():
            raise CloneCancelled("clone superseded by retry")
        code = proc.wait(timeout=5)
        return code, "\n".join(err_chunks[-20:])
    finally:
        if source_id is not None and _CLONE_PROCS.get(source_id) is proc:
            _CLONE_PROCS.pop(source_id, None)
        if proc.poll() is None:
            with suppress(Exception):
                proc.kill()


def _clone_repo_sync(
    url: str,
    dest: Path,
    *,
    token: str | None,
    branch: str | None,
    source_id: uuid.UUID | None = None,
    on_progress: ProgressCb | None = None,
    ssl_verify: bool = True,
    generation: int | None = None,
) -> None:
    """Run git clone under an exclusive flock so multiple uvicorn workers cannot
    corrupt the same `.git` (tmp_pack / index-pack races).

    Clones into a temporary sibling directory first. The existing clone is only
    replaced **after** the new clone succeeds — so a failed re-clone never
    destroys a working tree.
    """
    dest = dest.resolve()
    lock_path = dest.parent / f".{dest.name}.orbit-clone.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    clone_url = _auth_clone_url(url, token)
    env = os.environ.copy()
    if not ssl_verify:
        env["GIT_SSL_NO_VERIFY"] = "1"

    tmp_dest = dest.parent / f".{dest.name}.orbit-clone-tmp"

    def _emit(pct: int, stage: str) -> None:
        note_clone_progress(source_id, pct, stage)
        if on_progress:
            on_progress(pct, stage)

    cmd = [_git_executable(), "clone", "--progress", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [clone_url, str(tmp_dest)]

    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if not is_clone_generation_current(source_id, generation):
            raise CloneCancelled("clone superseded by retry")
        if tmp_dest.exists():
            shutil.rmtree(tmp_dest)
        # Do not pre-create tmp_dest — git clone wants to create it.
        _emit(5, "Starting clone")
        try:
            code, err = _run_clone_with_progress(
                cmd,
                env=env,
                source_id=source_id,
                on_progress=on_progress,
                generation=generation,
            )
        except CloneCancelled:
            shutil.rmtree(tmp_dest, ignore_errors=True)
            raise
        if code != 0:
            shutil.rmtree(tmp_dest, ignore_errors=True)
            raise RuntimeError(f"git clone failed (exit {code}): {err}")
        if not is_clone_generation_current(source_id, generation):
            shutil.rmtree(tmp_dest, ignore_errors=True)
            raise CloneCancelled("clone superseded by retry")
        _emit(98, "Finalizing")
        if dest.exists():
            shutil.rmtree(dest)
        tmp_dest.rename(dest)
        _emit(100, "Done")


async def clone_repo(
    url: str,
    dest: Path,
    *,
    token: str | None = None,
    branch: str | None = None,
    source_id: uuid.UUID | None = None,
    on_progress: ProgressCb | None = None,
    ssl_verify: bool = True,
    generation: int | None = None,
) -> Path:
    """Shallow-clone a GitHub/GitLab repo to *dest*.

    If *dest* already exists it is removed first so we get a fresh copy.
    Uses a cross-process file lock and limited retries for flaky index-pack errors.
    Returns the path to the clone directory.
    """
    last_err: RuntimeError | None = None
    for attempt in range(3):
        if not is_clone_generation_current(source_id, generation):
            raise CloneCancelled("clone superseded by retry")
        try:
            await asyncio.to_thread(
                _clone_repo_sync,
                url,
                dest,
                token=token,
                branch=branch,
                source_id=source_id,
                on_progress=on_progress,
                ssl_verify=ssl_verify,
                generation=generation,
            )
            logger.info("Cloned %s → %s", url, dest)
            if source_id and is_clone_generation_current(source_id, generation):
                clear_clone_progress(source_id)
            return dest
        except CloneCancelled:
            raise
        except RuntimeError as exc:
            last_err = exc
            if attempt < 2 and is_clone_generation_current(source_id, generation):
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            break
    if source_id and is_clone_generation_current(source_id, generation):
        clear_clone_progress(source_id)
    assert last_err is not None
    raise last_err
