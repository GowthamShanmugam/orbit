"""Organization-scoped reusable chat prompts (team templates)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.projects import user_has_org_access, user_is_org_team_admin
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.org_prompt_template import OrgPromptTemplate
from app.models.user import User

router = APIRouter()


class OrgPromptTemplateItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    title: str
    body: str
    sort_order: int


class OrgPromptTemplateCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=50_000)
    sort_order: int = 0


class OrgPromptTemplateUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=50_000)
    sort_order: int | None = None


class OrgPromptTemplatesListResponse(BaseModel):
    templates: list[OrgPromptTemplateItem]
    can_manage: bool


async def _require_org_access(
    db: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID
) -> None:
    if not await user_has_org_access(db, user_id, org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed for this organization",
        )


async def _require_org_admin(
    db: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID
) -> None:
    if not await user_is_org_team_admin(db, user_id, org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization admin role required to manage team prompts",
        )


def _to_item(t: OrgPromptTemplate) -> OrgPromptTemplateItem:
    return OrgPromptTemplateItem(
        id=t.id,
        org_id=t.org_id,
        title=t.title,
        body=t.body,
        sort_order=t.sort_order,
    )


@router.get(
    "/organizations/{org_id}/prompt-templates",
    response_model=OrgPromptTemplatesListResponse,
)
async def list_org_prompt_templates(
    org_id: uuid.UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrgPromptTemplatesListResponse:
    await _require_org_access(db, current.id, org_id)
    can_manage = await user_is_org_team_admin(db, current.id, org_id)
    result = await db.execute(
        select(OrgPromptTemplate)
        .where(OrgPromptTemplate.org_id == org_id)
        .order_by(OrgPromptTemplate.sort_order.asc(), OrgPromptTemplate.title.asc())
    )
    rows = list(result.scalars().all())
    return OrgPromptTemplatesListResponse(
        templates=[_to_item(t) for t in rows],
        can_manage=can_manage,
    )


@router.post(
    "/organizations/{org_id}/prompt-templates",
    response_model=OrgPromptTemplateItem,
    status_code=status.HTTP_201_CREATED,
)
async def create_org_prompt_template(
    org_id: uuid.UUID,
    body: OrgPromptTemplateCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrgPromptTemplate:
    await _require_org_access(db, current.id, org_id)
    await _require_org_admin(db, current.id, org_id)
    row = OrgPromptTemplate(
        id=uuid.uuid4(),
        org_id=org_id,
        title=body.title.strip(),
        body=body.body,
        sort_order=body.sort_order,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.patch(
    "/organizations/{org_id}/prompt-templates/{template_id}",
    response_model=OrgPromptTemplateItem,
)
async def update_org_prompt_template(
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    body: OrgPromptTemplateUpdate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrgPromptTemplate:
    await _require_org_access(db, current.id, org_id)
    await _require_org_admin(db, current.id, org_id)
    result = await db.execute(
        select(OrgPromptTemplate).where(
            OrgPromptTemplate.id == template_id,
            OrgPromptTemplate.org_id == org_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if body.title is not None:
        row.title = body.title.strip()
    if body.body is not None:
        row.body = body.body
    if body.sort_order is not None:
        row.sort_order = body.sort_order
    await db.commit()
    await db.refresh(row)
    return row


@router.delete(
    "/organizations/{org_id}/prompt-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_org_prompt_template(
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await _require_org_access(db, current.id, org_id)
    await _require_org_admin(db, current.id, org_id)
    result = await db.execute(
        select(OrgPromptTemplate).where(
            OrgPromptTemplate.id == template_id,
            OrgPromptTemplate.org_id == org_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    await db.delete(row)
    await db.commit()
