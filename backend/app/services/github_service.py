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
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

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


SKIP_DIRS = frozenset({
    "node_modules", ".git", "vendor", "dist", "build", "__pycache__",
    ".tox", ".mypy_cache", ".pytest_cache", ".venv", "venv", "env",
    ".next", ".nuxt", "target", "out", "coverage", ".terraform",
    ".eggs", "site-packages",
})

INDEXABLE_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb", ".java",
    ".kt", ".scala", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift",
    ".md", ".mdx", ".rst", ".txt", ".yaml", ".yml", ".toml", ".json",
    ".xml", ".html", ".css", ".scss", ".less", ".sql", ".sh", ".bash",
    ".zsh", ".fish", ".ps1", ".dockerfile", ".tf", ".hcl",
    ".makefile", ".cmake", ".gradle", ".sbt", ".cabal",
    ".proto", ".graphql", ".gql", ".env.example",
})

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
        "makefile", "dockerfile", "cmakelists.txt", "rakefile",
        "gemfile", "procfile", "justfile",
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


def _clone_repo_sync(
    url: str,
    dest: Path,
    *,
    token: str | None,
    branch: str | None,
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

    clone_url = url
    if token and clone_url.startswith("https://"):
        clone_url = clone_url.replace("https://", f"https://x-access-token:{token}@", 1)

    tmp_dest = dest.parent / f".{dest.name}.orbit-clone-tmp"

    cmd = [_git_executable(), "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [clone_url, str(tmp_dest)]

    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if tmp_dest.exists():
            shutil.rmtree(tmp_dest)
        tmp_dest.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(cmd, capture_output=True, check=False)
        if proc.returncode != 0:
            shutil.rmtree(tmp_dest, ignore_errors=True)
            err = proc.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"git clone failed (exit {proc.returncode}): {err}")
        # Clone succeeded — swap in the new tree.
        if dest.exists():
            shutil.rmtree(dest)
        tmp_dest.rename(dest)


async def clone_repo(
    url: str,
    dest: Path,
    *,
    token: str | None = None,
    branch: str | None = None,
) -> Path:
    """Shallow-clone a GitHub repo to *dest*.

    If *dest* already exists it is removed first so we get a fresh copy.
    Uses a cross-process file lock and limited retries for flaky index-pack errors.
    Returns the path to the clone directory.
    """
    last_err: RuntimeError | None = None
    for attempt in range(3):
        try:
            await asyncio.to_thread(_clone_repo_sync, url, dest, token=token, branch=branch)
            logger.info("Cloned %s → %s", url, dest)
            return dest
        except RuntimeError as exc:
            last_err = exc
            if attempt < 2:
                await asyncio.sleep(0.5 * (2**attempt))
    assert last_err is not None
    raise last_err
