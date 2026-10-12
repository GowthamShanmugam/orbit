"""Record AI token usage and estimate USD cost from published rates.

Costs are estimates (not GCP invoice amounts). Events are written in a
separate DB session so they commit even if the chat transaction rolls back,
and FKs use SET NULL so spend survives project/session deletes.
"""

from __future__ import annotations

import contextvars
import logging
import uuid
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.usage_event import UsageEvent

logger = logging.getLogger(__name__)

# USD per 1M tokens (Anthropic list / Vertex base). Regional Vertex often
# adds ~10% — applied when CLAUDE_PROVIDER=vertex.
_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5-20250929": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

# Cache token multipliers vs input price (Anthropic / Vertex common pattern).
_CACHE_READ_MULT = 0.1
_CACHE_WRITE_MULT = 1.25
_VERTEX_REGIONAL_MULT = 1.10

PRICING_NOTE = (
    "Estimated from published Claude token rates "
    "(not your GCP invoice). Vertex regional endpoints may differ slightly. "
    "Prompt cache reads are ~10% of input price; first write may cost a bit more."
)


@dataclass(frozen=True)
class UsageContext:
    user_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    session_id: uuid.UUID | None = None
    thread_id: uuid.UUID | None = None
    kind: str = "chat"


_usage_ctx: contextvars.ContextVar[UsageContext | None] = contextvars.ContextVar(
    "orbit_usage_ctx", default=None
)


def activate_usage_context(
    *,
    user_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    project_name: str | None = None,
    session_id: uuid.UUID | None = None,
    thread_id: uuid.UUID | None = None,
    kind: str = "chat",
) -> contextvars.Token:
    """Set tracking context; pair with ``deactivate_usage_context`` in finally."""
    return _usage_ctx.set(
        UsageContext(
            user_id=user_id,
            project_id=project_id,
            project_name=project_name,
            session_id=session_id,
            thread_id=thread_id,
            kind=kind,
        )
    )


def deactivate_usage_context(token: contextvars.Token) -> None:
    _usage_ctx.reset(token)


@asynccontextmanager
async def usage_tracking_context(
    *,
    user_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    project_name: str | None = None,
    session_id: uuid.UUID | None = None,
    thread_id: uuid.UUID | None = None,
    kind: str = "chat",
) -> AsyncIterator[None]:
    token = activate_usage_context(
        user_id=user_id,
        project_id=project_id,
        project_name=project_name,
        session_id=session_id,
        thread_id=thread_id,
        kind=kind,
    )
    try:
        yield
    finally:
        deactivate_usage_context(token)


@contextmanager
def usage_kind(kind: str) -> Iterator[None]:
    """Temporarily override the usage kind within an active tracking context."""
    current = _usage_ctx.get()
    if current is None:
        yield
        return
    token = _usage_ctx.set(
        UsageContext(
            user_id=current.user_id,
            project_id=current.project_id,
            project_name=current.project_name,
            session_id=current.session_id,
            thread_id=current.thread_id,
            kind=kind,
        )
    )
    try:
        yield
    finally:
        _usage_ctx.reset(token)


def normalize_model_id(model: str) -> str:
    """Map wire / Vertex ids back to a pricing key when possible."""
    m = model.strip()
    if "@" in m:
        # claude-sonnet-4-5@20250929 → claude-sonnet-4-5-20250929
        base, ver = m.split("@", 1)
        if ver and ver != "default":
            candidate = f"{base}-{ver}"
            if candidate in _PRICE_PER_MTOK or any(
                candidate.startswith(k) for k in _PRICE_PER_MTOK
            ):
                return candidate
        return base
    return m


def _lookup_prices(model: str) -> tuple[float, float]:
    key = normalize_model_id(model)
    if key in _PRICE_PER_MTOK:
        return _PRICE_PER_MTOK[key]
    for prefix, prices in _PRICE_PER_MTOK.items():
        if key.startswith(prefix):
            return prices
    # Unknown model — Sonnet-like mid-tier fallback
    return (3.0, 15.0)


def estimate_cost_usd(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    in_price, out_price = _lookup_prices(model)
    if settings.CLAUDE_PROVIDER == "vertex":
        in_price *= _VERTEX_REGIONAL_MULT
        out_price *= _VERTEX_REGIONAL_MULT

    # Non-cache input is billed at full input rate; cache tokens separately.
    billable_input = max(0, input_tokens - cache_read_tokens - cache_creation_tokens)
    cost = (
        billable_input * in_price
        + output_tokens * out_price
        + cache_read_tokens * in_price * _CACHE_READ_MULT
        + cache_creation_tokens * in_price * _CACHE_WRITE_MULT
    ) / 1_000_000
    return round(cost, 8)


def _tokens_from_usage(usage: Any) -> tuple[int, int, int, int]:
    if usage is None:
        return 0, 0, 0, 0
    inp = int(getattr(usage, "input_tokens", 0) or 0)
    out = int(getattr(usage, "output_tokens", 0) or 0)
    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cache_create = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    return inp, out, cache_read, cache_create


async def record_response_usage(
    response: Any,
    *,
    model: str,
    kind: str | None = None,
    user_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    project_name: str | None = None,
    session_id: uuid.UUID | None = None,
    thread_id: uuid.UUID | None = None,
) -> None:
    """Persist usage from an Anthropic Messages response. Never raises."""
    try:
        ctx = _usage_ctx.get()
        usage = getattr(response, "usage", None)
        inp, out, cache_read, cache_create = _tokens_from_usage(usage)
        if inp == 0 and out == 0 and cache_read == 0 and cache_create == 0:
            return

        event_kind = kind or (ctx.kind if ctx else "chat")
        uid = user_id if user_id is not None else (ctx.user_id if ctx else None)
        pid = project_id if project_id is not None else (ctx.project_id if ctx else None)
        pname = project_name if project_name is not None else (ctx.project_name if ctx else None)
        sid = session_id if session_id is not None else (ctx.session_id if ctx else None)
        tid = thread_id if thread_id is not None else (ctx.thread_id if ctx else None)

        model_key = normalize_model_id(model)
        cost = estimate_cost_usd(
            model=model_key,
            input_tokens=inp,
            output_tokens=out,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_create,
        )

        event = UsageEvent(
            id=uuid.uuid4(),
            user_id=uid,
            project_id=pid,
            project_name=pname,
            session_id=sid,
            thread_id=tid,
            model=model_key,
            kind=event_kind,
            input_tokens=inp,
            output_tokens=out,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_create,
            estimated_cost_usd=cost,
        )
        async with AsyncSessionLocal() as db:
            db.add(event)
            await db.commit()
    except Exception:
        logger.exception("Failed to record AI usage event")


@dataclass
class UsageBucket:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    estimated_cost_usd: float = 0.0
    calls: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "calls": self.calls,
        }


async def get_usage_summary(db: AsyncSession) -> dict[str, Any]:
    """Aggregate usage for Settings UI (instance-wide)."""
    now = datetime.now(timezone.utc)
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def _sum_cols():
        return (
            func.coalesce(func.sum(UsageEvent.input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cache_read_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cache_creation_tokens), 0),
            func.coalesce(func.sum(UsageEvent.estimated_cost_usd), 0.0),
            func.count(UsageEvent.id),
        )

    async def _period(since: datetime | None) -> dict[str, Any]:
        q = select(*_sum_cols())
        if since is not None:
            q = q.where(UsageEvent.created_at >= since)
        row = (await db.execute(q)).one()
        return UsageBucket(
            input_tokens=int(row[0]),
            output_tokens=int(row[1]),
            cache_read_tokens=int(row[2]),
            cache_creation_tokens=int(row[3]),
            estimated_cost_usd=float(row[4]),
            calls=int(row[5]),
        ).as_dict()

    totals = {
        "today": await _period(start_today),
        "this_month": await _period(start_month),
        "all_time": await _period(None),
    }

    by_model_rows = (
        await db.execute(
            select(
                UsageEvent.model,
                *_sum_cols(),
            )
            .where(UsageEvent.created_at >= start_month)
            .group_by(UsageEvent.model)
            .order_by(func.sum(UsageEvent.estimated_cost_usd).desc())
        )
    ).all()
    by_model = [
        {
            "model": r[0],
            **UsageBucket(
                input_tokens=int(r[1]),
                output_tokens=int(r[2]),
                cache_read_tokens=int(r[3]),
                cache_creation_tokens=int(r[4]),
                estimated_cost_usd=float(r[5]),
                calls=int(r[6]),
            ).as_dict(),
        }
        for r in by_model_rows
    ]

    display_name = func.coalesce(UsageEvent.project_name, "(deleted project)")
    by_project_rows = (
        await db.execute(
            select(
                UsageEvent.project_id,
                display_name.label("name"),
                *_sum_cols(),
            )
            .where(UsageEvent.created_at >= start_month)
            .group_by(UsageEvent.project_id, display_name)
            .order_by(func.sum(UsageEvent.estimated_cost_usd).desc())
            .limit(25)
        )
    ).all()
    by_project = [
        {
            "project_id": str(r[0]) if r[0] else None,
            "project_name": r[1] or "(deleted project)",
            **UsageBucket(
                input_tokens=int(r[2]),
                output_tokens=int(r[3]),
                cache_read_tokens=int(r[4]),
                cache_creation_tokens=int(r[5]),
                estimated_cost_usd=float(r[6]),
                calls=int(r[7]),
            ).as_dict(),
        }
        for r in by_project_rows
    ]

    day_expr = func.date_trunc("day", UsageEvent.created_at)
    recent_rows = (
        await db.execute(
            select(
                day_expr.label("day"),
                *_sum_cols(),
            )
            .where(UsageEvent.created_at >= start_month)
            .group_by(day_expr)
            .order_by(day_expr.asc())
        )
    ).all()
    recent_days = [
        {
            "date": r[0].date().isoformat() if r[0] else "",
            **UsageBucket(
                input_tokens=int(r[1]),
                output_tokens=int(r[2]),
                cache_read_tokens=int(r[3]),
                cache_creation_tokens=int(r[4]),
                estimated_cost_usd=float(r[5]),
                calls=int(r[6]),
            ).as_dict(),
        }
        for r in recent_rows
    ]

    return {
        "currency": "USD",
        "is_estimate": True,
        "pricing_note": PRICING_NOTE,
        "provider": settings.CLAUDE_PROVIDER,
        "totals": totals,
        "by_model": by_model,
        "by_project": by_project,
        "recent_days": recent_days,
        # keep empty shape stable for clients
        "empty": totals["all_time"]["calls"] == 0,
    }
