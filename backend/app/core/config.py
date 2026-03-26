from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import Field, computed_field, field_validator
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

    VAULT_MASTER_KEY: str | None = None
    GITHUB_TOKEN: str | None = None
    REPO_CLONE_DIR: str = "data/repos"

    CORS_ORIGINS: str = "http://localhost:5173"
    ENVIRONMENT: str = "development"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins_list(self) -> list[str]:
        return _parse_origins(self.CORS_ORIGINS)


settings = Settings()
