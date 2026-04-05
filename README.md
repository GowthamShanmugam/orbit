# Orbit

![Orbit UI demo: explorer, workspace, and AI chat](docs/assets/orbit-demo.gif)

Orbit is an AI-assisted workspace: projects, sessions, context packs, secrets, clusters, and streaming chat backed by **PostgreSQL** (with pgvector), **Redis**, and a **FastAPI** backend.

---

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| **Python 3.12+** | Backend API and Alembic |
| **Node 20+** | Frontend (Vite + React) |
| **Podman** or **Docker** | Postgres + Redis (recommended) |
| **GCP** (optional) | Default AI path uses Vertex AI — `gcloud auth application-default login` |

---

## Installation (choose one path)

### A. Local API + UI (Postgres/Redis in containers)

Best for day-to-day development: DB in Compose, app and Vite on your machine.

1. **Start only Postgres and Redis**

   ```bash
   podman compose up -d postgres redis
   # or: docker compose up -d postgres redis
   ```

   This exposes **5432** (Postgres) and **6379** (Redis) on `localhost`.

2. **Environment**

   ```bash
   cp .env.example .env
   ```

   For apps running **on your host** (not inside Compose), `DATABASE_URL` / `REDIS_URL` must use **`127.0.0.1`** — not `postgres` / `redis` (those names only resolve inside the Compose network).

   ```env
   DATABASE_URL=postgresql+asyncpg://orbit:orbit@127.0.0.1:5432/orbit
   REDIS_URL=redis://127.0.0.1:6379/0
   ```

3. **Backend: venv, migrations, server**

   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   alembic upgrade head
   uvicorn app.main:app --reload --reload-dir app --reload-dir alembic --host 0.0.0.0 --port 8000
   ```

   `--reload-dir` limits reloads to app code and migrations (avoids reloads when mirrored repos change under `data/repos/`).

4. **Frontend**

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

5. **Open the app**

   - UI: **http://localhost:5173** (Vite proxies API calls to the backend).
   - API: **http://localhost:8000** — health: `GET /health`.

### B. Full stack in containers

Run backend + frontend + DB + Redis + worker from the repo root:

```bash
cp .env.example .env
# For Compose, you can use service hostnames — compose.yml sets DATABASE_URL/REDIS_URL for the backend container.
podman compose up -d --build
# or: docker compose up -d --build
```

Adjust `.env` for AI keys (see below). Frontend is typically on **http://localhost:5173**, API on **http://localhost:8000**.

---

## AI configuration

| Mode | What to set |
|------|-------------|
| **Vertex AI** (default) | `GCP_PROJECT_ID`, `GCP_REGION`; run `gcloud auth application-default login` on the host (Compose mounts ADC for the backend container). |
| **Anthropic API** | `CLAUDE_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` in `.env`. |

---

## Database migrations

After pulling changes that include new migrations:

```bash
cd backend && source .venv/bin/activate
alembic upgrade head
```

If the API returns errors about missing columns (e.g. after a deploy), the DB schema is behind the app — run migrations before debugging API code.

**OpenShift / remote:** run Alembic in the backend pod or use your platform’s migration job; see `deploy/openshift/alembic-upgrade.sh` if you use that layout.

---

## Useful commands

| Task | Command |
|------|---------|
| Stop DB/Redis only | `podman compose down` (without `frontend`/`backend` if you only started `postgres` `redis`) |
| Stop full stack | `podman compose down` |
| Wipe DB volume | `podman compose down -v` |
| Backend tests | `cd backend && pytest` |
| Frontend build | `cd frontend && npm run build` |

---

<<<<<<< Updated upstream
## Project layout (backend)
=======
### Session context layers

In the workspace, **Context → Add layer** pins items to the **current session**. The assistant receives them under **Session Context** on every message: optional **Notes** are included verbatim; if you only set a label and URL, those (and the layer type) are still included so the model knows what you attached—use MCP (e.g. Jira) or repo tools when you need the full issue or PR body.

## Full stack in containers
>>>>>>> Stashed changes

| Path | Role |
|------|------|
| `app/main.py` | ASGI entry (`app` instance for Uvicorn) |
| `app/application.py` | `create_app()` — middleware and route registration |
| `app/core/lifespan.py` | Startup seeding and shutdown cleanup |
| `app/api/routes/` | HTTP route modules |
| `app/services/` | Business logic |
| `alembic/` | Schema migrations |

---

## Development notes

- **Project access:** With `ENVIRONMENT=development`, org membership and project shares are enforced. Do **not** set `DEV_RELAX_PROJECT_ACCESS=true` unless you intentionally want every user to see every project.
- **Secrets:** Never commit `.env`; use `.env.example` as a template only.
