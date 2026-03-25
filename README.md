# Orbit - Context-First AI IDE

Orbit is an integrated development environment built around persistent, structured context. It treats project knowledge, workflows, and artifacts as first-class data so AI assistance stays grounded in your repository, your team’s conventions, and explicit user intent rather than ephemeral chat history.

## Features

- **Context Hub** — Central store for embeddings, documents, and structured context with vector search via pgvector.
- **Workflow Engine** — Defines and runs repeatable tasks and pipelines with clear inputs and outputs.
- **Secret Vault** — Keeps credentials and tokens out of prompts and logs with controlled access patterns.
- **Artifacts** — Versioned outputs from AI and automation (patches, plans, exports) tied to projects and runs.
- **Project DNA** — Captures stack, layout, and conventions so the IDE and models share a consistent project model.
- **AI Transparency** — Surfaces what context was used, which tools ran, and how recommendations were produced.

## Tech stack

| Layer | Technologies |
|--------|----------------|
| API | Python 3.12, FastAPI, Uvicorn |
| Data | PostgreSQL 16, pgvector, SQLAlchemy (async), Alembic |
| Cache & tasks | Redis 7, Celery |
| Frontend | Node 20, React, TypeScript, Vite, Tailwind CSS |
| AI | Claude via Google Vertex AI (default) or direct Anthropic API |
| Auth | SSO-ready (OpenID Connect–style issuer and client settings) |

## Quick start

### Prerequisites — GCP authentication

Orbit uses Claude via Google Vertex AI by default. Authenticate once before starting:

```bash
gcloud auth application-default login
```

This stores credentials in `~/.config/gcloud/`, which the compose file mounts into containers automatically.

### Podman Compose (recommended)

1. Copy the environment template and fill in your GCP project ID:

   ```bash
   cp .env.example .env
   # Edit .env — set GCP_PROJECT_ID to your team's GCP project
   ```

2. Start all services:

   ```bash
   podman compose up --build
   ```

3. Open the app at [http://localhost:5173](http://localhost:5173). The API is served at [http://localhost:8000](http://localhost:8000).

Compose brings up PostgreSQL (with pgvector), Redis, the API (with live reload via a mounted `./backend` volume), the Vite dev server, and a Celery worker. GCP Application Default Credentials are mounted read-only from your host. Data for Postgres is stored in the `postgres_data` volume.

### Manual setup

**Backend**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://orbit:orbit@localhost:5432/orbit
export REDIS_URL=redis://localhost:6379/0
export SECRET_KEY=dev-secret-key-change-in-production
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Celery worker** (from `backend` with the same environment):

```bash
celery -A app.workers worker -l info
```

**Frontend**

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

Run Postgres and Redis locally (or point `DATABASE_URL` / `REDIS_URL` at your own instances) before starting the API and worker.

## Development

| Task | Command |
|------|---------|
| Start full stack | `podman compose up --build` |
| Start in background | `podman compose up -d --build` |
| View logs | `podman compose logs -f backend` |
| Stop stack | `podman compose down` |
| Remove volumes (wipes DB) | `podman compose down -v` |
| Backend tests (when present) | `cd backend && pytest` |
| Frontend typecheck & build | `cd frontend && npm run build` |

Use `.env` for local and Compose-driven runs; never commit real secrets. When running with Podman Compose, `DATABASE_URL` and `REDIS_URL` should use the service hostnames `postgres` and `redis` as in `.env.example`.

## Architecture

High-level data flow and service boundaries:

```mermaid
flowchart LR
  subgraph clients [Clients]
    UI[Web UI]
  end
  subgraph app [Application tier]
    API[FastAPI backend]
    W[Celery workers]
  end
  subgraph data [Data tier]
    PG[(PostgreSQL + pgvector)]
    R[(Redis)]
  end
  UI -->|HTTP / WS| API
  API --> PG
  API --> R
  W --> PG
  W --> R
  API -->|tasks| R
```

The browser talks to the FastAPI app; the app and workers share Redis for queues and caching and use PostgreSQL for durable state and vector search.

## License

MIT
