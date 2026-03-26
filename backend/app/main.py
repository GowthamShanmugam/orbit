from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import ai, auth, clusters, context, context_hub, files, projects, secrets, sessions
from app.core.config import settings
from app.core.database import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
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

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(projects.router, prefix="/projects", tags=["projects"])
app.include_router(sessions.router, tags=["sessions"])
app.include_router(context_hub.router, prefix="/hub", tags=["context-hub"])
app.include_router(context.router, tags=["context"])
app.include_router(ai.router, tags=["ai"])
app.include_router(secrets.router, tags=["secrets"])
app.include_router(clusters.router, tags=["clusters"])
app.include_router(files.router, tags=["files"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.close()
