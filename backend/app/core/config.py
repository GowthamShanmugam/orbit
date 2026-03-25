from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql+asyncpg://orbit:orbit@localhost:5432/orbit"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = Field(default="change-me-in-production-use-openssl-rand-hex-32")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    # AI provider: "vertex" (GCP/ADC auth) or "anthropic" (direct API key)
    CLAUDE_PROVIDER: Literal["vertex", "anthropic"] = "vertex"

    # Vertex AI settings (used when CLAUDE_PROVIDER=vertex)
    GCP_PROJECT_ID: str = ""
    GCP_REGION: str = "us-east5"

    # Direct Anthropic API key (used when CLAUDE_PROVIDER=anthropic)
    ANTHROPIC_API_KEY: str | None = None

    CLAUDE_DEFAULT_MODEL: str = "claude-sonnet-4-20250514"

    SSO_ISSUER_URL: str = ""
    SSO_CLIENT_ID: str = ""
    SSO_CLIENT_SECRET: str = ""

    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    ENVIRONMENT: str = "development"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        if v is None:
            return ["http://localhost:5173"]
        if isinstance(v, str):
            s = v.strip()
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
        if isinstance(v, list):
            return [str(x) for x in v]
        return ["http://localhost:5173"]


settings = Settings()
