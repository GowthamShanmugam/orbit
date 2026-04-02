"""Secret Vault service — CRUD, audit logging, and bulk operations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.secret_vault import decrypt, encrypt, make_placeholder
from app.models.secret import (
    ProjectSecret,
    SecretAuditLog,
    SecretScope,
    VaultBackend,
)


async def list_secrets(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int | None = None,
) -> list[ProjectSecret]:
    if limit is None:
        limit = settings.SECRET_LIST_DEFAULT_LIMIT
    result = await db.execute(
        select(ProjectSecret)
        .where(ProjectSecret.project_id == project_id)
        .order_by(ProjectSecret.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_secret(db: AsyncSession, secret_id: uuid.UUID) -> ProjectSecret | None:
    result = await db.execute(
        select(ProjectSecret).where(ProjectSecret.id == secret_id)
    )
    return result.scalar_one_or_none()


async def create_secret(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    name: str,
    value: str,
    scope: SecretScope = SecretScope.project,
    description: str | None = None,
    created_by: uuid.UUID | None = None,
) -> ProjectSecret:
    ciphertext, nonce, tag = encrypt(value)
    placeholder = make_placeholder(name)

    secret = ProjectSecret(
        project_id=project_id,
        name=name,
        scope=scope,
        encrypted_value=ciphertext,
        nonce=nonce,
        tag=tag,
        placeholder_key=placeholder.strip("{}").split(":", 1)[1] if ":" in placeholder.strip("{}") else name,
        vault_backend=VaultBackend.builtin,
        description=description,
        created_by=created_by,
    )
    db.add(secret)
    await db.flush()

    await _audit(db, secret.id, created_by, "created", f"Secret '{name}' created")
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


async def decrypt_secret(
    db: AsyncSession,
    secret: ProjectSecret,
    *,
    user_id: uuid.UUID | None = None,
) -> str:
    """Decrypt and return the secret value, logging the access."""
    value = decrypt(secret.encrypted_value, secret.nonce, secret.tag)
    await _audit(db, secret.id, user_id, "accessed", f"Secret '{secret.name}' decrypted")
    await db.commit()
    return value


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
