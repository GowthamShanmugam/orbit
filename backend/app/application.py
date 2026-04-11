"""
Application factory: middleware, routers, and health endpoints.

Production entrypoint is ``app.main:app`` (thin wrapper around ``create_app()``).
"""

from __future__ import annotations

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    ai,
    auth,
    clusters,
    context,
    context_hub,
    files,
    org_prompt_templates,
    organizations,
    projects,
    runtime_settings,
    secrets,
    session_artifacts,
    sessions,
    skills,
    threads,
    workflows,
)
from app.core.config import settings
from app.core.lifespan import lifespan
from app.middleware.ocp_auth import OCPAuthMiddleware, is_ocp_deployment


def create_app() -> FastAPI:
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

    _register_routes(app)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.close()

    return app


def _register_routes(app: FastAPI) -> None:
    """Mount all API routers. Order matters only if paths overlap."""
    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(organizations.router, tags=["organizations"])
    app.include_router(org_prompt_templates.router, tags=["org-prompt-templates"])
    app.include_router(projects.router, prefix="/projects", tags=["projects"])
    app.include_router(sessions.router, tags=["sessions"])
    app.include_router(context_hub.router, prefix="/hub", tags=["context-hub"])
    app.include_router(context.router, tags=["context"])
    app.include_router(ai.router, tags=["ai"])
    app.include_router(secrets.router, tags=["secrets"])
    app.include_router(skills.router, tags=["skills"])
    app.include_router(clusters.router, tags=["clusters"])
    app.include_router(files.router, tags=["files"])
    app.include_router(session_artifacts.router, tags=["session-artifacts"])
    app.include_router(threads.router, tags=["threads"])
    app.include_router(workflows.router, tags=["workflows"])
    app.include_router(runtime_settings.router)
