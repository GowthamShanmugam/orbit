# Orbit

![Orbit UI demo: explorer, workspace, and AI chat](docs/assets/orbit-demo.gif)

Orbit is an AI-assisted workspace: projects, sessions, context packs, secrets, clusters, and streaming chat backed by **PostgreSQL** (with pgvector), **Redis**, and a **FastAPI** backend.

---

## Installation

Choose the path that fits your use case:

| Path | Best for | Time |
|------|----------|------|
| [**A. Local development**](#a-local-development) | Contributors and day-to-day hacking | ~5 min |
| [**B. OpenShift cluster**](#b-openshift-cluster) | Production / team deployments on OCP | ~10 min |

---

### A. Local development

Run the backend and frontend on your machine with Postgres and Redis in containers.

#### Prerequisites

- Python 3.12+
- Node 20+
- Podman or Docker

#### 1. Clone and enter the repo

```bash
git clone https://github.com/GowthamShanmugam/orbit.git
cd orbit
```

#### 2. Start Postgres and Redis

```bash
podman compose up -d postgres redis
# or: docker compose up -d postgres redis
```

This exposes Postgres on `localhost:5432` and Redis on `localhost:6379`.

#### 3. Configure environment

```bash
cp .env.example .env
```

Open `.env` and set your AI provider. Pick **one** of the two options below:

**Vertex AI (default)**

```env
CLAUDE_PROVIDER=vertex
GCP_PROJECT_ID=my-gcp-project
GCP_REGION=us-east5
```

Then authenticate on your machine:

```bash
gcloud auth application-default login
```

**Anthropic API (direct key)**

```env
CLAUDE_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

> Leave `DATABASE_URL` and `REDIS_URL` at their defaults (`127.0.0.1`) for local development. The `postgres`/`redis` hostnames only work inside the Compose network.

#### 4. Start the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --reload-dir app --reload-dir alembic --host 0.0.0.0 --port 8000
```

#### 5. Start the frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

#### 6. Open the app

- UI: **http://localhost:5173** (Vite proxies API calls to the backend)
- API: **http://localhost:8000** -- health check: `GET /health`

---

### B. OpenShift cluster

Deploy the full Orbit stack on OpenShift using the [orbit-operator](https://github.com/GowthamShanmugam/orbit-operator). The operator provisions Postgres, Redis, backend, Celery worker, frontend, TLS route, and authentication from a single custom resource.

#### Prerequisites

- OpenShift 4.12+
- `oc` CLI logged in as cluster-admin

#### 1. Install the operator

```bash
oc new-project orbit-operator
oc apply -f https://raw.githubusercontent.com/GowthamShanmugam/orbit-operator/main/config/crd/orbit.redhat.com_orbitinstances.yaml
oc apply -f https://raw.githubusercontent.com/GowthamShanmugam/orbit-operator/main/config/rbac/
oc apply -f https://raw.githubusercontent.com/GowthamShanmugam/orbit-operator/main/config/manager/manager.yaml
```

#### 2. Create the Orbit instance

```bash
oc new-project orbit
```

If using Vertex AI, create the GCP service account secret first:

```bash
oc create secret generic orbit-gcp-sa \
  --from-file=sa-key.json=/path/to/service-account-key.json \
  -n orbit
```

Then apply the custom resource (edit the sample to match your environment):

```bash
curl -O https://raw.githubusercontent.com/GowthamShanmugam/orbit-operator/main/config/samples/orbit_v1alpha1_orbitinstance.yaml
# Edit the file: set your GCP project, region, image refs, etc.
oc apply -f orbit_v1alpha1_orbitinstance.yaml
```

#### 3. Access Orbit

```bash
oc get orbitinstance orbit -n orbit -w
```

Once the status shows `Ready`, open the route URL printed in the status output.

> For authentication options (OpenShift OAuth, Red Hat SSO), scaling, and advanced configuration, see the full [orbit-operator README](https://github.com/GowthamShanmugam/orbit-operator#readme).

---

## Database migrations

After pulling changes that include new migrations:

```bash
cd backend && source .venv/bin/activate
alembic upgrade head
```

**OpenShift:** run Alembic in the backend pod or use `deploy/openshift/alembic-upgrade.sh`.

---

## Useful commands

| Task | Command |
|------|---------|
| Stop DB/Redis only | `podman compose down` |
| Stop full stack | `podman compose down` |
| Wipe DB volume | `podman compose down -v` |
| Backend tests | `cd backend && pytest` |
| Frontend build | `cd frontend && npm run build` |

---

## Session context layers

In the workspace, **Context > Add layer** pins items to the **current session**. The assistant receives them under **Session Context** on every message: optional **Notes** are included verbatim; if you only set a label and URL, those (and the layer type) are still included so the model knows what you attached -- use MCP (e.g. Jira) or repo tools when you need the full issue or PR body.

---

## Project layout (backend)

| Path | Role |
|------|------|
| `app/main.py` | ASGI entry (`app` instance for Uvicorn) |
| `app/application.py` | `create_app()` -- middleware and route registration |
| `app/core/lifespan.py` | Startup seeding and shutdown cleanup |
| `app/api/routes/` | HTTP route modules |
| `app/services/` | Business logic |
| `alembic/` | Schema migrations |

---

## Development notes

- **Project access:** With `ENVIRONMENT=development`, org membership and project shares are enforced. Do **not** set `DEV_RELAX_PROJECT_ACCESS=true` unless you intentionally want every user to see every project.
- **Secrets:** Never commit `.env`; use `.env.example` as a template only.
