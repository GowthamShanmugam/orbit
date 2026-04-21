from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.runtime_setting import RuntimeSetting
from app.models.user import User
from app.services import runtime_settings as rs

router = APIRouter(prefix="/settings", tags=["settings"])

FEATURE_FLAGS_DB_KEY = "feature_flags"


class RuntimeSettingsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    values: dict[str, int | float]
    env_defaults: dict[str, int | float]
    overridden_keys: list[str]
    allow_write: bool


@router.get("/runtime", response_model=RuntimeSettingsResponse)
async def get_runtime_settings(
    _user: Annotated[User, Depends(get_current_user)],
) -> RuntimeSettingsResponse:
    return RuntimeSettingsResponse(
        values=rs.effective_values_snapshot(),
        env_defaults=rs.env_defaults_snapshot(),
        overridden_keys=rs.overridden_key_names(),
        allow_write=settings.RUNTIME_SETTINGS_ALLOW_WRITE,
    )


@router.put("/runtime", response_model=RuntimeSettingsResponse)
async def put_runtime_settings(
    body: rs.RuntimeSettingsUpdate,
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RuntimeSettingsResponse:
    if not settings.RUNTIME_SETTINGS_ALLOW_WRITE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Runtime settings writes are disabled (RUNTIME_SETTINGS_ALLOW_WRITE=false)",
        )
    await rs.apply_runtime_updates(db, body)
    return RuntimeSettingsResponse(
        values=rs.effective_values_snapshot(),
        env_defaults=rs.env_defaults_snapshot(),
        overridden_keys=rs.overridden_key_names(),
        allow_write=settings.RUNTIME_SETTINGS_ALLOW_WRITE,
    )


# ── Global feature flags (tech preview toggles) ─────────────────────────────


@router.get("/feature-flags")
async def get_feature_flags(
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, bool]:
    """Return global feature flags (e.g. system_map)."""
    row = await db.get(RuntimeSetting, FEATURE_FLAGS_DB_KEY)
    if not row or not isinstance(row.value, dict):
        return {}
    return {k: bool(v) for k, v in row.value.items()}


@router.put("/feature-flags")
async def put_feature_flags(
    body: dict[str, bool],
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, bool]:
    """Merge feature flag toggles into the global store."""
    row = await db.get(RuntimeSetting, FEATURE_FLAGS_DB_KEY)
    if row is None:
        row = RuntimeSetting(key=FEATURE_FLAGS_DB_KEY, value={})
        db.add(row)

    current: dict = dict(row.value) if isinstance(row.value, dict) else {}
    current.update(body)
    row.value = current
    await db.commit()
    await db.refresh(row)
    return {k: bool(v) for k, v in row.value.items()}
