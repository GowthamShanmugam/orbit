from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, get_current_user
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
        async with httpx.AsyncClient(timeout=30.0) as client:
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
        async with httpx.AsyncClient(timeout=30.0) as client:
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
