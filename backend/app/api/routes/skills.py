"""MCP Skills management endpoints.

Global skill catalog: browse available MCP servers, configure credentials,
enable/disable, test connections, and refresh tool caches.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.projects import user_can_mutate_global_skills
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.skill import McpSkill, SkillStatus
from app.models.user import User
from app.services import mcp_client

router = APIRouter()


class SkillResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None
    icon: str | None
    transport: str
    config_schema: dict[str, Any] | None
    has_config: bool
    enabled: bool
    is_builtin: bool
    status: str
    status_message: str | None
    tool_count: int
    created_at: str
    updated_at: str


class ConfigureSkillRequest(BaseModel):
    config_values: dict[str, str]


class SkillCatalogResponse(BaseModel):
    skills: list[SkillResponse]
    can_manage_skills: bool


class CreateSkillRequest(BaseModel):
    name: str
    slug: str
    description: str | None = None
    icon: str | None = None
    transport: str = "stdio"
    server_command: str
    server_args: list[str] | None = None
    server_url: str | None = None
    config_schema: dict[str, Any] | None = None


async def require_can_mutate_skills(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    if not await user_can_mutate_global_skills(db, current.id):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to change workspace skills",
        )


def _skill_to_response(skill: McpSkill) -> dict[str, Any]:
    return {
        "id": str(skill.id),
        "name": skill.name,
        "slug": skill.slug,
        "description": skill.description,
        "icon": skill.icon,
        "transport": skill.transport.value,
        "config_schema": skill.config_schema,
        "has_config": skill.config_values is not None and len(skill.config_values) > 0,
        "enabled": skill.enabled,
        "is_builtin": skill.is_builtin,
        "status": skill.status.value,
        "status_message": skill.status_message,
        "tool_count": len(skill.cached_tools) if skill.cached_tools else 0,
        "created_at": skill.created_at.isoformat() if skill.created_at else "",
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else "",
    }


@router.get("/skills", response_model=SkillCatalogResponse)
async def list_skills(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all MCP skills (global catalog) and whether the user may change them."""
    result = await db.execute(
        select(McpSkill).order_by(McpSkill.is_builtin.desc(), McpSkill.name.asc())
    )
    skills = result.scalars().all()
    can_manage = await user_can_mutate_global_skills(db, current.id)
    return SkillCatalogResponse(
        skills=[SkillResponse(**_skill_to_response(s)) for s in skills],
        can_manage_skills=can_manage,
    )


@router.get("/skills/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: uuid.UUID,
    _current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    skill = await db.get(McpSkill, skill_id)
    if not skill:
        raise HTTPException(404, "Skill not found")
    return _skill_to_response(skill)


@router.post("/skills", response_model=SkillResponse)
async def create_skill(
    body: CreateSkillRequest,
    _perm: Annotated[None, Depends(require_can_mutate_skills)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Add a custom MCP skill."""
    existing = await db.execute(
        select(McpSkill).where(McpSkill.slug == body.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Skill with slug '{body.slug}' already exists")

    from app.models.skill import SkillTransport
    skill = McpSkill(
        name=body.name,
        slug=body.slug,
        description=body.description,
        icon=body.icon,
        transport=SkillTransport(body.transport),
        server_command=body.server_command,
        server_args=body.server_args,
        server_url=body.server_url,
        config_schema=body.config_schema,
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    return _skill_to_response(skill)


@router.put("/skills/{skill_id}/configure", response_model=SkillResponse)
async def configure_skill(
    skill_id: uuid.UUID,
    body: ConfigureSkillRequest,
    _perm: Annotated[None, Depends(require_can_mutate_skills)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Set credentials/config, then immediately test connection and enable."""
    skill = await db.get(McpSkill, skill_id)
    if not skill:
        raise HTTPException(404, "Skill not found")

    skill.config_values = body.config_values
    skill.status = SkillStatus.configured
    skill.status_message = None
    await db.commit()
    await db.refresh(skill)

    result = await mcp_client.test_connection(skill)
    if result["success"]:
        skill.enabled = True
        await mcp_client.refresh_skill_tools(skill, db)
    else:
        skill.status = SkillStatus.error
        skill.status_message = result.get("error", "Connection failed")
        await db.commit()

    await db.refresh(skill)
    return _skill_to_response(skill)


@router.put("/skills/{skill_id}/toggle", response_model=SkillResponse)
async def toggle_skill(
    skill_id: uuid.UUID,
    _perm: Annotated[None, Depends(require_can_mutate_skills)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Enable or disable an MCP skill."""
    skill = await db.get(McpSkill, skill_id)
    if not skill:
        raise HTTPException(404, "Skill not found")

    if not skill.enabled and not skill.config_values:
        raise HTTPException(400, "Configure credentials before enabling")

    skill.enabled = not skill.enabled
    if not skill.enabled:
        skill.cached_tools = None
    await db.commit()
    await db.refresh(skill)
    return _skill_to_response(skill)


@router.post("/skills/{skill_id}/test")
async def test_skill_connection(
    skill_id: uuid.UUID,
    _perm: Annotated[None, Depends(require_can_mutate_skills)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Test connection to an MCP server and return available tools."""
    skill = await db.get(McpSkill, skill_id)
    if not skill:
        raise HTTPException(404, "Skill not found")
    if not skill.config_values:
        raise HTTPException(400, "Configure credentials first")

    result = await mcp_client.test_connection(skill)

    if result["success"]:
        skill.status = SkillStatus.connected
        skill.status_message = f"{result['tool_count']} tools discovered"
    else:
        skill.status = SkillStatus.error
        skill.status_message = result.get("error", "Unknown error")

    await db.commit()
    return result


@router.post("/skills/{skill_id}/refresh", response_model=SkillResponse)
async def refresh_tools(
    skill_id: uuid.UUID,
    _perm: Annotated[None, Depends(require_can_mutate_skills)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Re-fetch and cache tool definitions from the MCP server."""
    skill = await db.get(McpSkill, skill_id)
    if not skill:
        raise HTTPException(404, "Skill not found")
    if not skill.config_values:
        raise HTTPException(400, "Configure credentials first")

    await mcp_client.refresh_skill_tools(skill, db)
    await db.refresh(skill)
    return _skill_to_response(skill)


@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: uuid.UUID,
    _perm: Annotated[None, Depends(require_can_mutate_skills)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a custom MCP skill (builtin skills cannot be deleted)."""
    skill = await db.get(McpSkill, skill_id)
    if not skill:
        raise HTTPException(404, "Skill not found")
    if skill.is_builtin:
        raise HTTPException(400, "Cannot delete builtin skills")

    await db.delete(skill)
    await db.commit()
    return {"deleted": True}
