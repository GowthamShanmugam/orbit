from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.ocp_auth import is_ocp_deployment
from app.core.security import (
    _get_or_create_ocp_user,
    create_access_token,
    get_current_user,
)
from app.models.user import User

router = APIRouter()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    code: str = Field(min_length=1)
    redirect_uri: str = Field(min_length=1)


class DevTokenRequest(BaseModel):
    email: str = Field(min_length=3, max_length=512)
    full_name: str | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str | None
    avatar_url: str | None
    sso_subject: str
    is_active: bool


def _require_sso_config() -> str:
    issuer = (settings.SSO_ISSUER_URL or "").strip().rstrip("/")
    if not issuer:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SSO is not configured",
        )
    if not settings.SSO_CLIENT_ID or not settings.SSO_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SSO client is not configured",
        )
    return issuer


@router.post("/login", response_model=TokenResponse)
async def oauth_login(body: LoginRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> TokenResponse:
    issuer = _require_sso_config()
    token_url = f"{issuer}/protocol/openid-connect/token"
    form = {
        "grant_type": "authorization_code",
        "client_id": settings.SSO_CLIENT_ID,
        "client_secret": settings.SSO_CLIENT_SECRET,
        "code": body.code,
        "redirect_uri": body.redirect_uri,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.HTTP_CLIENT_TIMEOUT_SEC) as client:
            tr = await client.post(token_url, data=form)
            tr.raise_for_status()
            tokens = tr.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization code exchange failed",
        ) from e
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach identity provider",
        ) from e

    access = tokens.get("access_token")
    if not access or not isinstance(access, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token response from identity provider",
        )

    userinfo_url = f"{issuer}/protocol/openid-connect/userinfo"
    try:
        async with httpx.AsyncClient(timeout=settings.HTTP_CLIENT_TIMEOUT_SEC) as client:
            ur = await client.get(
                userinfo_url,
                headers={"Authorization": f"Bearer {access}"},
            )
            ur.raise_for_status()
            claims = ur.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not fetch user profile",
        ) from e

    sub = claims.get("sub")
    if not sub or not isinstance(sub, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User profile missing subject",
        )
    email = claims.get("email")
    if not email or not isinstance(email, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User profile missing email",
        )
    full_name = claims.get("name") if isinstance(claims.get("name"), str) else None
    avatar = claims.get("picture") if isinstance(claims.get("picture"), str) else None

    result = await db.execute(select(User).where(User.sso_subject == sub))
    user = result.scalar_one_or_none()
    if user is None:
        existing_email = await db.execute(select(User).where(User.email == email))
        if existing_email.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered with another identity",
            )
        user = User(
            email=email,
            full_name=full_name,
            avatar_url=avatar,
            sso_subject=sub,
            is_active=True,
        )
        db.add(user)
    else:
        user.email = email
        user.full_name = full_name
        user.avatar_url = avatar
        user.is_active = True

    await db.commit()
    await db.refresh(user)

    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def read_me(current: Annotated[User, Depends(get_current_user)]) -> User:
    return current


class AuthModeResponse(BaseModel):
    mode: str  # "ocp", "sso", or "dev"
    #: Relative path for oauth-proxy sign-out (only if something handles it before the SPA).
    ocp_signout_path: str | None = None
    #: Full IdP logout URL when not using oauth-proxy path (e.g. Keycloak logout).
    ocp_signout_url: str | None = None


def _ocp_logout_fields() -> tuple[str | None, str | None]:
    """Returns (ocp_signout_path, ocp_signout_url). Full URL wins over path."""
    url = (settings.OCP_OAUTH_SIGNOUT_URL or "").strip()
    path = (settings.OCP_OAUTH_SIGNOUT_PATH or "").strip()
    if url:
        return None, url
    return (path if path else None), None


@router.get("/mode", response_model=AuthModeResponse)
async def auth_mode(request: Request) -> AuthModeResponse:
    """Tell the frontend which auth mode is active.

    - "ocp": OpenShift / oauth-proxy style (X-Forwarded-User or running in-cluster)
    - "sso": SSO is configured (OIDC login flow available)
    - "dev": development mode (email-based dev login)

    Logout: there is a single IdP login (e.g. Red Hat SSO). oauth-proxy only gates the app and
    forwards identity; it is not a second login. Full SSO logout needs either a proxy-handled
    path, a configured IdP logout URL, or cluster documentation for manual sign-out.
    """
    sp, su = _ocp_logout_fields()

    if request.headers.get("X-Forwarded-User"):
        return AuthModeResponse(mode="ocp", ocp_signout_path=sp, ocp_signout_url=su)
    if is_ocp_deployment():
        return AuthModeResponse(mode="ocp", ocp_signout_path=sp, ocp_signout_url=su)
    if settings.SSO_ISSUER_URL and settings.SSO_CLIENT_ID:
        return AuthModeResponse(mode="sso")
    return AuthModeResponse(mode="dev")


class WhoamiResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    access_token: str
    token_type: str = "bearer"
    user: UserResponse


@router.get("/whoami", response_model=WhoamiResponse)
async def whoami(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WhoamiResponse:
    """Auto-login endpoint for OCP oauth-proxy deployments.

    When oauth-proxy injects X-Forwarded-User headers, this endpoint
    finds or creates the user and returns a JWT so the frontend can
    make subsequent API calls with a Bearer token.
    """
    ocp_user = request.headers.get("X-Forwarded-User")
    if not ocp_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authenticated user (X-Forwarded-User header missing)",
        )

    ocp_email = request.headers.get("X-Forwarded-Email", "")
    user = await _get_or_create_ocp_user(db, ocp_user, ocp_email)
    token = create_access_token({"sub": str(user.id)})

    return WhoamiResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.post("/token", response_model=TokenResponse)
async def dev_issue_token(
    body: DevTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    if settings.ENVIRONMENT != "development":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    dev_sub = f"dev:{body.email.lower()}"
    result = await db.execute(select(User).where(User.sso_subject == dev_sub))
    user = result.scalar_one_or_none()
    if user is None:
        result = await db.execute(select(User).where(User.email == str(body.email)))
        user = result.scalar_one_or_none()
    if user is None:
        user = User(
            email=str(body.email),
            full_name=body.full_name,
            avatar_url=None,
            sso_subject=dev_sub,
            is_active=True,
        )
        db.add(user)
    elif body.full_name is not None:
        user.full_name = body.full_name

    await db.commit()
    await db.refresh(user)

    return TokenResponse(access_token=create_access_token({"sub": str(user.id)}))
