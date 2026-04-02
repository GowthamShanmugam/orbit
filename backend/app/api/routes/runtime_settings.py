from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services import runtime_settings as rs

router = APIRouter(prefix="/settings", tags=["settings"])


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
