"""Skill Plugin management endpoints.

Two separate concerns:

**Integrations** (MCP tools): Per-user. Each user installs, configures their
own credentials, and enables. Tools auto-appear in that user's chat sessions.

**Skills** (Prompt packs): Public. Available to all users without install.
Users invoke on-demand via /command in chat. No credentials needed.
"""

from __future__ import annotations

import contextlib
import re
import uuid
from typing import Annotated, Any

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.projects import require_project_access, user_can_mutate_global_skills
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.skill import (
    PluginSkill,
    PluginSource,
    PluginType,
    ProjectSkillPack,
    SkillCategory,
    SkillPlugin,
    SkillStatus,
    SkillTransport,
    UserPluginConfig,
)
from app.models.user import User
from app.services import mcp_client

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SkillResponse(BaseModel):
    name: str
    slug: str
    description: str | None
    system_prompt: str | None = None
    user_invocable: bool


class IntegrationResponse(BaseModel):
    """An MCP integration with per-user credential state."""

    id: str
    name: str
    slug: str
    description: str | None
    version: str
    icon: str | None
    tags: list[str] | None
    transport: str | None
    config_schema: dict[str, Any] | None
    is_builtin: bool
    source: str
    source_repo: str | None
    tool_count: int
    configured: bool
    status: str
    status_message: str | None
    created_at: str
    updated_at: str


class SkillPluginResponse(BaseModel):
    """A public skill pack (prompt-based)."""

    id: str
    name: str
    slug: str
    description: str | None
    icon: str | None
    tags: list[str] | None
    category_name: str | None
    category_slug: str | None
    is_builtin: bool
    skills: list[SkillResponse]
    skill_count: int
    created_at: str


class IntegrationListResponse(BaseModel):
    integrations: list[IntegrationResponse]
    can_manage: bool


class SkillListResponse(BaseModel):
    skills: list[SkillPluginResponse]
    categories: list[dict[str, Any]]


class ConfigureIntegrationRequest(BaseModel):
    config_values: dict[str, str]


class CreateIntegrationRequest(BaseModel):
    name: str
    slug: str
    description: str | None = None
    icon: str | None = None
    tags: list[str] | None = None
    transport: str = "stdio"
    server_command: str
    server_args: list[str] | None = None
    server_url: str | None = None
    config_schema: dict[str, Any] | None = None
    source_repo: str | None = None


class CreateSkillPackRequest(BaseModel):
    name: str
    slug: str
    description: str | None = None
    icon: str | None = None
    tags: list[str] | None = None
    category_slug: str | None = None
    visibility: str = "public"
    skills: list[dict[str, Any]]


class ImportGitHubSkillRequest(BaseModel):
    repo_url: str
    name: str | None = None
    category_slug: str | None = None
    visibility: str = "public"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def require_can_manage(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    if not await user_can_mutate_global_skills(db, current.id):
        raise HTTPException(403, "You do not have permission to manage workspace plugins")


def _integration_to_response(
    plugin: SkillPlugin,
    user_config: UserPluginConfig | None,
) -> dict[str, Any]:
    has_creds = (
        user_config is not None
        and user_config.config_values is not None
        and len(user_config.config_values) > 0
    )
    return {
        "id": str(plugin.id),
        "name": plugin.name,
        "slug": plugin.slug,
        "description": plugin.description,
        "version": plugin.version,
        "icon": plugin.icon,
        "tags": plugin.tags,
        "transport": plugin.transport.value if plugin.transport else None,
        "config_schema": plugin.config_schema,
        "is_builtin": plugin.is_builtin,
        "source": plugin.source.value,
        "source_repo": plugin.source_repo,
        "tool_count": len(plugin.cached_tools) if plugin.cached_tools else 0,
        "configured": has_creds,
        "status": user_config.status.value if user_config else SkillStatus.available.value,
        "status_message": user_config.status_message if user_config else None,
        "created_at": plugin.created_at.isoformat() if plugin.created_at else "",
        "updated_at": plugin.updated_at.isoformat() if plugin.updated_at else "",
    }


def _skill_pack_to_response(plugin: SkillPlugin) -> dict[str, Any]:
    skills = (
        [
            {
                "name": s.name,
                "slug": s.slug,
                "description": s.description,
                "system_prompt": s.system_prompt,
                "user_invocable": s.user_invocable,
            }
            for s in sorted(plugin.skills, key=lambda s: s.sort_order)
        ]
        if plugin.skills
        else []
    )

    return {
        "id": str(plugin.id),
        "name": plugin.name,
        "slug": plugin.slug,
        "description": plugin.description,
        "icon": plugin.icon,
        "tags": plugin.tags,
        "category_name": plugin.category.name if plugin.category else None,
        "category_slug": plugin.category.slug if plugin.category else None,
        "is_builtin": plugin.is_builtin,
        "visibility": plugin.visibility,
        "skills": skills,
        "skill_count": len([s for s in (plugin.skills or []) if s.user_invocable]),
        "created_at": plugin.created_at.isoformat() if plugin.created_at else "",
    }


# ===========================================================================
# INTEGRATIONS endpoints (per-user credentials, enabled per session)
# ===========================================================================


@router.get("/integrations", response_model=IntegrationListResponse)
async def list_integrations(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List MCP integrations with the current user's credential state."""
    result = await db.execute(
        select(SkillPlugin)
        .where(SkillPlugin.plugin_type.in_([PluginType.mcp, PluginType.hybrid]))
        .order_by(SkillPlugin.sort_order.asc(), SkillPlugin.name.asc())
    )
    plugins = result.scalars().all()

    configs_result = await db.execute(
        select(UserPluginConfig).where(UserPluginConfig.user_id == current.id)
    )
    user_configs = {cfg.plugin_id: cfg for cfg in configs_result.scalars().all()}

    can_manage = await user_can_mutate_global_skills(db, current.id)

    return IntegrationListResponse(
        integrations=[
            IntegrationResponse(**_integration_to_response(p, user_configs.get(p.id)))
            for p in plugins
        ],
        can_manage=can_manage,
    )


@router.put("/integrations/{plugin_id}/configure", response_model=IntegrationResponse)
async def configure_integration(
    plugin_id: uuid.UUID,
    body: ConfigureIntegrationRequest,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Set the current user's credentials and test connection."""
    plugin = await db.get(SkillPlugin, plugin_id)
    if not plugin:
        raise HTTPException(404, "Integration not found")

    config_result = await db.execute(
        select(UserPluginConfig).where(
            UserPluginConfig.user_id == current.id,
            UserPluginConfig.plugin_id == plugin_id,
        )
    )
    user_config = config_result.scalar_one_or_none()
    if not user_config:
        user_config = UserPluginConfig(user_id=current.id, plugin_id=plugin_id)
        db.add(user_config)

    user_config.config_values = body.config_values
    user_config.enabled = True
    user_config.status = SkillStatus.configured
    user_config.status_message = None
    await db.commit()
    await db.refresh(user_config)

    try:
        result = await mcp_client.test_connection(plugin, user_config)
    except Exception as exc:
        user_config.status = SkillStatus.error
        user_config.status_message = f"Test failed: {exc}"
        user_config.enabled = False
        await db.commit()
        await db.refresh(user_config)
        await db.refresh(plugin)
        return _integration_to_response(plugin, user_config)

    if result["success"]:
        user_config.status = SkillStatus.connected
        user_config.enabled = True
        user_config.status_message = f"{result['tool_count']} tools discovered"
        await db.commit()
        with contextlib.suppress(Exception):
            await mcp_client.refresh_plugin_tools(plugin, user_config, db)
    else:
        user_config.status = SkillStatus.error
        user_config.enabled = False
        user_config.status_message = result.get("error", "Connection failed")
        await db.commit()

    await db.refresh(user_config)
    await db.refresh(plugin)
    return _integration_to_response(plugin, user_config)


@router.post("/integrations/{plugin_id}/test")
async def test_integration(
    plugin_id: uuid.UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Test connection using the current user's credentials."""
    plugin = await db.get(SkillPlugin, plugin_id)
    if not plugin:
        raise HTTPException(404, "Integration not found")

    config_result = await db.execute(
        select(UserPluginConfig).where(
            UserPluginConfig.user_id == current.id,
            UserPluginConfig.plugin_id == plugin_id,
        )
    )
    user_config = config_result.scalar_one_or_none()
    if not user_config or not user_config.config_values:
        raise HTTPException(400, "Configure your credentials first")

    result = await mcp_client.test_connection(plugin, user_config)
    if result["success"]:
        user_config.status = SkillStatus.connected
        user_config.enabled = True
        user_config.status_message = f"{result['tool_count']} tools discovered"
    else:
        user_config.status = SkillStatus.error
        user_config.enabled = False
        user_config.status_message = result.get("error", "Unknown error")
    await db.commit()
    return result


@router.post("/integrations", response_model=IntegrationResponse)
async def create_integration(
    body: CreateIntegrationRequest,
    current: Annotated[User, Depends(get_current_user)],
    _perm: Annotated[None, Depends(require_can_manage)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Add a custom MCP integration to the catalog."""
    existing = await db.execute(select(SkillPlugin).where(SkillPlugin.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Plugin with slug '{body.slug}' already exists")

    plugin = SkillPlugin(
        name=body.name,
        slug=body.slug,
        description=body.description,
        icon=body.icon,
        tags=body.tags,
        plugin_type=PluginType.mcp,
        source=PluginSource.github if body.source_repo else PluginSource.custom,
        source_repo=body.source_repo,
        transport=SkillTransport(body.transport),
        server_command=body.server_command,
        server_args=body.server_args,
        server_url=body.server_url,
        config_schema=body.config_schema,
    )
    db.add(plugin)
    await db.commit()
    await db.refresh(plugin)
    return _integration_to_response(plugin, None)


@router.delete("/integrations/{plugin_id}")
async def delete_integration(
    plugin_id: uuid.UUID,
    _perm: Annotated[None, Depends(require_can_manage)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a custom integration (builtin cannot be deleted)."""
    plugin = await db.get(SkillPlugin, plugin_id)
    if not plugin:
        raise HTTPException(404, "Integration not found")
    if plugin.is_builtin:
        raise HTTPException(400, "Cannot delete builtin integrations")
    await db.delete(plugin)
    await db.commit()
    return {"deleted": True}


# ===========================================================================
# SKILLS endpoints (public prompt packs -- no install needed)
# ===========================================================================


@router.get("/skills", response_model=SkillListResponse)
async def list_skills(
    _current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List skill packs visible to the current user (public + own private)."""
    from sqlalchemy import or_

    result = await db.execute(
        select(SkillPlugin)
        .where(SkillPlugin.plugin_type.in_([PluginType.prompt, PluginType.hybrid]))
        .where(
            or_(
                SkillPlugin.visibility == "public",
                SkillPlugin.created_by == _current.id,
            )
        )
        .order_by(SkillPlugin.sort_order.asc(), SkillPlugin.name.asc())
    )
    plugins = result.scalars().all()

    cats_result = await db.execute(select(SkillCategory).order_by(SkillCategory.sort_order.asc()))
    categories = [
        {"name": c.name, "slug": c.slug, "description": c.description}
        for c in cats_result.scalars().all()
    ]

    return SkillListResponse(
        skills=[SkillPluginResponse(**_skill_pack_to_response(p)) for p in plugins],
        categories=categories,
    )


@router.post("/skills", response_model=SkillPluginResponse)
async def create_skill_pack(
    body: CreateSkillPackRequest,
    _current: Annotated[User, Depends(get_current_user)],
    _perm: Annotated[None, Depends(require_can_manage)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Add a custom skill pack to the catalog (public, no install needed)."""
    existing = await db.execute(select(SkillPlugin).where(SkillPlugin.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Skill pack with slug '{body.slug}' already exists")

    cat_id = None
    if body.category_slug:
        cat_result = await db.execute(
            select(SkillCategory).where(SkillCategory.slug == body.category_slug)
        )
        cat = cat_result.scalar_one_or_none()
        if cat:
            cat_id = cat.id

    plugin = SkillPlugin(
        name=body.name,
        slug=body.slug,
        description=body.description,
        icon=body.icon,
        tags=body.tags,
        plugin_type=PluginType.prompt,
        source=PluginSource.custom,
        is_builtin=False,
        visibility=body.visibility,
        created_by=_current.id,
        category_id=cat_id,
    )
    db.add(plugin)
    await db.flush()

    for skill_data in body.skills:
        skill = PluginSkill(
            plugin_id=plugin.id,
            name=skill_data["name"],
            slug=skill_data["slug"],
            description=skill_data.get("description"),
            system_prompt=skill_data.get("system_prompt"),
            user_invocable=skill_data.get("user_invocable", True),
        )
        db.add(skill)

    await db.commit()
    await db.refresh(plugin)
    return _skill_pack_to_response(plugin)


@router.delete("/skills/{plugin_id}")
async def delete_skill_pack(
    plugin_id: uuid.UUID,
    _perm: Annotated[None, Depends(require_can_manage)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a custom skill pack (builtin cannot be deleted)."""
    plugin = await db.get(SkillPlugin, plugin_id)
    if not plugin:
        raise HTTPException(404, "Skill pack not found")
    if plugin.is_builtin:
        raise HTTPException(400, "Cannot delete builtin skill packs")
    await db.delete(plugin)
    await db.commit()
    return {"deleted": True}


class ImportGitHubResponse(BaseModel):
    imported: list[SkillPluginResponse]
    skipped: list[str]
    total: int


@router.post("/skills/import-github", response_model=ImportGitHubResponse)
async def import_skill_from_github(
    body: ImportGitHubSkillRequest,
    _current: Annotated[User, Depends(get_current_user)],
    _perm: Annotated[None, Depends(require_can_manage)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Import skill packs from a GitHub repository.

    Supports two patterns:
    1. **Registry repo** (has registry.yaml) -- imports each plugin listed in
       the registry as a separate skill pack. Fetches actual skill definitions
       from each plugin's source repository.
    2. **Single skill repo** -- fetches CLAUDE.md / AGENTS.md / SKILL.md and
       creates one skill pack from it.
    """
    owner, repo = _parse_github_url(body.repo_url)
    raw_base = f"https://raw.githubusercontent.com/{owner}/{repo}/main"

    registry = await _try_fetch_registry(raw_base)
    if registry:
        return await _import_from_registry(
            registry,
            owner,
            repo,
            body.category_slug,
            body.visibility,
            _current.id,
            db,
        )

    return await _import_single_skill(
        raw_base,
        owner,
        repo,
        body.name,
        body.category_slug,
        body.visibility,
        _current.id,
        db,
    )


# ---------------------------------------------------------------------------
# GitHub import helpers
# ---------------------------------------------------------------------------


def _parse_github_url(url: str) -> tuple[str, str]:
    """Extract owner/repo from a GitHub URL or 'owner/repo' shorthand."""
    url = url.strip().rstrip("/")
    match = re.match(r"(?:https?://github\.com/)?([^/]+)/([^/]+?)(?:\.git)?$", url)
    if not match:
        raise HTTPException(
            400, "Invalid GitHub URL. Use https://github.com/owner/repo or owner/repo"
        )
    return match.group(1), match.group(2)


async def _try_fetch_registry(raw_base: str) -> dict[str, Any] | None:
    """Check if the repo has a registry.yaml and parse it."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{raw_base}/registry.yaml")
        if resp.status_code != 200:
            return None
        try:
            data = yaml.safe_load(resp.text)
            if isinstance(data, dict) and "plugins" in data:
                return data
        except yaml.YAMLError:
            pass
    return None


async def _import_from_registry(
    registry: dict[str, Any],
    owner: str,
    repo: str,
    category_slug: str | None,
    visibility: str,
    created_by: uuid.UUID,
    db: AsyncSession,
) -> dict[str, Any]:
    """Import all plugins from a registry.yaml."""
    reg_categories = registry.get("categories", {})
    cat_cache: dict[str, uuid.UUID] = {}

    for cat_key, cat_info in reg_categories.items():
        cat_name = cat_info.get("name", cat_key.replace("-", " ").title())
        cat_slug_val = re.sub(r"[^a-z0-9]+", "-", cat_key.lower()).strip("-")
        existing = await db.execute(select(SkillCategory).where(SkillCategory.slug == cat_slug_val))
        cat_obj = existing.scalar_one_or_none()
        if not cat_obj:
            cat_obj = SkillCategory(
                name=cat_name,
                slug=cat_slug_val,
                description=cat_info.get("description"),
            )
            db.add(cat_obj)
            await db.flush()
        cat_cache[cat_key] = cat_obj.id

    plugins_data = registry.get("plugins", [])
    imported = []
    skipped = []

    for p in plugins_data:
        p_name = p.get("name", "")
        p_slug = re.sub(r"[^a-z0-9]+", "-", p_name.lower()).strip("-")
        if not p_slug:
            continue

        existing = await db.execute(select(SkillPlugin).where(SkillPlugin.slug == p_slug))
        if existing.scalar_one_or_none():
            skipped.append(f"{p_name} (already exists)")
            continue

        p_cat_key = p.get("category")
        cat_id = cat_cache.get(p_cat_key) if p_cat_key else None
        if not cat_id and category_slug:
            cat_result = await db.execute(
                select(SkillCategory).where(SkillCategory.slug == category_slug)
            )
            cat_row = cat_result.scalar_one_or_none()
            if cat_row:
                cat_id = cat_row.id

        source_info = p.get("source", {})
        source_repo_str = source_info.get("repo", "")
        source_url = f"https://github.com/{source_repo_str}" if source_repo_str else None

        plugin = SkillPlugin(
            name=p_name.replace("-", " ").title(),
            slug=p_slug,
            description=p.get("description", "").strip(),
            version=p.get("version", "1.0.0"),
            plugin_type=PluginType.prompt,
            source=PluginSource.github,
            source_repo=source_url,
            is_builtin=False,
            visibility=visibility,
            created_by=created_by,
            category_id=cat_id,
            tags=p.get("tags", []) + ["imported", f"registry:{owner}/{repo}"],
        )
        db.add(plugin)
        await db.flush()

        p_skills = p.get("skills", [])
        skill_prompts = await _fetch_plugin_skill_prompts(source_info)

        for idx, s in enumerate(p_skills):
            s_name = s.get("name", f"skill-{idx}")
            s_slug = re.sub(r"[^a-z0-9.]+", "-", s_name.lower()).strip("-")
            full_slug = f"{p_slug}.{s_slug}" if "." not in s_slug else s_slug
            invocable = s.get("user-invocable", True)

            prompt = skill_prompts.get(s_name, "")
            if not prompt:
                prompt = f"You are executing the '{s_name}' skill.\n\n{s.get('description', '')}"

            db.add(
                PluginSkill(
                    plugin_id=plugin.id,
                    name=s_name.replace("-", " ").replace(".", " ").title(),
                    slug=full_slug,
                    description=s.get("description", ""),
                    system_prompt=prompt,
                    user_invocable=invocable,
                    sort_order=idx,
                )
            )

        await db.flush()
        await db.refresh(plugin)
        imported.append(SkillPluginResponse(**_skill_pack_to_response(plugin)))

    await db.commit()

    return {
        "imported": imported,
        "skipped": skipped,
        "total": len(plugins_data),
    }


async def _fetch_plugin_skill_prompts(
    source: dict[str, Any],
) -> dict[str, str]:
    """Fetch actual skill prompt files from a plugin's source repo.

    Looks in the skills_dir (or common paths) for individual .md files
    matching skill names.
    """
    source_repo = source.get("repo", "")
    ref = source.get("ref", "main")
    skills_dir = source.get("skills_dir", ".claude/skills")

    if not source_repo:
        return {}

    raw_base = f"https://raw.githubusercontent.com/{source_repo}/{ref}"
    prompts: dict[str, str] = {}

    skill_dirs = [skills_dir, ".claude/skills", "skills", ".cursor-plugin/skills"]
    seen_dirs: set[str] = set()

    async with httpx.AsyncClient(timeout=10) as client:
        for sdir in skill_dirs:
            if sdir in seen_dirs:
                continue
            seen_dirs.add(sdir)

            listing_url = f"https://api.github.com/repos/{source_repo}/contents/{sdir}?ref={ref}"
            resp = await client.get(
                listing_url, headers={"Accept": "application/vnd.github.v3+json"}
            )
            if resp.status_code != 200:
                continue

            try:
                files = resp.json()
            except Exception:
                continue

            if not isinstance(files, list):
                continue

            for f in files:
                fname = f.get("name", "")
                if not fname.endswith(".md"):
                    continue
                skill_name = fname.removesuffix(".md")

                dl = f.get("download_url") or f"{raw_base}/{sdir}/{fname}"
                content_resp = await client.get(dl)
                if content_resp.status_code == 200 and content_resp.text.strip():
                    prompts[skill_name] = content_resp.text.strip()

            if prompts:
                break

    return prompts


_SKILL_FILES = [
    "CLAUDE.md",
    "AGENTS.md",
    "SKILL.md",
    "skills/SKILL.md",
    ".claude-plugin/SKILL.md",
    ".cursor-plugin/SKILL.md",
    "README.md",
]


async def _import_single_skill(
    raw_base: str,
    owner: str,
    repo: str,
    custom_name: str | None,
    category_slug: str | None,
    visibility: str,
    created_by: uuid.UUID,
    db: AsyncSession,
) -> dict[str, Any]:
    """Import a single skill repo (not a registry)."""
    skill_content = await _fetch_skill_content(raw_base, owner, repo)

    slug = re.sub(r"[^a-z0-9]+", "-", repo.lower()).strip("-")
    name = custom_name or repo.replace("-", " ").title()

    existing = await db.execute(select(SkillPlugin).where(SkillPlugin.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Skill pack '{slug}' already exists")

    cat_id = None
    if category_slug:
        cat_result = await db.execute(
            select(SkillCategory).where(SkillCategory.slug == category_slug)
        )
        cat = cat_result.scalar_one_or_none()
        if cat:
            cat_id = cat.id

    plugin = SkillPlugin(
        name=name,
        slug=slug,
        description=f"Imported from github.com/{owner}/{repo}",
        plugin_type=PluginType.prompt,
        source=PluginSource.github,
        source_repo=f"https://github.com/{owner}/{repo}",
        is_builtin=False,
        visibility=visibility,
        created_by=created_by,
        category_id=cat_id,
        tags=["github", "imported"],
    )
    db.add(plugin)
    await db.flush()

    skills_parsed = _parse_skill_sections(skill_content, slug)
    for s in skills_parsed:
        db.add(
            PluginSkill(
                plugin_id=plugin.id,
                name=s["name"],
                slug=s["slug"],
                description=s["description"],
                system_prompt=s["system_prompt"],
                user_invocable=True,
            )
        )

    await db.commit()
    await db.refresh(plugin)

    return {
        "imported": [SkillPluginResponse(**_skill_pack_to_response(plugin))],
        "skipped": [],
        "total": 1,
    }


async def _fetch_skill_content(raw_base: str, owner: str, repo: str) -> str:
    """Try multiple known skill file paths and return the first found."""
    async with httpx.AsyncClient(timeout=15) as client:
        for path in _SKILL_FILES:
            resp = await client.get(f"{raw_base}/{path}")
            if resp.status_code == 200 and len(resp.text.strip()) > 50:
                return resp.text

    raise HTTPException(
        404,
        f"Could not find a skill definition in {owner}/{repo}. "
        f"Expected one of: {', '.join(_SKILL_FILES)}",
    )


def _parse_skill_sections(content: str, base_slug: str) -> list[dict[str, Any]]:
    """Parse markdown into individual skill entries.

    If the content has ## headings, each heading becomes a separate skill.
    Otherwise, the entire content becomes a single skill.
    """
    sections = re.split(r"^## (.+)$", content, flags=re.MULTILINE)

    if len(sections) <= 1:
        return [
            {
                "name": base_slug.replace("-", " ").title(),
                "slug": base_slug,
                "description": _first_paragraph(content),
                "system_prompt": content.strip(),
            }
        ]

    skills: list[dict[str, Any]] = []
    preamble = sections[0].strip()
    for i in range(1, len(sections), 2):
        heading = sections[i].strip()
        body = sections[i + 1].strip() if i + 1 < len(sections) else ""

        skill_slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
        full_slug = f"{base_slug}.{skill_slug}"

        prompt_parts = []
        if preamble:
            prompt_parts.append(preamble)
        prompt_parts.append(f"## {heading}\n\n{body}")

        skills.append(
            {
                "name": heading,
                "slug": full_slug,
                "description": _first_paragraph(body),
                "system_prompt": "\n\n".join(prompt_parts),
            }
        )

    if not skills:
        return [
            {
                "name": base_slug.replace("-", " ").title(),
                "slug": base_slug,
                "description": _first_paragraph(content),
                "system_prompt": content.strip(),
            }
        ]

    return skills


def _first_paragraph(text: str) -> str:
    """Extract the first non-empty paragraph as a description."""
    for line in text.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("```"):
            return line[:200]
    return ""


# ===========================================================================
# PROJECT-SCOPED SKILL ENDPOINTS
# ===========================================================================


@router.get("/projects/{project_id}/skills")
async def list_project_skills(
    project_id: uuid.UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List skill packs available in this project (installed + built-in)."""
    await require_project_access(db, current.id, project_id)

    installed_result = await db.execute(
        select(ProjectSkillPack)
        .where(ProjectSkillPack.project_id == project_id)
        .order_by(ProjectSkillPack.installed_at.desc())
    )
    installed_rows = installed_result.scalars().all()
    installed_plugin_ids = {row.skill_plugin_id for row in installed_rows}

    builtin_result = await db.execute(
        select(SkillPlugin).where(
            SkillPlugin.plugin_type.in_([PluginType.prompt, PluginType.hybrid]),
            SkillPlugin.is_builtin,
        )
    )
    builtin_plugins = builtin_result.scalars().all()

    if installed_plugin_ids:
        custom_result = await db.execute(
            select(SkillPlugin).where(SkillPlugin.id.in_(installed_plugin_ids))
        )
        custom_plugins = custom_result.scalars().all()
    else:
        custom_plugins = []

    all_plugins = {p.id: p for p in builtin_plugins}
    for p in custom_plugins:
        all_plugins[p.id] = p

    cats_result = await db.execute(select(SkillCategory).order_by(SkillCategory.sort_order.asc()))
    all_cats = cats_result.scalars().all()

    skills_out = []
    for plugin in sorted(all_plugins.values(), key=lambda p: (p.sort_order, p.name)):
        resp = _skill_pack_to_response(plugin)
        resp["installed"] = plugin.is_builtin or plugin.id in installed_plugin_ids
        skills_out.append(resp)

    used_slugs = {p.category.slug for p in all_plugins.values() if p.category}
    categories = [
        {"name": c.name, "slug": c.slug, "description": c.description}
        for c in all_cats
        if c.slug in used_slugs
    ]

    return {"skills": skills_out, "categories": categories}


@router.get("/projects/{project_id}/skills/available")
async def list_available_skills(
    project_id: uuid.UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List skill packs that can be installed to this project (not yet installed, not built-in)."""
    await require_project_access(db, current.id, project_id, min_access="write")

    installed_result = await db.execute(
        select(ProjectSkillPack.skill_plugin_id).where(ProjectSkillPack.project_id == project_id)
    )
    installed_ids = {row for row in installed_result.scalars().all()}

    from sqlalchemy import or_

    result = await db.execute(
        select(SkillPlugin)
        .where(
            SkillPlugin.plugin_type.in_([PluginType.prompt, PluginType.hybrid]),
            ~SkillPlugin.is_builtin,
            SkillPlugin.id.notin_(installed_ids) if installed_ids else True,
            or_(
                SkillPlugin.visibility == "public",
                SkillPlugin.created_by == current.id,
            ),
        )
        .order_by(SkillPlugin.name.asc())
    )
    plugins = result.scalars().all()

    return {
        "skills": [_skill_pack_to_response(p) for p in plugins],
    }


@router.post("/projects/{project_id}/skills/{plugin_id}/install")
async def install_skill_to_project(
    project_id: uuid.UUID,
    plugin_id: uuid.UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Install a skill pack to a project."""
    await require_project_access(db, current.id, project_id, min_access="write")

    plugin = await db.get(SkillPlugin, plugin_id)
    if not plugin:
        raise HTTPException(404, "Skill pack not found")
    if plugin.is_builtin:
        raise HTTPException(400, "Built-in skill packs are always available")

    existing = await db.execute(
        select(ProjectSkillPack).where(
            ProjectSkillPack.project_id == project_id,
            ProjectSkillPack.skill_plugin_id == plugin_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Skill pack already installed in this project")

    row = ProjectSkillPack(
        project_id=project_id,
        skill_plugin_id=plugin_id,
        installed_by=current.id,
    )
    db.add(row)
    await db.commit()

    resp = _skill_pack_to_response(plugin)
    resp["installed"] = True
    return resp


@router.delete("/projects/{project_id}/skills/{plugin_id}/uninstall")
async def uninstall_skill_from_project(
    project_id: uuid.UUID,
    plugin_id: uuid.UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Remove a skill pack from a project."""
    await require_project_access(db, current.id, project_id, min_access="write")

    result = await db.execute(
        select(ProjectSkillPack).where(
            ProjectSkillPack.project_id == project_id,
            ProjectSkillPack.skill_plugin_id == plugin_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Skill pack not installed in this project")

    await db.delete(row)
    await db.commit()
    return {"deleted": True}
