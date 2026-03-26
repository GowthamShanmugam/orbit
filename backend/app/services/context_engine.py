from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.context import (
    ContextSource,
    SessionLayer,
    SessionLayerType,
)


async def list_context_sources(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 100,
) -> list[ContextSource]:
    result = await db.execute(
        select(ContextSource)
        .where(ContextSource.project_id == project_id)
        .order_by(ContextSource.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def add_context_source(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    type: str,
    name: str,
    url: str | None = None,
    config: dict[str, Any] | None = None,
    auto_attach: bool = True,
) -> ContextSource:
    source = ContextSource(
        project_id=project_id,
        type=type,
        name=name,
        url=url,
        config=config,
        auto_attach=auto_attach,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def remove_context_source(db: AsyncSession, source: ContextSource) -> None:
    await db.delete(source)
    await db.commit()


async def get_context_source(
    db: AsyncSession, source_id: uuid.UUID
) -> ContextSource | None:
    result = await db.execute(
        select(ContextSource).where(ContextSource.id == source_id)
    )
    return result.scalar_one_or_none()


async def list_session_layers(
    db: AsyncSession, session_id: uuid.UUID
) -> list[SessionLayer]:
    result = await db.execute(
        select(SessionLayer)
        .where(SessionLayer.session_id == session_id)
        .order_by(SessionLayer.created_at.asc())
    )
    return list(result.scalars().all())


async def add_session_layer(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    type: SessionLayerType,
    label: str,
    reference_url: str | None = None,
    cached_content: dict[str, Any] | None = None,
    token_count: int = 0,
) -> SessionLayer:
    layer = SessionLayer(
        session_id=session_id,
        type=type,
        label=label,
        reference_url=reference_url,
        cached_content=cached_content,
        token_count=token_count,
    )
    db.add(layer)
    await db.commit()
    await db.refresh(layer)
    return layer


async def remove_session_layer(db: AsyncSession, layer: SessionLayer) -> None:
    await db.delete(layer)
    await db.commit()


async def get_session_layer(
    db: AsyncSession, layer_id: uuid.UUID
) -> SessionLayer | None:
    result = await db.execute(
        select(SessionLayer).where(SessionLayer.id == layer_id)
    )
    return result.scalar_one_or_none()


