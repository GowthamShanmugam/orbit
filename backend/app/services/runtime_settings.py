"""In-memory overrides for a whitelisted subset of ``Settings`` (DB-backed)."""

from __future__ import annotations

import contextvars
import logging
import threading
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.project import Project
from app.models.runtime_setting import RuntimeSetting

_log = logging.getLogger(__name__)

_lock = threading.Lock()
_overrides: dict[str, Any] = {}

# Per-chat merge (project overrides on top of global); set only during ``chat_stream``.
_runtime_merged: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "runtime_merged", default=None
)

# Keys exposed in UI / API; must match Settings attributes and Field constraints.
ALLOWED_KEYS: frozenset[str] = frozenset({
    "AI_MAX_TOOL_ROUNDS",
    "AI_CONTEXT_ASSEMBLY_MAX_TOKENS",
    "AI_MAX_CONTINUATIONS",
    "AI_TOOL_SSE_HEARTBEAT_SEC",
    "MCP_TOOL_CALL_TIMEOUT_SEC",
    "MCP_CONNECTION_TIMEOUT_SEC",
    "LOCAL_TOOL_DEFAULT_TIMEOUT_SEC",
    "LOCAL_TOOL_MAX_TIMEOUT_SEC",
})


class RuntimeSettingsUpdate(BaseModel):
    """Partial update: omit a field to leave it unchanged; set to null to clear override."""

    model_config = ConfigDict(extra="forbid")

    AI_MAX_TOOL_ROUNDS: int | None = Field(default=None, ge=1, le=1000)
    AI_CONTEXT_ASSEMBLY_MAX_TOKENS: int | None = Field(default=None, ge=1000, le=2_000_000)
    AI_MAX_CONTINUATIONS: int | None = Field(default=None, ge=0, le=50)
    AI_TOOL_SSE_HEARTBEAT_SEC: float | None = Field(default=None, ge=1.0, le=3600.0)
    MCP_TOOL_CALL_TIMEOUT_SEC: int | None = Field(default=None, ge=5, le=3600)
    MCP_CONNECTION_TIMEOUT_SEC: int | None = Field(default=None, ge=5, le=600)
    LOCAL_TOOL_DEFAULT_TIMEOUT_SEC: int | None = Field(default=None, ge=1, le=86_400)
    LOCAL_TOOL_MAX_TIMEOUT_SEC: int | None = Field(default=None, ge=1, le=86_400)


def _global_effective(name: str) -> Any:
    """Server global: runtime_settings table, else env ``settings`` (no project merge)."""
    with _lock:
        if name in _overrides:
            return _overrides[name]
    return getattr(settings, name)


def eff(name: str) -> Any:
    """Effective value: project merge (if active), else global DB override, else env."""
    merged = _runtime_merged.get()
    if merged is not None and name in merged:
        return merged[name]
    return _global_effective(name)


def eff_int(name: str) -> int:
    return int(eff(name))


def eff_float(name: str) -> float:
    return float(eff(name))


def _set_memory_from_rows(rows: list[RuntimeSetting]) -> None:
    global _overrides
    next_map: dict[str, Any] = {}
    for row in rows:
        if row.key in ALLOWED_KEYS:
            next_map[row.key] = row.value
    with _lock:
        _overrides = next_map


async def load_runtime_overrides(db: AsyncSession) -> None:
    """Load all overrides from DB into memory (startup and after writes)."""
    result = await db.execute(
        select(RuntimeSetting).where(RuntimeSetting.key.in_(ALLOWED_KEYS))
    )
    rows = list(result.scalars().all())
    _set_memory_from_rows(rows)
    with _lock:
        n = len(_overrides)
    _log.info("Runtime settings loaded: %d override(s)", n)


async def apply_project_runtime_updates(
    db: AsyncSession,
    project_id: uuid.UUID,
    body: RuntimeSettingsUpdate,
) -> None:
    """Merge partial updates into ``projects.runtime_overrides``; null clears a key."""
    raw_updates = body.model_dump(exclude_unset=True)
    if not raw_updates:
        return

    proj = await db.get(Project, project_id)
    if proj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")

    current: dict[str, Any] = dict(proj.runtime_overrides or {})
    if not isinstance(current, dict):
        current = {}

    for key, val in raw_updates.items():
        if key not in ALLOWED_KEYS:
            continue
        if val is None:
            current.pop(key, None)
        else:
            current[key] = val

    base = {k: _global_effective(k) for k in ALLOWED_KEYS}
    for k, v in current.items():
        if k in ALLOWED_KEYS and v is not None:
            base[k] = v
    merged = _coerce_merged_types(base)
    _validate_local_tool_pair(
        int(merged["LOCAL_TOOL_DEFAULT_TIMEOUT_SEC"]),
        int(merged["LOCAL_TOOL_MAX_TIMEOUT_SEC"]),
    )

    proj.runtime_overrides = current if current else {}
    await db.commit()


async def apply_runtime_updates(
    db: AsyncSession,
    body: RuntimeSettingsUpdate,
) -> None:
    """Apply partial updates: unset fields ignored; explicit null removes override."""
    raw = body.model_dump(exclude_unset=True)
    if not raw:
        await load_runtime_overrides(db)
        return

    snap: dict[str, int | float] = effective_values_snapshot()
    for key, val in raw.items():
        if val is None:
            snap[key] = getattr(settings, key)  # type: ignore[literal-required]
        else:
            snap[key] = val  # type: ignore[assignment]

    if int(snap["LOCAL_TOOL_DEFAULT_TIMEOUT_SEC"]) > int(snap["LOCAL_TOOL_MAX_TIMEOUT_SEC"]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="LOCAL_TOOL_DEFAULT_TIMEOUT_SEC must be <= LOCAL_TOOL_MAX_TIMEOUT_SEC",
        )

    for key, val in raw.items():
        if val is None:
            await db.execute(delete(RuntimeSetting).where(RuntimeSetting.key == key))
        else:
            row = await db.get(RuntimeSetting, key)
            if row is None:
                db.add(RuntimeSetting(key=key, value=val))
            else:
                row.value = val

    await db.commit()
    await load_runtime_overrides(db)


def effective_values_snapshot() -> dict[str, int | float]:
    """Current **global** effective values (for API GET); ignores project context."""
    return {
        "AI_MAX_TOOL_ROUNDS": int(_global_effective("AI_MAX_TOOL_ROUNDS")),
        "AI_CONTEXT_ASSEMBLY_MAX_TOKENS": int(_global_effective("AI_CONTEXT_ASSEMBLY_MAX_TOKENS")),
        "AI_MAX_CONTINUATIONS": int(_global_effective("AI_MAX_CONTINUATIONS")),
        "AI_TOOL_SSE_HEARTBEAT_SEC": float(_global_effective("AI_TOOL_SSE_HEARTBEAT_SEC")),
        "MCP_TOOL_CALL_TIMEOUT_SEC": int(_global_effective("MCP_TOOL_CALL_TIMEOUT_SEC")),
        "MCP_CONNECTION_TIMEOUT_SEC": int(_global_effective("MCP_CONNECTION_TIMEOUT_SEC")),
        "LOCAL_TOOL_DEFAULT_TIMEOUT_SEC": int(_global_effective("LOCAL_TOOL_DEFAULT_TIMEOUT_SEC")),
        "LOCAL_TOOL_MAX_TIMEOUT_SEC": int(_global_effective("LOCAL_TOOL_MAX_TIMEOUT_SEC")),
    }


def _validate_local_tool_pair(default_s: int, max_s: int) -> None:
    if default_s > max_s:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="LOCAL_TOOL_DEFAULT_TIMEOUT_SEC must be <= LOCAL_TOOL_MAX_TIMEOUT_SEC",
        )


async def merged_runtime_for_project(db: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    """Full effective map for ALLOWED_KEYS: global server values with project JSONB overrides."""
    base = {k: _global_effective(k) for k in ALLOWED_KEYS}
    proj = await db.get(Project, project_id)
    if not proj or not proj.runtime_overrides:
        return _coerce_merged_types(base)
    raw = proj.runtime_overrides
    if not isinstance(raw, dict):
        return _coerce_merged_types(base)
    for k, v in raw.items():
        if k in ALLOWED_KEYS and v is not None:
            base[k] = v
    merged = _coerce_merged_types(base)
    _validate_local_tool_pair(
        int(merged["LOCAL_TOOL_DEFAULT_TIMEOUT_SEC"]),
        int(merged["LOCAL_TOOL_MAX_TIMEOUT_SEC"]),
    )
    return merged


def _coerce_merged_types(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ALLOWED_KEYS:
        v = d[k]
        if k == "AI_TOOL_SSE_HEARTBEAT_SEC":
            out[k] = float(v)
        else:
            out[k] = int(v)
    return out


@asynccontextmanager
async def project_runtime_context(db: AsyncSession, project_id: uuid.UUID):
    """Activate project-layered runtime for ``eff()`` / ``eff_int`` inside this chat turn."""
    merged = await merged_runtime_for_project(db, project_id)
    token = _runtime_merged.set(merged)
    try:
        yield merged
    finally:
        _runtime_merged.reset(token)


def project_layer_snapshot(project: Project) -> tuple[dict[str, int | float], list[str]]:
    """Coerced per-project overrides and sorted key names (whitelisted, non-null)."""
    raw = project.runtime_overrides or {}
    if not isinstance(raw, dict):
        return {}, []
    pairs: list[tuple[str, int | float]] = []
    for k in sorted(raw.keys()):
        if k not in ALLOWED_KEYS:
            continue
        v = raw[k]
        if v is None:
            continue
        coerced: int | float = float(v) if k == "AI_TOOL_SSE_HEARTBEAT_SEC" else int(v)
        pairs.append((k, coerced))
    return dict(pairs), [k for k, _ in pairs]


def env_defaults_snapshot() -> dict[str, int | float]:
    """Env-backed defaults (same keys as ``effective_values_snapshot``)."""
    return {
        "AI_MAX_TOOL_ROUNDS": settings.AI_MAX_TOOL_ROUNDS,
        "AI_CONTEXT_ASSEMBLY_MAX_TOKENS": settings.AI_CONTEXT_ASSEMBLY_MAX_TOKENS,
        "AI_MAX_CONTINUATIONS": settings.AI_MAX_CONTINUATIONS,
        "AI_TOOL_SSE_HEARTBEAT_SEC": float(settings.AI_TOOL_SSE_HEARTBEAT_SEC),
        "MCP_TOOL_CALL_TIMEOUT_SEC": settings.MCP_TOOL_CALL_TIMEOUT_SEC,
        "MCP_CONNECTION_TIMEOUT_SEC": settings.MCP_CONNECTION_TIMEOUT_SEC,
        "LOCAL_TOOL_DEFAULT_TIMEOUT_SEC": settings.LOCAL_TOOL_DEFAULT_TIMEOUT_SEC,
        "LOCAL_TOOL_MAX_TIMEOUT_SEC": settings.LOCAL_TOOL_MAX_TIMEOUT_SEC,
    }


def overridden_key_names() -> list[str]:
    with _lock:
        return sorted(_overrides.keys())
