"""Repo indexing worker — clones GitHub repos via API, chunks files, stores in DB.

Runs in-process as a background task (no Celery required for now).
Designed to be called from an API endpoint or triggered on pack install.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.context import ContextSource, IndexedChunk
from app.services.github_service import (
    fetch_file_contents,
    fetch_repo_tree,
    parse_github_url,
)
from app.services.indexer import split_into_chunks

logger = logging.getLogger(__name__)


async def index_github_source(
    db: AsyncSession,
    source: ContextSource,
    *,
    token: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Index a GitHub repo source: fetch tree, download files, chunk & store.

    Yields progress events suitable for SSE streaming:
      {"type": "progress", "phase": ..., "detail": ..., "pct": ...}
      {"type": "complete", "chunks": N, "tokens": N, "files": N}
      {"type": "error", "message": ...}
    """
    if not source.url:
        yield {"type": "error", "message": "Source has no URL"}
        return

    try:
        owner, repo = parse_github_url(source.url)
    except ValueError as e:
        yield {"type": "error", "message": str(e)}
        return

    yield {
        "type": "progress",
        "phase": "tree",
        "detail": f"Fetching file tree for {owner}/{repo}",
        "pct": 0,
    }

    try:
        tree = await fetch_repo_tree(owner, repo, token=token)
    except Exception as e:
        yield {"type": "error", "message": f"Failed to fetch repo tree: {e}"}
        return

    yield {
        "type": "progress",
        "phase": "tree",
        "detail": f"Found {tree.total_files} indexable files in {owner}/{repo}",
        "pct": 5,
    }

    async def _on_progress(done: int, total: int) -> None:
        pass  # progress yielded below after fetch completes per-batch

    yield {
        "type": "progress",
        "phase": "download",
        "detail": f"Downloading {tree.total_files} files",
        "pct": 10,
    }

    try:
        tree = await fetch_file_contents(tree, token=token)
    except Exception as e:
        yield {"type": "error", "message": f"Failed to download files: {e}"}
        return

    yield {
        "type": "progress",
        "phase": "download",
        "detail": f"Downloaded {tree.fetched_files}/{tree.total_files} files",
        "pct": 50,
    }

    # Clear previous chunks for this source
    await db.execute(
        delete(IndexedChunk).where(IndexedChunk.source_id == source.id)
    )

    yield {
        "type": "progress",
        "phase": "indexing",
        "detail": "Chunking and storing",
        "pct": 55,
    }

    total_chunks = 0
    total_tokens = 0
    files_indexed = 0

    for i, f in enumerate(tree.files):
        if not f.content:
            continue

        ext = f.path.rsplit(".", 1)[-1] if "." in f.path else ""
        chunk_type = "doc" if ext in ("md", "mdx", "rst", "txt") else "code"

        chunks_data = split_into_chunks(
            f.content, file_path=f.path, chunk_type=chunk_type
        )

        for cd in chunks_data:
            chunk = IndexedChunk(
                source_id=source.id,
                file_path=cd["file_path"],
                content=cd["content"],
                chunk_type=cd["chunk_type"],
                token_count=cd["token_count"],
            )
            db.add(chunk)
            total_chunks += 1
            total_tokens += cd["token_count"]

        files_indexed += 1

        if (i + 1) % 50 == 0:
            await db.flush()
            pct = 55 + int((i / len(tree.files)) * 40)
            yield {
                "type": "progress",
                "phase": "indexing",
                "detail": f"Indexed {files_indexed}/{len(tree.files)} files ({total_chunks} chunks)",
                "pct": min(pct, 95),
            }

    source.last_indexed = datetime.now(timezone.utc)
    source.config = {
        **(source.config or {}),
        "index_stats": {
            "files": files_indexed,
            "chunks": total_chunks,
            "tokens": total_tokens,
            "branch": tree.branch,
        },
    }

    await db.commit()

    yield {
        "type": "complete",
        "chunks": total_chunks,
        "tokens": total_tokens,
        "files": files_indexed,
        "branch": tree.branch,
    }

    logger.info(
        "Indexed %s/%s: %d files, %d chunks, %d tokens",
        owner, repo, files_indexed, total_chunks, total_tokens,
    )


async def index_project_sources(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    token: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Index all unindexed GitHub sources for a project."""
    result = await db.execute(
        select(ContextSource).where(
            ContextSource.project_id == project_id,
            ContextSource.type == "github_repo",
            ContextSource.last_indexed.is_(None),
        )
    )
    sources = result.scalars().all()

    if not sources:
        yield {"type": "complete", "message": "No unindexed sources found"}
        return

    for i, source in enumerate(sources):
        yield {
            "type": "progress",
            "phase": "source",
            "detail": f"Indexing source {i+1}/{len(sources)}: {source.name}",
            "source_name": source.name,
            "pct": 0,
        }
        async for event in index_github_source(db, source, token=token):
            yield {**event, "source_name": source.name}
