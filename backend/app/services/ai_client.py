"""Factory for the Anthropic client.

Supports two providers controlled by ``settings.CLAUDE_PROVIDER``:

* **vertex** (default) — Uses Google Vertex AI with Application Default
  Credentials.  Authenticate locally with ``gcloud auth application-default
  login``; in OpenShift use Workload Identity Federation.
* **anthropic** — Uses the Anthropic API directly with ``ANTHROPIC_API_KEY``.

Returns **async** clients so callers can ``await`` API calls without blocking
the event loop (critical for SSE heartbeats during long model calls).
"""

from __future__ import annotations

import functools

from anthropic import AsyncAnthropic, AsyncAnthropicVertex

from app.core.config import settings


@functools.lru_cache(maxsize=1)
def get_ai_client() -> AsyncAnthropic | AsyncAnthropicVertex:
    """Return a cached async Anthropic-compatible client based on config."""
    if settings.CLAUDE_PROVIDER == "vertex":
        if not settings.GCP_PROJECT_ID:
            raise RuntimeError("GCP_PROJECT_ID must be set when CLAUDE_PROVIDER=vertex")
        return AsyncAnthropicVertex(
            project_id=settings.GCP_PROJECT_ID,
            region=settings.GCP_REGION,
        )

    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY must be set when CLAUDE_PROVIDER=anthropic")
    return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
