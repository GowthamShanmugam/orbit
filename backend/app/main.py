from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import ai, auth, clusters, context, context_hub, files, projects, secrets, sessions, skills, workflows
from app.core.config import settings
from app.middleware.ocp_auth import OCPAuthMiddleware, is_ocp_deployment
from app.core.database import AsyncSessionLocal, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    import logging

    _log = logging.getLogger(__name__)

    for attempt in range(1, 16):
        try:
            async with AsyncSessionLocal() as db:
                from app.services.mcp_client import seed_builtin_skills
                from app.services.workflow_defs import seed_builtin_workflows
                await seed_builtin_skills(db)
                await seed_builtin_workflows(db)
            _log.info("Built-in skills and workflows seeded successfully")
            break
        except Exception:
            if attempt < 15:
                _log.warning("Seed attempt %d/15 failed (DB may not be ready), retrying in %ds...", attempt, attempt * 2)
                await asyncio.sleep(attempt * 2)
            else:
                _log.error("Could not seed builtin data after 15 attempts -- run migrations first")
    yield
    from app.services.mcp_client import evict_all
    await evict_all()
    await engine.dispose()


app = FastAPI(
    title="Orbit API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if is_ocp_deployment():
    app.add_middleware(OCPAuthMiddleware)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(projects.router, prefix="/projects", tags=["projects"])
app.include_router(sessions.router, tags=["sessions"])
app.include_router(context_hub.router, prefix="/hub", tags=["context-hub"])
app.include_router(context.router, tags=["context"])
app.include_router(ai.router, tags=["ai"])
app.include_router(secrets.router, tags=["secrets"])
app.include_router(skills.router, tags=["skills"])
app.include_router(clusters.router, tags=["clusters"])
app.include_router(files.router, tags=["files"])
app.include_router(workflows.router, tags=["workflows"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.close()
