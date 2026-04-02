from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


def _decode_token_if_valid(token: str) -> dict | None:
    """Return claims if JWT is valid and unexpired; otherwise None (no exception)."""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None


async def _get_or_create_ocp_user(
    db: AsyncSession,
    username: str,
    email: str,
) -> User:
    """Find or create a User from oauth-proxy forwarded headers."""
    sso_subject = f"ocp:{username}"

    result = await db.execute(select(User).where(User.sso_subject == sso_subject))
    user = result.scalar_one_or_none()

    if user is None:
        if email:
            existing = await db.execute(select(User).where(User.email == email))
            user = existing.scalar_one_or_none()
            if user:
                user.sso_subject = sso_subject
                await db.commit()
                await db.refresh(user)
                return user

        user = User(
            email=email or f"{username}@ocp.local",
            full_name=username,
            sso_subject=sso_subject,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Authenticate via JWT token OR oauth-proxy X-Forwarded-* headers.

    If a Bearer token is present and **valid**, it wins. Expired or malformed JWTs
    do **not** block OpenShift: oauth-proxy headers are used so sessions stay valid
    while the browser still has an old JWT in localStorage.
    """
    if token:
        payload = _decode_token_if_valid(token)
        if payload is not None:
            sub = payload.get("sub")
            if sub is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Could not validate credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            try:
                user_id = UUID(sub)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Could not validate credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                ) from e
            result = await db.execute(
                select(User).where(User.id == user_id, User.is_active.is_(True))
            )
            user = result.scalar_one_or_none()
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found or inactive",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return user

    ocp_user = request.headers.get("X-Forwarded-User")
    if ocp_user:
        ocp_email = request.headers.get("X-Forwarded-Email", "")
        return await _get_or_create_ocp_user(db, ocp_user, ocp_email)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
