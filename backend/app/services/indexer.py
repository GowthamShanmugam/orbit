"""Repo indexing service -- splits files into chunks and stores them.

Full embedding generation (calling an embedding model) is deferred to
a Celery background worker.  This module provides the chunking and
DB persistence logic used by both the sync API path (for small code
snippets) and the async worker path.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.context import ContextSource, IndexedChunk

CHUNK_MAX_TOKENS = 512


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def split_into_chunks(
    content: str,
    *,
    file_path: str | None = None,
    chunk_type: str = "code",
    max_tokens: int = CHUNK_MAX_TOKENS,
) -> list[dict[str, Any]]:
    lines = content.split("\n")
    chunks: list[dict[str, Any]] = []
    current_lines: list[str] = []
    current_tokens = 0

    for line in lines:
        line_tokens = _estimate_tokens(line)
        if current_tokens + line_tokens > max_tokens and current_lines:
            text = "\n".join(current_lines)
            chunks.append(
                {
                    "content": text,
                    "file_path": file_path,
                    "chunk_type": chunk_type,
                    "token_count": current_tokens,
                }
            )
            current_lines = []
            current_tokens = 0
        current_lines.append(line)
        current_tokens += line_tokens

    if current_lines:
        text = "\n".join(current_lines)
        chunks.append(
            {
                "content": text,
                "file_path": file_path,
                "chunk_type": chunk_type,
                "token_count": current_tokens,
            }
        )

    return chunks


async def index_content(
    db: AsyncSession,
    *,
    source_id: uuid.UUID,
    file_path: str | None = None,
    content: str,
    chunk_type: str = "code",
) -> list[IndexedChunk]:
    chunks_data = split_into_chunks(
        content, file_path=file_path, chunk_type=chunk_type
    )
    created: list[IndexedChunk] = []
    for cd in chunks_data:
        chunk = IndexedChunk(
            source_id=source_id,
            file_path=cd["file_path"],
            content=cd["content"],
            chunk_type=cd["chunk_type"],
            token_count=cd["token_count"],
        )
        db.add(chunk)
        created.append(chunk)

    await db.commit()
    for c in created:
        await db.refresh(c)
    return created


async def clear_source_chunks(db: AsyncSession, source_id: uuid.UUID) -> int:
    result = await db.execute(
        delete(IndexedChunk).where(IndexedChunk.source_id == source_id)
    )
    await db.commit()
    return result.rowcount  # type: ignore[return-value]


async def get_source_stats(
    db: AsyncSession, source_id: uuid.UUID
) -> dict[str, Any]:
    row = await db.execute(
        select(
            func.count(IndexedChunk.id),
            func.coalesce(func.sum(IndexedChunk.token_count), 0),
        ).where(IndexedChunk.source_id == source_id)
    )
    count, tokens = row.one()
    return {"chunk_count": count, "total_tokens": tokens}
