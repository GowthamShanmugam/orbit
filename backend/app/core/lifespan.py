"""FastAPI lifespan: startup seeding and shutdown cleanup."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine

_log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Seed built-in data when the DB is ready; release resources on shutdown."""
    max_attempts = settings.STARTUP_SEED_MAX_ATTEMPTS
    for attempt in range(1, max_attempts + 1):
        try:
            async with AsyncSessionLocal() as db:
                from app.services.mcp_client import seed_builtin_skills
                from app.services.workflow_defs import seed_builtin_workflows
                from app.services.runtime_settings import load_runtime_overrides

                await seed_builtin_skills(db)
                await seed_builtin_workflows(db)
                await load_runtime_overrides(db)
            _log.info("Built-in skills and workflows seeded successfully")
            break
        except Exception:
            if attempt < max_attempts:
                _log.warning(
                    "Seed attempt %d/%d failed (DB may not be ready), retrying in %ds...",
                    attempt,
                    max_attempts,
                    attempt * 2,
                )
                await asyncio.sleep(attempt * 2)
            else:
                _log.error(
                    "Could not seed builtin data after %d attempts -- run migrations first",
                    max_attempts,
                )

    yield

    from app.services.mcp_client import evict_all

    await evict_all()
    await engine.dispose()
