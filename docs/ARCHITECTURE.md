# Orbit Architecture

> A complete technical reference for contributors, operators, and anyone evaluating the system.

---

## Table of Contents

1. [High-Level Overview](#1-high-level-overview)
2. [System Architecture](#2-system-architecture)
3. [Backend](#3-backend)
   - [Directory Layout](#31-directory-layout)
   - [Application Startup](#32-application-startup)
   - [API Routes](#33-api-routes)
   - [Database Models](#34-database-models)
   - [Services Layer](#35-services-layer)
4. [AI Pipeline](#4-ai-pipeline)
   - [Client Factory](#41-client-factory)
   - [Chat Stream Flow](#42-chat-stream-flow)
   - [Tool System](#43-tool-system)
   - [Context Assembly](#44-context-assembly)
   - [Conversation Cache & Compaction](#45-conversation-cache--compaction)
5. [MCP Integration](#5-mcp-integration)
6. [Context Pack System](#6-context-pack-system)
7. [Secrets & Vault](#7-secrets--vault)
8. [Cluster Management](#8-cluster-management)
9. [Frontend](#9-frontend)
   - [Directory Layout](#91-directory-layout)
   - [Routing](#92-routing)
   - [State Management](#93-state-management)
   - [API Layer](#94-api-layer)
   - [Streaming Chat](#95-streaming-chat)
10. [Authentication](#10-authentication)
11. [Deployment](#11-deployment)
    - [Local Development (Compose)](#111-local-development-compose)
    - [OpenShift (Manual Scripts)](#112-openshift-manual-scripts)
    - [OpenShift (Operator)](#113-openshift-operator)
12. [Data Flow Diagrams](#12-data-flow-diagrams)

---

## 1. High-Level Overview

Orbit is a self-hosted, AI-assisted workspace that combines project management, context-aware AI chat, secrets management, MCP tool integrations, and Kubernetes cluster operations into a single application.

```mermaid
graph TB
    User([User / Browser])

    subgraph Frontend
        React[React + TypeScript<br/>Vite + Tailwind CSS]
        Nginx[nginx reverse proxy]
    end

    subgraph Backend
        FastAPI[FastAPI + Uvicorn]
        AI[AI Service<br/>Streaming Chat]
        Tools[Tool System<br/>Repo · Kube · MCP · Shell]
    end

    subgraph Data
        PG[(PostgreSQL<br/>+ pgvector)]
        Redis[(Redis)]
    end

    subgraph External
        Claude[Claude API<br/>Vertex AI / Anthropic]
        MCP_Servers[MCP Servers<br/>Jira · GitHub · etc.]
        K8s[OpenShift / K8s<br/>Clusters]
    end

    User --> React
    React --> Nginx
    Nginx -->|/api/*| FastAPI
    FastAPI --> PG
    FastAPI --> Redis
    AI --> Claude
    Tools --> MCP_Servers
    Tools --> K8s
    AI --> Tools
```

**Key design decisions:**

- **SSE over WebSocket** — AI chat uses Server-Sent Events via HTTP POST streaming, keeping the protocol simple and proxy-friendly.
- **In-process background tasks** — Git cloning, indexing, and context assembly run as FastAPI `BackgroundTasks`, not Celery (Celery is defined in Compose but unused in app code today).
- **Pluggable AI provider** — A single env var (`CLAUDE_PROVIDER`) switches between Vertex AI (GCP ADC) and direct Anthropic API key.
- **Encrypted-at-rest secrets** — AES-256-GCM with key derived from `SECRET_KEY`; secrets injected into tool inputs at runtime via `{{secret:name}}` placeholders.

---

## 2. System Architecture

```mermaid
graph LR
    subgraph Browser
        SPA[React SPA]
    end

    subgraph "Container: Frontend"
        NG[nginx:8080]
    end

    subgraph "Container: Backend"
        API[FastAPI:8000]
        AIS[AI Service]
        CTX[Context Engine]
        SEC[Secret Vault]
        MCPc[MCP Client]
        KT[Kube Tools]
        RT[Repo Tools]
        LT[Local Tools]
        SAT[Artifact Tools]
    end

    subgraph "Container: PostgreSQL"
        DB[(orbit DB<br/>pgvector)]
    end

    subgraph "Container: Redis"
        RD[(Cache / Queues)]
    end

    SPA -->|HTTP| NG
    NG -->|proxy /api/| API
    API --> AIS
    AIS --> CTX
    AIS --> SEC
    AIS --> MCPc
    AIS --> KT
    AIS --> RT
    AIS --> LT
    AIS --> SAT
    API --> DB
    API --> RD
    AIS -->|Anthropic SDK| Claude[Claude API]
    MCPc -->|stdio / HTTP| ExtMCP[External MCP Servers]
    KT -->|HTTPS| K8sAPI[K8s API Server]
```

---

## 3. Backend

### 3.1 Directory Layout

```
backend/app/
├── main.py                  # ASGI entry: create_app()
├── application.py           # FastAPI factory, CORS, middleware, routers
├── api/routes/              # All REST endpoints
│   ├── ai.py                # /ai/models, /chat (SSE stream)
│   ├── auth.py              # /auth/login, /auth/token, /auth/me
│   ├── clusters.py          # Cluster CRUD + test-connection
│   ├── context.py           # Context sources + session layers
│   ├── context_hub.py       # Hub pack catalog (/hub/*)
│   ├── files.py             # Repo tree/file browsing
│   ├── projects.py          # Project CRUD + shares + runtime settings
│   ├── secrets.py           # Secret CRUD + scanning
│   ├── sessions.py          # Session CRUD + messages
│   ├── skills.py            # MCP skill CRUD + test/refresh
│   ├── threads.py           # Thread CRUD + thread chat
│   ├── workflows.py         # Workflow templates
│   └── ...
├── core/
│   ├── config.py            # Pydantic Settings (all env vars)
│   ├── database.py          # Async SQLAlchemy engine + session
│   ├── security.py          # JWT + OCP auth helpers
│   ├── secret_vault.py      # AES-256-GCM encrypt/decrypt
│   └── secret_scanner.py    # Detect leaked secrets in user input
├── middleware/
│   └── ocp_auth.py          # OpenShift X-Forwarded-User middleware
├── models/                  # SQLAlchemy ORM models
├── services/                # Business logic layer
└── workflow_engine/         # Multi-agent orchestration (experimental)
```

### 3.2 Application Startup

```mermaid
sequenceDiagram
    participant U as uvicorn
    participant M as main.py
    participant A as application.py
    participant L as lifespan.py
    participant DB as PostgreSQL
    participant MCP as MCP Client

    U->>M: import app
    M->>A: create_app()
    A->>A: Register CORS, middleware, routers
    A->>L: lifespan context manager
    L->>DB: seed_database() — create default org, user, workflows
    L->>MCP: seed_builtin_skills()
    Note over L: App is ready
    L-->>MCP: evict_all() on shutdown
```

### 3.3 API Routes

| Area | Method | Path | Handler |
|------|--------|------|---------|
| **Auth** | POST | `/auth/login` | Login with credentials |
| | POST | `/auth/token` | Issue JWT |
| | GET | `/auth/me` | Current user profile |
| | GET | `/auth/mode` | Auth mode (jwt / ocp) |
| **Projects** | GET/POST | `/projects` | List / create |
| | GET/PUT/DELETE | `/projects/{id}` | Detail / update / delete |
| | GET/PUT | `/projects/{id}/runtime-settings` | Per-project AI config |
| | GET/POST/PATCH/DELETE | `/projects/{id}/shares/*` | Project sharing |
| **Sessions** | GET/POST | `/projects/{pid}/sessions` | List / create |
| | GET/PUT/PATCH/DELETE | `/projects/{pid}/sessions/{sid}` | Detail / update / delete |
| | POST/GET/DELETE | `/projects/{pid}/sessions/{sid}/messages` | Send / list / clear |
| **AI Chat** | GET | `/ai/models` | Available models |
| | POST | `/projects/{pid}/sessions/{sid}/chat` | SSE streaming chat |
| **Threads** | POST/GET | `…/sessions/{sid}/threads` | Create / list |
| | GET/DELETE | `…/threads/{tid}` | Detail / delete |
| | POST | `…/threads/{tid}/chat` | SSE streaming thread chat |
| **Context** | GET/POST/DELETE | `/projects/{pid}/context-sources` | Project context sources |
| | GET/POST/DELETE | `/sessions/{sid}/layers` | Session context layers |
| **Context Hub** | GET/POST | `/hub/packs` | Pack catalog |
| | GET/PUT/DELETE | `/hub/packs/{id}` | Pack detail |
| | GET/POST/DELETE | `/hub/projects/{pid}/installed-packs` | Install/uninstall |
| **Secrets** | GET/POST/PUT/DELETE | `/projects/{pid}/secrets/*` | Vault CRUD |
| | POST | `/scan-secrets` | Scan text for secrets |
| **Skills (MCP)** | GET/POST | `/skills` | List / register |
| | PUT | `/skills/{id}/configure` | Update config |
| | PUT | `/skills/{id}/toggle` | Enable/disable |
| | POST | `/skills/{id}/test` | Test connection |
| | POST | `/skills/{id}/refresh` | Refresh tool list |
| **Clusters** | GET/POST | `/projects/{pid}/clusters` | List / register |
| | GET/PUT/DELETE | `…/clusters/{cid}` | Detail / update / remove |
| | POST | `…/clusters/{cid}/test-connection` | Probe API server |
| **Files** | GET | `/projects/{pid}/repos` | List cloned repos |
| | GET | `…/repos/{rid}/tree` | Directory tree |
| | GET | `…/repos/{rid}/file` | File contents |
| **Artifacts** | GET | `…/sessions/{sid}/artifacts/tree` | Artifact file tree |
| | GET | `…/sessions/{sid}/artifacts/file` | Read artifact |
| | GET | `…/sessions/{sid}/artifacts/download` | Download artifact |
| **Settings** | GET/PUT | `/settings/runtime` | Global runtime settings |

### 3.4 Database Models

```mermaid
erDiagram
    organizations ||--o{ projects : has
    organizations ||--o{ teams : has
    organizations ||--o{ org_prompt_templates : has
    teams ||--o{ team_members : has
    users ||--o{ team_members : belongs_to
    users ||--o{ sessions : creates
    projects ||--o{ sessions : contains
    projects ||--o{ project_shares : shared_via
    projects ||--o{ context_sources : has
    projects ||--o{ project_secrets : stores
    projects ||--o{ project_clusters : connects
    projects ||--o{ installed_packs : installs
    sessions ||--o{ messages : contains
    sessions ||--o{ session_layers : has
    sessions ||--o{ threads : branches
    threads ||--o{ messages : contains
    messages ||--o{ threads : spawns
    context_packs ||--o{ pack_context_sources : includes
    context_packs ||--o{ installed_packs : installed_as
    context_sources ||--o{ indexed_chunks : indexes
    project_secrets ||--o{ secret_audit_logs : audited_by
    project_clusters ||--o{ test_runs : tested_via

    users {
        uuid id PK
        string email
        string full_name
        string sso_subject
        boolean is_active
    }
    projects {
        uuid id PK
        string name
        uuid org_id FK
        uuid created_by_id FK
        jsonb default_ai_config
        jsonb runtime_overrides
    }
    sessions {
        uuid id PK
        string title
        uuid project_id FK
        uuid user_id FK
        string claude_model
        jsonb ai_config
    }
    messages {
        uuid id PK
        uuid session_id FK
        uuid thread_id FK
        string role
        jsonb content
        jsonb metadata
    }
    threads {
        uuid id PK
        uuid session_id FK
        uuid parent_message_id FK
        string title
    }
    context_sources {
        uuid id PK
        uuid project_id FK
        string type
        string name
        string url
    }
    session_layers {
        uuid id PK
        uuid session_id FK
        string type
        text cached_content
        int token_count
    }
    indexed_chunks {
        uuid id PK
        uuid source_id FK
        string file_path
        text content
        vector embedding
    }
    project_secrets {
        uuid id PK
        uuid project_id FK
        string name
        bytes encrypted_value
        bytes nonce
        bytes tag
    }
    project_clusters {
        uuid id PK
        uuid project_id FK
        string name
        string api_server_url
        string auth_method
    }
    mcp_skills {
        uuid id PK
        string name
        string slug
        string transport
        boolean enabled
        jsonb cached_tools
    }
    context_packs {
        uuid id PK
        string name
        string category
        string visibility
    }
```

### 3.5 Services Layer

| Service | File | Responsibility |
|---------|------|----------------|
| **AI Client** | `ai_client.py` | Factory: cached `AnthropicVertex` or `Anthropic` client |
| **AI Service** | `ai_service.py` | Context assembly, streaming chat, tool loop, secret resolution |
| **Context Engine** | `context_engine.py` | CRUD for context sources and session layers |
| **Context Hub** | `context_hub_service.py` | Pack catalog, install/uninstall, background cloning |
| **Secret Service** | `secret_service.py` | Encrypt/decrypt secrets, rotation, audit logging |
| **Cluster Service** | `cluster_service.py` | Cluster CRUD, encrypted credentials, connection testing |
| **MCP Client** | `mcp_client.py` | MCP server connections, tool discovery, execution, pooling |
| **Repo Tools** | `repo_tools.py` | File tree/search/read on cloned repos |
| **Kube Tools** | `kube_tools.py` | Live Kubernetes cluster queries as AI tools |
| **Local Tools** | `local_tools.py` | Shell execution in cloned repos |
| **Artifact Tools** | `session_artifact_tools.py` | Read/write session artifact files |
| **Indexer** | `indexer.py` | Chunk text content into indexed_chunks |
| **GitHub Service** | `github_service.py` | Clone repos, fetch trees via GitHub API |
| **Runtime Settings** | `runtime_settings.py` | Merge env + DB settings, per-project overrides |

---

## 4. AI Pipeline

### 4.1 Client Factory

```mermaid
graph TD
    ENV[".env: CLAUDE_PROVIDER"]
    ENV -->|vertex| VX[AnthropicVertex<br/>GCP_PROJECT_ID + GCP_REGION<br/>Auth: Application Default Credentials]
    ENV -->|anthropic| AN[Anthropic<br/>ANTHROPIC_API_KEY]
    VX --> CLIENT[Cached AI Client]
    AN --> CLIENT
```

- **Vertex AI** authenticates via Google ADC. Locally, `~/.config/gcloud` is mounted read-only into the container. On OpenShift, use Workload Identity or a mounted service account key.
- **Anthropic** uses a direct API key from the environment.

### 4.2 Chat Stream Flow

```mermaid
sequenceDiagram
    participant B as Browser
    participant API as POST /chat
    participant AIS as AI Service
    participant CTX as Context Assembly
    participant CL as Claude API
    participant T as Tool Dispatch

    B->>API: POST { message, model }
    API->>AIS: chat_stream(session, message)

    AIS->>CTX: assemble_context(session)
    CTX-->>AIS: system prompt + session layers

    AIS->>AIS: Load conversation from cache or DB
    AIS->>AIS: Build tool definitions (repo + kube + mcp + local + artifact)

    loop Tool Loop (max rounds)
        AIS->>CL: messages.create(system, messages, tools)
        CL-->>AIS: Response (text + tool_use blocks)
        AIS-->>B: SSE: text_delta events

        alt Has tool_use blocks
            AIS->>AIS: Resolve {{secret:name}} placeholders
            AIS->>T: Execute tool by name prefix
            T-->>AIS: Tool result
            AIS-->>B: SSE: activity event
            Note over AIS: Append tool_result, continue loop
        else No tool_use
            Note over AIS: Break loop
        end
    end

    AIS->>AIS: Save assistant message to DB
    AIS-->>B: SSE: message_complete + done
```

### 4.3 Tool System

Tools are registered dynamically based on what the project has attached:

```mermaid
graph TD
    AIS[AI Service]

    subgraph "Tool Definitions"
        RT[Repo Tools<br/>file_tree, file_read, file_search]
        KT[Kube Tools<br/>list_pods, get_logs, describe, etc.]
        MCPt[MCP Tools<br/>mcp_{slug}__{tool_name}]
        LT[Local Tools<br/>shell_exec in cloned repo]
        SAT[Artifact Tools<br/>read_artifact, write_artifact, list_artifacts]
    end

    AIS -->|has context sources| RT
    AIS -->|has clusters| KT
    AIS -->|has clusters + repos| LT
    AIS -->|has enabled skills| MCPt
    AIS -->|always| SAT

    subgraph "Tool Dispatch"
        AIS -->|name starts with mcp_| MCPt
        AIS -->|name starts with kube_| KT
        AIS -->|name = shell_exec| LT
        AIS -->|name starts with artifact_| SAT
        AIS -->|default| RT
    end
```

### 4.4 Context Assembly

The system prompt is built from multiple layers:

```mermaid
graph TD
    SP[System Prompt]

    H[Header: role, date, project name] --> SP
    WF[Workflow prompt<br/>from session ai_config] --> SP
    SL[Session Layers<br/>pinned context, URLs, text] --> SP
    RA[Repo Addendum<br/>available repo tools] --> SP
    KA[Kube Addendum<br/>available cluster tools] --> SP
    MA[MCP Addendum<br/>available MCP tools] --> SP
    AA[Artifact Addendum<br/>artifact tool instructions] --> SP

    SP --> AI[Claude API Call]
```

Session layers (`session_layers` table) are converted to prompt text by `session_layer_prompt.layer_to_prompt_chunk()`, respecting a configurable token budget (`AI_CONTEXT_ASSEMBLY_MAX_TOKENS`).

### 4.5 Conversation Cache & Compaction

- An LRU cache (`_conversation_cache`) holds the full Anthropic message history per session, including tool use/result blocks that are not persisted to the DB.
- Only the final assistant text message is saved to the `messages` table.
- When the conversation exceeds `AI_COMPACTION_TRIGGER_TOKENS`, a summary is generated and older messages are replaced with the summary to stay within limits.
- Thread conversations use a separate cache key (`UUID5` of thread ID) to avoid colliding with the main session.

---

## 5. MCP Integration

```mermaid
sequenceDiagram
    participant UI as Skills UI
    participant API as /skills API
    participant DB as mcp_skills table
    participant MCPc as MCP Client
    participant Srv as External MCP Server

    UI->>API: POST /skills (register)
    API->>DB: Insert McpSkill (transport, command/URL)
    UI->>API: POST /skills/{id}/test
    API->>MCPc: Connect + list_tools
    MCPc->>Srv: Initialize (stdio spawn or HTTP)
    Srv-->>MCPc: Tool definitions
    MCPc-->>API: Tools list
    API->>DB: Update cached_tools

    Note over MCPc: During AI chat
    MCPc->>MCPc: get_tool_definitions() from DB cache
    MCPc->>Srv: execute_tool(name, args)
    Srv-->>MCPc: Result
```

- **Transport**: `stdio` (spawn a local process) or `http` (SSE-based MCP HTTP transport).
- **Naming**: Tools are prefixed as `mcp_{slug}__{tool_name}` to avoid collisions with built-in tools.
- **Pooling**: HTTP connections are pooled with a configurable TTL; stdio connections are not pooled (process per call).
- **Builtin skills**: Seeded on startup via `seed_builtin_skills()`.

---

## 6. Context Pack System

```mermaid
graph TD
    subgraph "Hub Catalog"
        CP[Context Pack<br/>name, category, visibility]
        PCS[Pack Sources<br/>GitHub URLs, configs]
        CP --> PCS
    end

    subgraph "Per Project"
        IP[Installed Pack<br/>version, overrides]
        CS[Context Source<br/>type, URL, auto_attach]
        IC[Indexed Chunks<br/>file_path, content, embedding]
        CS --> IC
    end

    CP -->|install| IP
    IP -->|creates| CS
    CS -->|background clone + index| IC
    IC -->|used by| RT[Repo Tools in AI chat]
```

- **Hub packs** are shared catalog items (public, org-scoped, or personal).
- **Installing** a pack into a project creates `ContextSource` entries and triggers background git cloning.
- **Indexed chunks** are used by repo tools for file browsing and search during AI chat.
- Embeddings column exists (`vector(1536)` via pgvector) but embedding generation is deferred to a future worker.

---

## 7. Secrets & Vault

```mermaid
graph TD
    User[User creates secret<br/>via UI or API]
    User --> SS[Secret Service]
    SS -->|AES-256-GCM| SV[Secret Vault<br/>key = SHA256 of SECRET_KEY]
    SV --> DB[(project_secrets<br/>encrypted_value + nonce + tag)]

    AI[AI Chat tool input<br/>"use {{secret:MY_KEY}}"]
    AI --> Resolve[resolve_secrets]
    Resolve -->|decrypt| SV
    Resolve -->|inject plaintext| Tool[Tool Execution]
    Tool -->|redacted in response| AI

    SS -->|every access| Audit[(secret_audit_logs)]
```

- Secrets are encrypted at rest using AES-256-GCM with a key derived from `SECRET_KEY` (SHA-256 hash).
- The `{{secret:name}}` placeholder syntax lets the AI reference secrets in tool inputs without seeing the plaintext.
- `secret_scanner.py` scans user messages for accidentally pasted secrets before they reach the AI.

---

## 8. Cluster Management

```mermaid
graph TD
    User[Register cluster<br/>API URL + credentials]
    User --> CS[Cluster Service]
    CS -->|encrypt credentials| SV[Secret Vault]
    CS --> DB[(project_clusters)]

    AI[AI Chat] -->|kube tools| KT[Kube Tools]
    KT -->|decrypt creds| CS
    KT -->|HTTPS| K8s[K8s API Server]
    K8s -->|pods, logs, events, etc.| KT
    KT -->|result| AI

    AI -->|local_tools| LT[Local Tools]
    LT -->|shell with kubeconfig| K8s
```

- Cluster credentials are encrypted with the same vault as secrets.
- `kube_tools.py` provides AI-callable functions for listing pods, reading logs, describing resources, and more.
- `local_tools.py` provides shell execution with an injected kubeconfig for advanced operations.

---

## 9. Frontend

### 9.1 Directory Layout

```
frontend/src/
├── App.tsx              # Routes
├── main.tsx             # Entry: BrowserRouter + QueryClient + AuthGate
├── app.css              # Tailwind + CSS variables design system
├── api/                 # Axios/fetch API modules (one per backend area)
├── stores/              # Zustand stores (UI + session state)
├── pages/               # Route-level components
│   ├── ProjectList.tsx
│   ├── ProjectDetail.tsx
│   ├── SessionView.tsx  # IDE-style: explorer + chat + editor
│   ├── SettingsPage.tsx
│   └── WorkflowsPage.tsx
├── components/
│   ├── Chat/            # ChatPanel, ThreadPanel, ActivityStream
│   ├── Layout/          # MainLayout, Sidebar, TopBar
│   ├── Orbi/            # AI mascot (CSS dog)
│   ├── ContextHub/      # Pack catalog UI
│   ├── ContextManager/  # Context sources + layers
│   ├── Clusters/        # Cluster CRUD UI
│   ├── SecretVault/     # Vault + scanner UI
│   ├── Skills/          # MCP skills UI
│   ├── Editor/          # Monaco editor panel
│   └── ...
├── lib/                 # Utilities (auth, tokens, product tour)
└── types/               # TypeScript interfaces
```

### 9.2 Routing

| Path | Component | Layout |
|------|-----------|--------|
| `/projects` | `ProjectList` | Sidebar visible |
| `/projects/:id` | `ProjectDetail` | Sidebar visible, tabs for sessions/context/clusters/secrets |
| `/projects/:id/sessions/:sid` | `SessionView` | Full-width IDE (sidebar hidden) |
| `/hub` | `HubCatalog` | Sidebar visible |
| `/hub/:packId` | `PackDetail` | Sidebar visible |
| `/skills` | `SkillCatalog` | Sidebar visible |
| `/workflows` | `WorkflowsPage` | Sidebar visible |
| `/settings` | `SettingsPage` | Sidebar visible |

### 9.3 State Management

**Zustand** for UI/session state, **TanStack Query** for server cache.

| Store | Purpose |
|-------|---------|
| `sessionStore` | Active session, messages array, add/set/clear |
| `threadStore` | Active thread, thread messages, streaming state |
| `activityStore` | Streaming text, tool activities, elapsed time |
| `projectStore` | Current project reference |
| `authStore` | User, token, auth mode, login/logout |
| `editorStore` | Monaco editor tabs (open files) |
| `themeStore` | Dark/light theme with localStorage persistence |
| `orbiStore` | Mascot state (idle/thinking/happy/sleeping), preferences |
| `secretStore` | Vault secrets list, scan warnings |
| `contextHubStore` | Hub search query, selected category filter |

### 9.4 API Layer

- **`api/client.ts`** — Shared Axios instance with base URL `/api`, JWT Bearer header from stored token, 401 interceptor for session expiry.
- **Dev proxy** — Vite proxies `/api` → `http://localhost:8000` (strips `/api` prefix).
- **Production** — nginx in the frontend container proxies `/api/` → backend container.

### 9.5 Streaming Chat

```mermaid
sequenceDiagram
    participant CP as ChatPanel
    participant API as api/ai.ts
    participant BE as Backend SSE

    CP->>API: streamChat(projectId, sessionId, input)
    API->>BE: fetch POST /api/.../chat
    BE-->>API: SSE stream (ReadableStream)

    loop Parse SSE lines
        API->>API: Parse "event:" + "data:" lines
        API-->>CP: yield StreamEvent
    end

    CP->>CP: Handle event types
    Note over CP: user_message → add to store
    Note over CP: text_delta → append streaming text
    Note over CP: activity → show tool execution
    Note over CP: message_complete → finalize message
    Note over CP: done → end stream
```

Chat does **not** use WebSocket. It uses `fetch()` with `response.body.getReader()` to read SSE events from an HTTP POST response body.

---

## 10. Authentication

```mermaid
graph TD
    subgraph "Local / JWT Mode"
        Login[POST /auth/login] --> JWT[Issue JWT]
        JWT --> Bearer[Authorization: Bearer token]
        Bearer --> API[API endpoints]
    end

    subgraph "OpenShift / OCP Mode"
        OCP[oauth2-proxy or OCP auth]
        OCP -->|X-Forwarded-User header| MW[OCP Auth Middleware]
        MW -->|auto-provision user| API
    end

    API --> SEC[get_current_user]
    SEC -->|prefers JWT| JWT_V[Verify JWT]
    SEC -->|fallback| FWD[Read X-Forwarded-User]
```

- **Local**: Standard username/password → JWT Bearer token flow.
- **OpenShift**: The `OCPAuthMiddleware` reads `X-Forwarded-User` / `X-Forwarded-Email` headers set by oauth2-proxy or OCP's built-in auth. Users are auto-provisioned in the DB on first access.
- Auth mode is detected by checking for `KUBERNETES_SERVICE_HOST` in the environment.

---

## 11. Deployment

### 11.1 Local Development (Compose)

```mermaid
graph TB
    subgraph "podman/docker compose"
        PG[postgres<br/>pgvector/pgvector:pg16<br/>:5432]
        RD[redis<br/>redis:7-alpine<br/>:6379]
        BE[backend<br/>uvicorn :8000<br/>mounts: ./backend, ~/.config/gcloud]
        FE[frontend<br/>vite dev :5173]
        CW[celery_worker<br/>same backend image<br/>defined but unused]
    end

    FE -->|vite proxy /api| BE
    BE --> PG
    BE --> RD
    CW --> PG
    CW --> RD
```

**Key points:**
- `~/.config/gcloud` is mounted read-only for Vertex AI ADC authentication.
- Override with `GOOGLE_APPLICATION_CREDENTIALS_DIR` env var if gcloud config is elsewhere.
- Backend runs with live code mount (`./backend:/app`) for hot reload.
- Frontend runs Vite dev server (not nginx) in development.

### 11.2 OpenShift (Manual Scripts)

```mermaid
graph TB
    subgraph "deploy/openshift/"
        IS[01-imagestreams.yaml]
        BC[02-buildconfigs.yaml]
        INFRA[03-infra.yaml<br/>Postgres + Redis]
        APP[04-app.yaml<br/>Backend + Frontend]
        OA[05-oauth2-proxy.example.yaml]
    end

    subgraph "OpenShift Cluster"
        PG[Postgres Deployment]
        RD[Redis Deployment]
        BE[Backend Deployment<br/>initContainer: alembic migrate]
        FE[Frontend Deployment<br/>nginx → backend proxy]
        RT[Route: orbit-web]
    end

    BC -->|oc start-build| IS
    IS --> BE
    IS --> FE
    INFRA --> PG
    INFRA --> RD
    APP --> BE
    APP --> FE
    FE --> RT
```

Run `deploy/openshift/build-deploy.sh` which:
1. Applies ImageStreams + BuildConfigs
2. Builds backend/frontend images from source
3. Deploys Postgres + Redis (03-infra.yaml)
4. Deploys backend (with DB migration initContainer) + frontend (04-app.yaml)
5. Creates the Route and sets CORS

### 11.3 OpenShift (Operator)

The [orbit-operator](https://github.com/GowthamShanmugam/orbit-operator) is a separate Kubernetes operator that automates the full deployment from a single custom resource (`OrbitInstance`). It provisions Postgres, Redis, backend, frontend, Celery worker, TLS route, and authentication.

---

## 12. Data Flow Diagrams

### User Sends a Chat Message (End-to-End)

```mermaid
sequenceDiagram
    participant U as User
    participant FE as React Frontend
    participant NG as nginx
    participant API as FastAPI
    participant AIS as AI Service
    participant DB as PostgreSQL
    participant CL as Claude API
    participant MCP as MCP Server
    participant K8s as K8s Cluster

    U->>FE: Type message, click Send
    FE->>FE: scanForSecrets(message)
    FE->>NG: POST /api/.../chat
    NG->>API: Proxy to backend

    API->>DB: Save user message
    API->>AIS: chat_stream(session, message)

    AIS->>DB: Load session layers
    AIS->>AIS: assemble_context() → system prompt
    AIS->>AIS: Load conversation cache

    AIS->>CL: messages.create(system, messages, tools)

    loop Streaming response
        CL-->>AIS: text chunk
        AIS-->>FE: SSE: text_delta
        FE->>FE: Update streaming text in UI
    end

    alt Claude calls a tool
        AIS->>AIS: Resolve {{secret:*}} placeholders
        AIS->>MCP: execute_tool (if MCP tool)
        AIS->>K8s: kube query (if kube tool)
        AIS-->>FE: SSE: activity (tool name + status)
        AIS->>CL: Send tool result, get next response
    end

    AIS->>DB: Save assistant message
    AIS-->>FE: SSE: message_complete
    AIS-->>FE: SSE: done
    FE->>FE: Finalize message in store
    FE->>FE: Orbi → happy state
```

### Context Pack Installation

```mermaid
sequenceDiagram
    participant U as User
    participant API as /hub API
    participant DB as PostgreSQL
    participant BG as BackgroundTask
    participant GH as GitHub

    U->>API: POST /hub/projects/{pid}/installed-packs
    API->>DB: Create InstalledPack
    API->>DB: Create ContextSource entries from pack sources
    API->>BG: Trigger background clone

    BG->>GH: git clone (repo URL)
    BG->>DB: Update ContextSource (last_indexed)
    BG->>DB: Create IndexedChunk rows (chunked files)
```
