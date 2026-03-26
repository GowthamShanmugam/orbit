from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.context import (
    ContextPack,
    ContextSource,
    InstalledPack,
    PackContextSource,
    PackVisibility,
)


async def list_packs(
    db: AsyncSession,
    *,
    org_ids: list[uuid.UUID] | None = None,
    user_id: uuid.UUID | None = None,
    category: str | None = None,
    search: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[ContextPack]:
    stmt = (
        select(ContextPack)
        .options(selectinload(ContextPack.sources))
        .order_by(ContextPack.updated_at.desc())
    )

    from sqlalchemy import or_

    visibility_filters = [ContextPack.visibility == PackVisibility.public]
    if org_ids:
        visibility_filters.append(
            (ContextPack.visibility == PackVisibility.organization)
            & (ContextPack.org_id.in_(org_ids))
        )
    if user_id is not None:
        visibility_filters.append(
            (ContextPack.visibility == PackVisibility.personal)
            & (ContextPack.created_by == user_id)
        )
        visibility_filters.append(ContextPack.created_by == user_id)
    stmt = stmt.where(or_(*visibility_filters))

    if category:
        stmt = stmt.where(ContextPack.category == category)

    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            ContextPack.name.ilike(pattern) | ContextPack.description.ilike(pattern)
        )

    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def get_pack(db: AsyncSession, pack_id: uuid.UUID) -> ContextPack | None:
    result = await db.execute(
        select(ContextPack)
        .options(selectinload(ContextPack.sources))
        .where(ContextPack.id == pack_id)
    )
    return result.scalar_one_or_none()


async def create_pack(
    db: AsyncSession,
    *,
    name: str,
    description: str | None = None,
    icon: str | None = None,
    category: str | None = None,
    visibility: PackVisibility = PackVisibility.organization,
    dependencies: dict[str, Any] | None = None,
    maintainer_team: str | None = None,
    org_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    sources: list[dict[str, Any]] | None = None,
) -> ContextPack:
    pack = ContextPack(
        name=name,
        description=description,
        icon=icon,
        category=category,
        visibility=visibility,
        dependencies=dependencies,
        maintainer_team=maintainer_team,
        org_id=org_id,
        created_by=created_by,
        repo_count=0,
    )
    db.add(pack)
    await db.flush()

    if sources:
        repo_count = 0
        for src in sources:
            pcs = PackContextSource(
                pack_id=pack.id,
                type=src["type"],
                name=src["name"],
                url=src.get("url"),
                config=src.get("config"),
            )
            db.add(pcs)
            if src["type"] in ("github_repo", "gitlab_repo"):
                repo_count += 1
        pack.repo_count = repo_count

    await db.commit()
    await db.refresh(pack)

    result = await db.execute(
        select(ContextPack)
        .options(selectinload(ContextPack.sources))
        .where(ContextPack.id == pack.id)
    )
    return result.scalar_one()


async def update_pack(
    db: AsyncSession,
    pack: ContextPack,
    *,
    name: str | None = None,
    description: str | None = None,
    icon: str | None = None,
    category: str | None = None,
    visibility: PackVisibility | None = None,
    maintainer_team: str | None = None,
) -> ContextPack:
    if name is not None:
        pack.name = name
    if description is not None:
        pack.description = description
    if icon is not None:
        pack.icon = icon
    if category is not None:
        pack.category = category
    if visibility is not None:
        pack.visibility = visibility
    if maintainer_team is not None:
        pack.maintainer_team = maintainer_team

    await db.commit()
    await db.refresh(pack)
    return pack


async def delete_pack(db: AsyncSession, pack: ContextPack) -> None:
    await db.delete(pack)
    await db.commit()


async def add_source_to_pack(
    db: AsyncSession,
    pack: ContextPack,
    *,
    type: str,
    name: str,
    url: str | None = None,
    config: dict[str, Any] | None = None,
) -> PackContextSource:
    source = PackContextSource(
        pack_id=pack.id,
        type=type,
        name=name,
        url=url,
        config=config,
    )
    db.add(source)
    if type in ("github_repo", "gitlab_repo"):
        pack.repo_count = pack.repo_count + 1
    await db.commit()
    await db.refresh(source)
    return source


async def remove_source_from_pack(
    db: AsyncSession, pack: ContextPack, source: PackContextSource
) -> None:
    if source.type in ("github_repo", "gitlab_repo"):
        pack.repo_count = max(0, pack.repo_count - 1)
    await db.delete(source)
    await db.commit()


async def install_pack(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    pack_id: uuid.UUID,
    auto_update: bool = True,
) -> InstalledPack:
    result = await db.execute(
        select(InstalledPack).where(
            InstalledPack.project_id == project_id,
            InstalledPack.pack_id == pack_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    pack = await get_pack(db, pack_id)
    if pack is None:
        raise ValueError("Pack not found")

    installed = InstalledPack(
        project_id=project_id,
        pack_id=pack_id,
        version=pack.version,
        auto_update=auto_update,
    )
    db.add(installed)

    for src in pack.sources:
        ctx = ContextSource(
            project_id=project_id,
            type=src.type,
            name=src.name,
            url=src.url,
            config=src.config,
            auto_attach=True,
        )
        db.add(ctx)

    await db.commit()
    await db.refresh(installed)
    return installed


async def uninstall_pack(
    db: AsyncSession, *, project_id: uuid.UUID, pack_id: uuid.UUID
) -> None:
    result = await db.execute(
        select(InstalledPack).where(
            InstalledPack.project_id == project_id,
            InstalledPack.pack_id == pack_id,
        )
    )
    installed = result.scalar_one_or_none()
    if installed is not None:
        await db.delete(installed)
        await db.commit()


async def list_installed_packs(
    db: AsyncSession, project_id: uuid.UUID
) -> list[InstalledPack]:
    result = await db.execute(
        select(InstalledPack)
        .options(selectinload(InstalledPack.pack).selectinload(ContextPack.sources))
        .where(InstalledPack.project_id == project_id)
        .order_by(InstalledPack.installed_at.desc())
    )
    return list(result.scalars().unique().all())


async def get_pack_categories(db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(ContextPack.category)
        .where(ContextPack.category.isnot(None))
        .distinct()
        .order_by(ContextPack.category)
    )
    return [row[0] for row in result.all()]
