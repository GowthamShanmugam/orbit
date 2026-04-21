"""AI Rules CRUD — global rules under /settings, project rules under /projects."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.projects import require_project_access
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.ai_rule import AIRule, RuleCategory, RuleScope
from app.models.user import User

router = APIRouter()


class AIRuleOut(BaseModel):
    id: str
    scope: str
    category: str
    project_id: str | None
    title: str
    content: str
    enabled: bool
    is_seeded: bool
    sort_order: int
    readonly: bool

    model_config = {"from_attributes": True}


class CreateRuleBody(BaseModel):
    title: str
    content: str
    category: str = "other"
    sort_order: int = 0


class UpdateRuleBody(BaseModel):
    title: str | None = None
    content: str | None = None
    category: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None


def _to_out(rule: AIRule) -> dict[str, Any]:
    return {
        "id": str(rule.id),
        "scope": rule.scope.value if isinstance(rule.scope, RuleScope) else rule.scope,
        "category": rule.category.value if isinstance(rule.category, RuleCategory) else rule.category,
        "project_id": str(rule.project_id) if rule.project_id else None,
        "title": rule.title,
        "content": rule.content,
        "enabled": rule.enabled,
        "is_seeded": rule.is_seeded,
        "sort_order": rule.sort_order,
        "readonly": rule.is_seeded,
    }


# ── Global AI rules (under /settings) ────────────────────────────────────────


@router.get("/settings/ai-rules")
async def list_global_rules(
    _current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return all global AI rules (seeded + admin-created)."""
    result = await db.execute(
        select(AIRule)
        .where(AIRule.scope == RuleScope.glob)
        .order_by(AIRule.sort_order.asc())
    )
    rules = result.scalars().all()
    return [_to_out(r) for r in rules]


@router.post("/settings/ai-rules", status_code=status.HTTP_201_CREATED)
async def create_global_rule(
    payload: CreateRuleBody,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a global AI rule (admin-created, not seeded)."""
    try:
        cat = RuleCategory(payload.category)
    except ValueError:
        cat = RuleCategory.other

    rule = AIRule(
        id=uuid.uuid4(),
        scope=RuleScope.glob,
        category=cat,
        project_id=None,
        title=payload.title,
        content=payload.content,
        enabled=True,
        is_seeded=False,
        sort_order=payload.sort_order,
        created_by_id=current.id,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _to_out(rule)


@router.patch("/settings/ai-rules/{rule_id}")
async def update_global_rule(
    rule_id: uuid.UUID,
    payload: UpdateRuleBody,
    _current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update a global AI rule. Seeded rules cannot be modified."""
    result = await db.execute(select(AIRule).where(AIRule.id == rule_id))
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if rule.scope != RuleScope.glob:
        raise HTTPException(status_code=400, detail="Not a global rule")
    if rule.is_seeded:
        raise HTTPException(status_code=403, detail="Seeded rules are read-only")

    if payload.title is not None:
        rule.title = payload.title
    if payload.content is not None:
        rule.content = payload.content
    if payload.category is not None:
        try:
            rule.category = RuleCategory(payload.category)
        except ValueError:
            rule.category = RuleCategory.other
    if payload.enabled is not None:
        rule.enabled = payload.enabled
    if payload.sort_order is not None:
        rule.sort_order = payload.sort_order

    await db.commit()
    await db.refresh(rule)
    return _to_out(rule)


@router.delete("/settings/ai-rules/{rule_id}")
async def delete_global_rule(
    rule_id: uuid.UUID,
    _current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Delete a global AI rule. Seeded rules cannot be deleted."""
    result = await db.execute(select(AIRule).where(AIRule.id == rule_id))
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if rule.scope != RuleScope.glob:
        raise HTTPException(status_code=400, detail="Not a global rule")
    if rule.is_seeded:
        raise HTTPException(status_code=403, detail="Seeded rules cannot be deleted")

    await db.delete(rule)
    await db.commit()
    return {"status": "deleted"}


# ── Project-scoped AI rules ──────────────────────────────────────────────────


@router.get("/projects/{project_id}/ai-rules")
async def list_project_rules(
    project_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return project-specific AI rules only."""
    await require_project_access(db, current.id, project_id)

    result = await db.execute(
        select(AIRule)
        .where(
            AIRule.scope == RuleScope.project,
            AIRule.project_id == project_id,
        )
        .order_by(AIRule.sort_order.asc())
    )
    rules = result.scalars().all()
    return [_to_out(r) for r in rules]


@router.post("/projects/{project_id}/ai-rules", status_code=status.HTTP_201_CREATED)
async def create_project_rule(
    project_id: uuid.UUID,
    payload: CreateRuleBody,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a project-level AI rule."""
    await require_project_access(db, current.id, project_id)

    try:
        cat = RuleCategory(payload.category)
    except ValueError:
        cat = RuleCategory.other

    rule = AIRule(
        id=uuid.uuid4(),
        scope=RuleScope.project,
        category=cat,
        project_id=project_id,
        title=payload.title,
        content=payload.content,
        enabled=True,
        is_seeded=False,
        sort_order=payload.sort_order,
        created_by_id=current.id,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _to_out(rule)


@router.patch("/projects/{project_id}/ai-rules/{rule_id}")
async def update_project_rule(
    project_id: uuid.UUID,
    rule_id: uuid.UUID,
    payload: UpdateRuleBody,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update a project-level AI rule."""
    await require_project_access(db, current.id, project_id)

    result = await db.execute(select(AIRule).where(AIRule.id == rule_id))
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if rule.is_seeded:
        raise HTTPException(status_code=403, detail="Global rules are read-only")
    if rule.project_id != project_id:
        raise HTTPException(status_code=403, detail="Rule belongs to another project")

    if payload.title is not None:
        rule.title = payload.title
    if payload.content is not None:
        rule.content = payload.content
    if payload.category is not None:
        try:
            rule.category = RuleCategory(payload.category)
        except ValueError:
            rule.category = RuleCategory.other
    if payload.enabled is not None:
        rule.enabled = payload.enabled
    if payload.sort_order is not None:
        rule.sort_order = payload.sort_order

    await db.commit()
    await db.refresh(rule)
    return _to_out(rule)


@router.delete("/projects/{project_id}/ai-rules/{rule_id}")
async def delete_project_rule(
    project_id: uuid.UUID,
    rule_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Delete a project-level AI rule."""
    await require_project_access(db, current.id, project_id)

    result = await db.execute(select(AIRule).where(AIRule.id == rule_id))
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if rule.is_seeded:
        raise HTTPException(status_code=403, detail="Global rules cannot be deleted")
    if rule.project_id != project_id:
        raise HTTPException(status_code=403, detail="Rule belongs to another project")

    await db.delete(rule)
    await db.commit()
    return {"status": "deleted"}
