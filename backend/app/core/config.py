from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"
if _ROOT_ENV.exists():
    load_dotenv(_ROOT_ENV, override=False)


def _parse_origins(raw: str) -> list[str]:
    s = raw.strip()
    if not s:
        return ["http://localhost:5173"]
    if s.startswith("["):
        import json
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in s.split(",") if part.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql+asyncpg://orbit:orbit@localhost:5432/orbit"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = Field(default="change-me-in-production-use-openssl-rand-hex-32")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    CLAUDE_PROVIDER: Literal["vertex", "anthropic"] = "vertex"

    GCP_PROJECT_ID: str = ""
    GCP_REGION: str = "us-east5"

    ANTHROPIC_API_KEY: str | None = None

    CLAUDE_DEFAULT_MODEL: str = "claude-sonnet-4-5-20250929"

    SSO_ISSUER_URL: str = ""
    SSO_CLIENT_ID: str = ""
    SSO_CLIENT_SECRET: str = ""

    #: Relative path only if oauth-proxy (or equivalent) handles it *before* the SPA.
    #: Default empty: nginx serves index.html for unknown paths, so /oauth2/sign_out would load
    #: the React app with no route (blank page). Set e.g. /oauth2/sign_out when a proxy sits in front.
    OCP_OAUTH_SIGNOUT_PATH: str = ""
    #: Optional full URL for IdP logout (e.g. Keycloak end_session_endpoint + post_logout_redirect_uri).
    #: If set, takes precedence over OCP_OAUTH_SIGNOUT_PATH.
    OCP_OAUTH_SIGNOUT_URL: str = ""

    VAULT_MASTER_KEY: str | None = None
    GITHUB_TOKEN: str | None = None
    REPO_CLONE_DIR: str = "data/repos"
    # AI-written reports and exports per session (not git repos).
    SESSION_ARTIFACTS_DIR: str = "data/session_artifacts"

    CORS_ORIGINS: str = "http://localhost:5173"
    ENVIRONMENT: str = "development"
    #: When True (development only), every user sees every project and org checks are skipped.
    DEV_RELAX_PROJECT_ACCESS: bool = False

    # -------------------------------------------------------------------------
    # AI chat / agent (see app.services.ai_service)
    # -------------------------------------------------------------------------
    AI_TOOL_SSE_HEARTBEAT_SEC: float = Field(default=15.0, ge=1.0)
    AI_MAX_TOOL_ROUNDS: int = Field(default=5, ge=1)
    AI_COMPACTION_BETA: str = "compact-2026-01-12"
    AI_COMPACTION_TRIGGER_TOKENS: int = Field(default=150_000, ge=1000)
    #: Comma-separated model IDs that use server-side context compaction.
    AI_COMPACTION_MODEL_IDS: str = "claude-opus-4-6,claude-sonnet-4-6"
    AI_MAX_CACHE_CHARS: int = Field(default=700_000, ge=10_000)
    AI_SUMMARY_TARGET_CHARS: int = Field(default=8_000, ge=500)
    AI_TOOL_RESULT_TRIM_CHARS: int = Field(default=8_000, ge=500)
    AI_MID_LOOP_COMPACT_CHARS: int = Field(default=500_000, ge=10_000)
    AI_MAX_CACHED_SESSIONS: int = Field(default=200, ge=1)
    AI_CONTEXT_ASSEMBLY_MAX_TOKENS: int = Field(default=100_000, ge=1000)
    AI_SUMMARY_CALL_MAX_TOKENS: int = Field(default=2048, ge=256)
    AI_SUMMARY_KEEP_RECENT_MESSAGES: int = Field(default=6, ge=2)
    AI_SUMMARY_STRING_SNIPPET_CHARS: int = Field(default=2000, ge=100)
    AI_SUMMARY_TOOL_TEXT_SNIPPET_CHARS: int = Field(default=500, ge=50)
    AI_SUMMARY_OLDER_BLOB_MAX_CHARS: int = Field(default=30_000, ge=1000)
    AI_COMPACT_KEEP_RECENT_MESSAGES: int = Field(default=4, ge=1)
    AI_MAX_CONTINUATIONS: int = Field(default=3, ge=0)
    AI_SSE_TEXT_CHUNK_SIZE: int = Field(default=40, ge=1)
    AI_MAX_OUTPUT_TOKENS_STANDARD: int = Field(default=16384, ge=256)
    AI_MAX_OUTPUT_TOKENS_HAIKU: int = Field(default=8192, ge=256)

    # -------------------------------------------------------------------------
    # HTTP clients (auth, GitHub, cluster probe, etc.)
    # -------------------------------------------------------------------------
    HTTP_CLIENT_TIMEOUT_SEC: float = Field(default=30.0, ge=1.0)
    CLUSTER_TEST_TIMEOUT_SEC: float = Field(default=10.0, ge=1.0)

    # -------------------------------------------------------------------------
    # MCP (app.services.mcp_client)
    # -------------------------------------------------------------------------
    MCP_TOOL_CALL_TIMEOUT_SEC: int = Field(default=120, ge=5)
    MCP_CONNECTION_TIMEOUT_SEC: int = Field(default=30, ge=5)
    MCP_POOL_TTL_SECONDS: int = Field(default=300, ge=30)
    MCP_LIST_TOOLS_TIMEOUT_SEC: float = Field(default=5.0, ge=1.0)

    # -------------------------------------------------------------------------
    # Local shell / repo / GitHub / artifacts / indexer
    # -------------------------------------------------------------------------
    LOCAL_TOOL_DEFAULT_TIMEOUT_SEC: int = Field(default=300, ge=1)
    LOCAL_TOOL_MAX_TIMEOUT_SEC: int = Field(default=600, ge=1)
    LOCAL_TOOL_MAX_OUTPUT_CHARS: int = Field(default=20_000, ge=1000)
    LOCAL_TOOL_TRUNCATE_HEAD_CHARS: int = Field(default=2000, ge=100)

    REPO_MAX_FILE_READ_CHARS: int = Field(default=100_000, ge=1000)
    REPO_MAX_SEARCH_RESULTS: int = Field(default=40, ge=1)
    REPO_MAX_TREE_ENTRIES: int = Field(default=500, ge=10)

    GITHUB_MAX_FILE_BYTES: int = Field(default=100_000, ge=1000)
    GITHUB_FETCH_CONCURRENCY: int = Field(default=10, ge=1)

    ARTIFACT_MAX_FILE_CHARS: int = Field(default=500_000, ge=1000)
    ARTIFACT_MAX_WRITE_CHARS: int = Field(default=400_000, ge=1000)

    INDEXER_CHUNK_MAX_TOKENS: int = Field(default=512, ge=64)

    # -------------------------------------------------------------------------
    # Kubernetes client & kube tools
    # -------------------------------------------------------------------------
    KUBE_HTTP_CONNECT_TIMEOUT_SEC: float = Field(default=10.0, ge=1.0)
    KUBE_HTTP_READ_TIMEOUT_SEC: float = Field(default=30.0, ge=1.0)
    KUBE_EVENTS_DEFAULT_LIMIT: int = Field(default=100, ge=1)
    KUBE_LOG_STREAM_TIMEOUT_SEC: float = Field(default=60.0, ge=5.0)

    KUBE_TOOL_DEFAULT_LIMIT: int = Field(default=50, ge=1)
    KUBE_LOG_MAX_CHARS: int = Field(default=8000, ge=500)
    KUBE_EVENTS_RECENT_COUNT: int = Field(default=30, ge=1)
    KUBE_EVENT_MESSAGE_PREVIEW_CHARS: int = Field(default=200, ge=20)
    KUBE_STATUS_MESSAGE_PREVIEW_CHARS: int = Field(default=150, ge=20)
    KUBE_JOB_ACTIVE_DEADLINE_SECONDS: int = Field(default=120, ge=1)
    KUBE_JOB_TTL_SECONDS_AFTER_FINISHED: int = Field(default=60, ge=0)
    KUBE_WAIT_POD_TIMEOUT_SEC: float = Field(default=120.0, ge=5.0)
    KUBE_WAIT_POD_POLL_SEC: float = Field(default=2.0, ge=0.1)
    KUBE_DIAG_LOG_TAIL_LINES: int = Field(default=500, ge=10)

    # -------------------------------------------------------------------------
    # Service list defaults (non-API)
    # -------------------------------------------------------------------------
    CONTEXT_ENGINE_DEFAULT_LIMIT: int = Field(default=100, ge=1)
    SECRET_LIST_DEFAULT_LIMIT: int = Field(default=100, ge=1)
    SECRET_AUDIT_DEFAULT_LIMIT: int = Field(default=50, ge=1)
    CONTEXT_HUB_PACK_LIST_DEFAULT: int = Field(default=50, ge=1)
    CLUSTER_TEST_RUN_LIST_LIMIT: int = Field(default=50, ge=1)

    # -------------------------------------------------------------------------
    # API pagination (FastAPI Query defaults)
    # -------------------------------------------------------------------------
    API_PAGE_DEFAULT: int = Field(default=50, ge=1)
    API_PAGE_MAX: int = Field(default=200, ge=1)
    API_PAGE_LARGE_DEFAULT: int = Field(default=100, ge=1)
    API_PAGE_LARGE_MAX: int = Field(default=500, ge=1)

    # -------------------------------------------------------------------------
    # Runtime settings (UI + DB overrides; see app.services.runtime_settings)
    # -------------------------------------------------------------------------
    #: When False, PUT /settings/runtime returns 403 (GET still returns effective values).
    RUNTIME_SETTINGS_ALLOW_WRITE: bool = True

    # -------------------------------------------------------------------------
    # App startup (DB seed retry)
    # -------------------------------------------------------------------------
    STARTUP_SEED_MAX_ATTEMPTS: int = Field(default=15, ge=1)

    # -------------------------------------------------------------------------
    # Workflow agents (max output tokens for sub-agents)
    # -------------------------------------------------------------------------
    WORKFLOW_CODEBASE_MAX_TOKENS: int = Field(default=80_000, ge=1000)
    WORKFLOW_CODEGEN_MAX_TOKENS: int = Field(default=60_000, ge=1000)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins_list(self) -> list[str]:
        return _parse_origins(self.CORS_ORIGINS)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ai_compaction_model_ids_set(self) -> frozenset[str]:
        return frozenset(
            x.strip()
            for x in self.AI_COMPACTION_MODEL_IDS.split(",")
            if x.strip()
        )


settings = Settings()
