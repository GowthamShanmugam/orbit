"""Secret Vault service — CRUD, audit logging, and bulk operations."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.secret_vault import encrypt
from app.models.secret import (
    ProjectSecret,
    SecretAuditLog,
    SecretScope,
    VaultBackend,
)


async def list_secrets(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int | None = None,
) -> list[ProjectSecret]:
    if limit is None:
        limit = settings.SECRET_LIST_DEFAULT_LIMIT
    result = await db.execute(
        select(ProjectSecret)
        .where(ProjectSecret.created_by == user_id)
        .order_by(ProjectSecret.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_secret(db: AsyncSession, secret_id: uuid.UUID) -> ProjectSecret | None:
    result = await db.execute(select(ProjectSecret).where(ProjectSecret.id == secret_id))
    return result.scalar_one_or_none()


async def create_secret(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    name: str,
    value: str,
    scope: SecretScope = SecretScope.personal,
    description: str | None = None,
) -> ProjectSecret:
    ciphertext, nonce, tag = encrypt(value)
    placeholder_key = re.sub(r"[^A-Za-z0-9_.\-]", "_", name)

    secret = ProjectSecret(
        name=name,
        scope=scope,
        encrypted_value=ciphertext,
        nonce=nonce,
        tag=tag,
        placeholder_key=placeholder_key,
        vault_backend=VaultBackend.builtin,
        description=description,
        created_by=user_id,
    )
    db.add(secret)
    await db.flush()

    await _audit(db, secret.id, user_id, "created", f"Secret '{name}' created")
    await db.commit()
    await db.refresh(secret)
    return secret


async def update_secret_value(
    db: AsyncSession,
    secret: ProjectSecret,
    new_value: str,
    *,
    user_id: uuid.UUID | None = None,
) -> ProjectSecret:
    ciphertext, nonce, tag = encrypt(new_value)
    secret.encrypted_value = ciphertext
    secret.nonce = nonce
    secret.tag = tag
    secret.last_rotated = datetime.now(UTC)
    await _audit(db, secret.id, user_id, "rotated", f"Secret '{secret.name}' value rotated")
    await db.commit()
    await db.refresh(secret)
    return secret


async def delete_secret(
    db: AsyncSession,
    secret: ProjectSecret,
    *,
    user_id: uuid.UUID | None = None,
) -> None:
    await _audit(db, secret.id, user_id, "deleted", f"Secret '{secret.name}' deleted")
    await db.delete(secret)
    await db.commit()


async def get_audit_log(
    db: AsyncSession,
    secret_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int | None = None,
) -> list[SecretAuditLog]:
    if limit is None:
        limit = settings.SECRET_AUDIT_DEFAULT_LIMIT
    result = await db.execute(
        select(SecretAuditLog)
        .where(SecretAuditLog.secret_id == secret_id)
        .order_by(SecretAuditLog.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def _audit(
    db: AsyncSession,
    secret_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: str,
    details: str | None = None,
) -> None:
    log = SecretAuditLog(
        secret_id=secret_id,
        user_id=user_id,
        action=action,
        details=details,
    )
    db.add(log)
