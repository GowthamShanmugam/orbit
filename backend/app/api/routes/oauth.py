"""OAuth 2.0 web-flow endpoints for integrations that need browser-based auth.

Currently supports Google Drive.  The flow:
 1. User pastes their Google OAuth Client JSON in the UI.
 2. Frontend calls POST /oauth/google-drive/start  -> stores encrypted client
    config, returns the Google authorization URL.
 3. Frontend opens a popup pointing at that URL.
 4. Google redirects to GET /oauth/google-drive/callback?code=...&state=...
 5. Backend exchanges the code for tokens, encrypts and stores them.
 6. Returns a small HTML page that signals the parent window and closes.
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.secret_vault import encrypt_value
from app.core.security import get_current_user
from app.models import User
from app.models.skill import (
    SkillPlugin,
    SkillStatus,
    UserPluginConfig,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth", tags=["oauth"])

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_DRIVE_SCOPES = "https://www.googleapis.com/auth/drive.readonly"

_OAUTH_STATE_TTL = 600  # 10 minutes
_OAUTH_STATE_PREFIX = "oauth_state:"
_redis: aioredis.Redis | None = None
_redis_available: bool | None = None
_pending_states: dict[str, dict[str, Any]] = {}


async def _get_redis() -> aioredis.Redis | None:
    global _redis, _redis_available
    if _redis_available is False:
        return None
    if _redis is None:
        try:
            _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            await _redis.ping()
            _redis_available = True
        except Exception:
            logger.info("Redis unavailable, using in-memory OAuth state store")
            _redis_available = False
            _redis = None
            return None
    return _redis


async def _store_state(state: str, data: dict[str, Any]) -> None:
    r = await _get_redis()
    if r:
        await r.setex(f"{_OAUTH_STATE_PREFIX}{state}", _OAUTH_STATE_TTL, json.dumps(data))
    else:
        _pending_states[state] = data


async def _pop_state(state: str) -> dict[str, Any] | None:
    r = await _get_redis()
    if r:
        key = f"{_OAUTH_STATE_PREFIX}{state}"
        raw = await r.get(key)
        if raw is None:
            return None
        await r.delete(key)
        return json.loads(raw)
    return _pending_states.pop(state, None)


def _gdrive_callback_url() -> str:
    return f"{settings.APP_BASE_URL}/oauth/google-drive/callback"


def _parse_client_json(raw: str) -> dict[str, str]:
    """Extract client_id and client_secret from either 'web' or 'installed' format."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Invalid JSON. Paste the full OAuth Client JSON file.") from exc

    inner = data.get("web") or data.get("installed")
    if not inner:
        raise HTTPException(
            400,
            'JSON must have a "web" or "installed" key. '
            "Download the JSON from Google Cloud Console > Credentials.",
        )

    client_id = inner.get("client_id")
    client_secret = inner.get("client_secret")
    if not client_id or not client_secret:
        raise HTTPException(400, "client_id and client_secret are required in the JSON.")

    return {"client_id": client_id, "client_secret": client_secret}


# ---------------------------------------------------------------------------
# Start OAuth flow
# ---------------------------------------------------------------------------


class StartOAuthRequest(BaseModel):
    client_json: str


class StartOAuthResponse(BaseModel):
    auth_url: str
    callback_url: str


@router.post("/google-drive/start", response_model=StartOAuthResponse)
async def start_google_drive_oauth(
    body: StartOAuthRequest,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Store the encrypted client config and return the Google authorization URL."""
    client_info = _parse_client_json(body.client_json)

    result = await db.execute(select(SkillPlugin).where(SkillPlugin.slug == "google-drive"))
    plugin = result.scalar_one_or_none()
    if not plugin:
        raise HTTPException(404, "Google Drive integration not found")

    cfg_result = await db.execute(
        select(UserPluginConfig).where(
            UserPluginConfig.user_id == current.id,
            UserPluginConfig.plugin_id == plugin.id,
        )
    )
    user_config = cfg_result.scalar_one_or_none()
    if not user_config:
        user_config = UserPluginConfig(user_id=current.id, plugin_id=plugin.id)
        db.add(user_config)

    user_config.config_values = {
        "oauth_client_config": encrypt_value(json.dumps(client_info)),
    }
    user_config.status = SkillStatus.configured
    user_config.status_message = "Waiting for Google authorization..."
    await db.commit()

    state = secrets.token_urlsafe(32)
    await _store_state(state, {
        "user_id": str(current.id),
        "plugin_id": str(plugin.id),
        "client_id": client_info["client_id"],
        "client_secret": client_info["client_secret"],
    })

    callback_url = _gdrive_callback_url()
    params = {
        "client_id": client_info["client_id"],
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": GOOGLE_DRIVE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    auth_url = f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"

    return StartOAuthResponse(auth_url=auth_url, callback_url=callback_url)


# ---------------------------------------------------------------------------
# OAuth callback
# ---------------------------------------------------------------------------

_SUCCESS_HTML = """<!DOCTYPE html>
<html><head><title>Connected</title>
<style>
  body { font-family: system-ui, sans-serif; display: flex;
         align-items: center; justify-content: center; height: 100vh;
         margin: 0; background: #0a0a0a; color: #e0e0e0; }
  .card { text-align: center; padding: 2rem; }
  .check { font-size: 3rem; }
  p { margin-top: 0.5rem; opacity: 0.7; font-size: 0.9rem; }
</style></head>
<body><div class="card">
  <div class="check">&#10003;</div>
  <h2>Google Drive Connected</h2>
  <p>You can close this window.</p>
</div>
<script>
  if (window.opener) { window.opener.postMessage({type:'oauth-complete',provider:'google-drive'}, '*'); }
  setTimeout(() => window.close(), 2000);
</script></body></html>"""

_ERROR_HTML = """<!DOCTYPE html>
<html><head><title>Error</title>
<style>
  body {{ font-family: system-ui, sans-serif; display: flex;
         align-items: center; justify-content: center; height: 100vh;
         margin: 0; background: #0a0a0a; color: #e0e0e0; }}
  .card {{ text-align: center; padding: 2rem; max-width: 400px; }}
  .x {{ font-size: 3rem; color: #ef4444; }}
  p {{ margin-top: 0.5rem; opacity: 0.7; font-size: 0.9rem; word-break: break-word; }}
</style></head>
<body><div class="card">
  <div class="x">&#10007;</div>
  <h2>Authorization Failed</h2>
  <p>{error}</p>
</div>
<script>
  if (window.opener) {{ window.opener.postMessage({{type:'oauth-error',provider:'google-drive',error:'{error_js}'}}, '*'); }}
  setTimeout(() => window.close(), 5000);
</script></body></html>"""


@router.get("/google-drive/callback")
async def google_drive_callback(
    db: Annotated[AsyncSession, Depends(get_db)],
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    """Handle the redirect from Google after user authorizes (or denies)."""
    if error:
        return HTMLResponse(_ERROR_HTML.format(error=error, error_js=error))

    if not code or not state:
        return HTMLResponse(
            _ERROR_HTML.format(
                error="Missing code or state parameter.",
                error_js="Missing code or state parameter.",
            )
        )

    pending = await _pop_state(state)
    if not pending:
        return HTMLResponse(
            _ERROR_HTML.format(
                error="Invalid or expired state. Please try again.",
                error_js="Invalid or expired state.",
            )
        )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": pending["client_id"],
                    "client_secret": pending["client_secret"],
                    "redirect_uri": _gdrive_callback_url(),
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            tokens = resp.json()
    except Exception as exc:
        logger.exception("Google token exchange failed")
        msg = str(exc)[:200]
        return HTMLResponse(_ERROR_HTML.format(error=msg, error_js=msg.replace("'", "\\'")))

    user_id = uuid.UUID(pending["user_id"])
    plugin_id = uuid.UUID(pending["plugin_id"])

    cfg_result = await db.execute(
        select(UserPluginConfig).where(
            UserPluginConfig.user_id == user_id,
            UserPluginConfig.plugin_id == plugin_id,
        )
    )
    user_config = cfg_result.scalar_one_or_none()
    if not user_config:
        return HTMLResponse(
            _ERROR_HTML.format(
                error="Plugin config not found. Please try again.",
                error_js="Plugin config not found.",
            )
        )

    encrypted_tokens = encrypt_value(
        json.dumps(
            {
                "access_token": tokens.get("access_token"),
                "refresh_token": tokens.get("refresh_token"),
                "token_type": tokens.get("token_type", "Bearer"),
                "scope": tokens.get("scope", ""),
                "expiry": tokens.get("expires_in"),
            }
        )
    )

    user_config.config_values = {
        **user_config.config_values,
        "oauth_credentials": encrypted_tokens,
        "oauth_connected": "true",
    }
    user_config.enabled = True
    user_config.status = SkillStatus.connected
    user_config.status_message = "Google Drive authorized successfully"
    await db.commit()

    return HTMLResponse(_SUCCESS_HTML)
