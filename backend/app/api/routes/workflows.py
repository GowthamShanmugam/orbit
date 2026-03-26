"""Workflow management endpoints.

List available workflows, create custom ones, and delete non-builtin entries.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.workflow import Workflow

router = APIRouter()


class WorkflowResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    system_prompt: str
    icon: str | None
    is_builtin: bool
    sort_order: int
    created_at: str
    updated_at: str


class CreateWorkflowRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_]+$")
    description: str = Field(min_length=1)
    system_prompt: str = ""
    icon: str | None = None
    sort_order: int = 100


def _workflow_to_response(wf: Workflow) -> dict[str, Any]:
    return {
        "id": str(wf.id),
        "name": wf.name,
        "slug": wf.slug,
        "description": wf.description,
        "system_prompt": wf.system_prompt,
        "icon": wf.icon,
        "is_builtin": wf.is_builtin,
        "sort_order": wf.sort_order,
        "created_at": wf.created_at.isoformat(),
        "updated_at": wf.updated_at.isoformat(),
    }


@router.get("/workflows", response_model=list[WorkflowResponse])
async def list_workflows(
    _current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(Workflow).order_by(Workflow.sort_order, Workflow.name)
    )
    return [_workflow_to_response(wf) for wf in result.scalars().all()]


@router.get("/workflows/{slug}", response_model=WorkflowResponse)
async def get_workflow(
    slug: str,
    _current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    result = await db.execute(select(Workflow).where(Workflow.slug == slug))
    wf = result.scalar_one_or_none()
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return _workflow_to_response(wf)


@router.post("/workflows", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    body: CreateWorkflowRequest,
    _current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    existing = await db.execute(select(Workflow).where(Workflow.slug == body.slug))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workflow with slug '{body.slug}' already exists",
        )
    wf = Workflow(
        name=body.name,
        slug=body.slug,
        description=body.description,
        system_prompt=body.system_prompt,
        icon=body.icon,
        is_builtin=False,
        sort_order=body.sort_order,
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)
    return _workflow_to_response(wf)


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: UUID,
    _current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if wf.is_builtin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete built-in workflows",
        )
    await db.delete(wf)
    await db.commit()
