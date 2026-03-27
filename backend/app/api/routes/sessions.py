from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.routes.projects import (
    require_orbit_session_in_project,
    require_project_access,
)
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.session import Message, MessageRole, Session as OrbitSession, SessionStatus
from app.models.user import User

router = APIRouter()


class SessionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1, max_length=512)
    model: str | None = Field(default=None, max_length=128, alias="model")
    ai_config: dict[str, Any] | None = None


class SessionUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str | None = Field(default=None, min_length=1, max_length=512)
    status: SessionStatus | None = None
    model: str | None = Field(default=None, max_length=128, alias="model")
    ai_config: dict[str, Any] | None = None


class MessageCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    role: MessageRole
    content: str
    metadata_: dict[str, Any] | None = Field(default=None, alias="metadata")


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    role: MessageRole
    content: str
    metadata_: dict[str, Any] | None = Field(default=None, serialization_alias="metadata")
    created_at: datetime


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    title: str
    status: SessionStatus
    project_id: UUID
    user_id: UUID
    claude_model: str = Field(exclude=True)
    ai_config: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def model(self) -> str:
        return self.claude_model


class SessionDetailResponse(SessionResponse):
    messages: list[MessageResponse]


@router.get("/projects/{project_id}/sessions", response_model=list[SessionResponse])
async def list_sessions(
    project_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[OrbitSession]:
    await require_project_access(db, current.id, project_id)
    result = await db.execute(
        select(OrbitSession)
        .where(OrbitSession.project_id == project_id)
        .order_by(OrbitSession.created_at.desc()),
    )
    return list(result.scalars().all())


@router.post(
    "/projects/{project_id}/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    project_id: UUID,
    body: SessionCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrbitSession:
    await require_project_access(db, current.id, project_id, min_access="write")
    orbit_session = OrbitSession(
        title=body.title,
        project_id=project_id,
        user_id=current.id,
        claude_model=body.model or "claude-sonnet-4-5-20250929",
        ai_config=body.ai_config,
    )
    db.add(orbit_session)
    await db.commit()
    await db.refresh(orbit_session)
    return orbit_session


@router.get("/projects/{project_id}/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    project_id: UUID,
    session_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrbitSession:
    await require_project_access(db, current.id, project_id)
    result = await db.execute(
        select(OrbitSession)
        .options(selectinload(OrbitSession.messages))
        .where(OrbitSession.id == session_id, OrbitSession.project_id == project_id),
    )
    orbit_session = result.scalar_one_or_none()
    if orbit_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    orbit_session.messages.sort(key=lambda m: m.created_at)
    return orbit_session


@router.put("/projects/{project_id}/sessions/{session_id}", response_model=SessionResponse)
@router.patch("/projects/{project_id}/sessions/{session_id}", response_model=SessionResponse)
async def update_session(
    project_id: UUID,
    session_id: UUID,
    body: SessionUpdate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrbitSession:
    orbit_session = await require_orbit_session_in_project(
        db, current.id, project_id, session_id, min_access="write"
    )
    if body.title is not None:
        orbit_session.title = body.title
    if body.status is not None:
        orbit_session.status = body.status
    if body.model is not None:
        orbit_session.claude_model = body.model
    if body.ai_config is not None:
        orbit_session.ai_config = body.ai_config
    await db.commit()
    await db.refresh(orbit_session)
    return orbit_session


@router.delete("/projects/{project_id}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    project_id: UUID,
    session_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    orbit_session = await require_orbit_session_in_project(
        db, current.id, project_id, session_id, min_access="write"
    )
    await db.delete(orbit_session)
    await db.commit()


@router.post(
    "/projects/{project_id}/sessions/{session_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_message(
    project_id: UUID,
    session_id: UUID,
    body: MessageCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Message:
    await require_orbit_session_in_project(
        db, current.id, project_id, session_id, min_access="write"
    )
    message = Message(
        session_id=session_id,
        role=body.role,
        content=body.content,
        metadata_=body.metadata_,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


@router.get("/projects/{project_id}/sessions/{session_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    project_id: UUID,
    session_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> list[Message]:
    await require_orbit_session_in_project(
        db, current.id, project_id, session_id, min_access="read"
    )
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .offset(skip)
        .limit(limit),
    )
    return list(result.scalars().all())
