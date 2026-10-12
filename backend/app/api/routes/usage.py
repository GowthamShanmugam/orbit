"""AI usage / estimated spend endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services import usage_metering

router = APIRouter(prefix="/settings", tags=["settings"])


class UsageBucketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    estimated_cost_usd: float
    calls: int


class UsageModelRow(UsageBucketResponse):
    model: str


class UsageProjectRow(UsageBucketResponse):
    project_id: str | None
    project_name: str


class UsageDayRow(UsageBucketResponse):
    date: str


class UsageTotals(BaseModel):
    today: UsageBucketResponse
    this_month: UsageBucketResponse
    all_time: UsageBucketResponse


class UsageSummaryResponse(BaseModel):
    currency: str
    is_estimate: bool
    pricing_note: str
    provider: str
    totals: UsageTotals
    by_model: list[UsageModelRow]
    by_project: list[UsageProjectRow]
    recent_days: list[UsageDayRow]
    empty: bool


@router.get("/usage", response_model=UsageSummaryResponse)
async def get_usage(
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Return instance-wide estimated AI spend (survives restarts and project deletes)."""
    return await usage_metering.get_usage_summary(db)
