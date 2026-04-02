"""Middleware that reads user identity from oauth-proxy forwarded headers.

When deployed on OpenShift with an oauth-proxy sidecar, the proxy injects
X-Forwarded-User, X-Forwarded-Email, and X-Forwarded-Access-Token headers
into every authenticated request.  This middleware reads those headers and
populates ``request.state.ocp_user`` so downstream code can identify the
caller without needing its own OIDC/OAuth library.

When the headers are absent (e.g. local development), the middleware is a
no-op.
"""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class OCPAuthMiddleware(BaseHTTPMiddleware):
    """Extracts user identity from oauth-proxy X-Forwarded-* headers."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        user = request.headers.get("X-Forwarded-User")
        email = request.headers.get("X-Forwarded-Email")
        access_token = request.headers.get("X-Forwarded-Access-Token")

        if user:
            request.state.ocp_user = {
                "username": user,
                "email": email or "",
                "access_token": access_token or "",
            }
        else:
            request.state.ocp_user = None

        return await call_next(request)


def is_ocp_deployment() -> bool:
    """Return True if we appear to be running inside an OpenShift pod."""
    return bool(os.environ.get("KUBERNETES_SERVICE_HOST"))
