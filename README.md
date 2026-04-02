# Orbit

![Orbit UI demo: explorer, workspace, and AI chat](docs/assets/orbit-demo.gif)

## Local development (backend + frontend on your machine)

### 1. Start Postgres and Redis (containers)

From the repo root:

```bash
podman compose up -d postgres redis
# or: docker compose up -d postgres redis
```

This publishes **Postgres on `localhost:5432`** and **Redis on `localhost:6379`**.

If you see **“container name orbit-postgres is already in use”**, remove the old container or reuse it:

```bash
podman rm -f orbit-postgres   # only if you created that container manually before
podman ps -a                  # list containers (not `podman list`)
```

### 2. Configure `.env` for the host (not Docker DNS)

Copy `.env.example` to `.env` at the repo root.

When you run **Alembic** and **uvicorn on your Mac**, the DB host must be **`127.0.0.1`** or **`localhost`**, not `postgres`:

```env
DATABASE_URL=postgresql+asyncpg://orbit:orbit@127.0.0.1:5432/orbit
REDIS_URL=redis://127.0.0.1:6379/0
```

Use `postgres` / `redis` as hostnames **only** when the app runs **inside** the same Compose stack as those services.

**Project visibility:** With `ENVIRONMENT=development`, the API still enforces **organization membership** and **project shares** by default. Do **not** set `DEV_RELAX_PROJECT_ACCESS=true` unless you intentionally want every user to see every project (legacy debugging).

### 3. Migrations and API

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
uvicorn app.main:app --reload --reload-dir app --reload-dir alembic --host 0.0.0.0 --port 8000
```

`--reload-dir` limits the file watcher to application code and migrations. Without it, changes under `data/repos/` (mirrored Git clones) also match `*.py` and force constant reloads.

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** (Vite proxies `/api` to **http://localhost:8000**).

### AI (Claude)

- **Vertex** (default): set `GCP_PROJECT_ID`, run `gcloud auth application-default login`.
- Or set `CLAUDE_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` in `.env`.

## Full stack in containers

Use the same `compose.yml` with `.env` where `DATABASE_URL` uses `@postgres:5432` and `REDIS_URL` uses `redis:6379` when variables are passed into the **backend** container (as in the compose file). Run:

```bash
podman compose up -d
# or: docker compose up -d
```
