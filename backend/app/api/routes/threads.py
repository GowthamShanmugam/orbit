"""Thread endpoints — branch conversations from specific messages."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.routes.projects import require_orbit_session_in_project
from app.core.database import get_db
from app.core.secret_scanner import scan_text
from app.core.secret_vault import make_placeholder
from app.core.security import get_current_user
from app.models.session import Message, MessageRole, Thread
from app.models.session import Session as OrbitSession
from app.models.user import User

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ThreadCreate(BaseModel):
    parent_message_id: UUID


class ThreadResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    session_id: UUID
    parent_message_id: UUID
    title: str
    reply_count: int = 0
    created_at: datetime


class ThreadDetailResponse(ThreadResponse):
    messages: list["ThreadMessageResponse"]


class ThreadMessageResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    session_id: UUID
    thread_id: UUID | None
    role: MessageRole
    content: str
    created_at: datetime


class ThreadChatRequest(BaseModel):
    message: str = Field(min_length=1)
    model: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _require_thread(
    db: AsyncSession,
    user_id: UUID,
    project_id: UUID,
    session_id: UUID,
    thread_id: UUID,
    *,
    min_access: str = "read",
) -> Thread:
    await require_orbit_session_in_project(
        db, user_id, project_id, session_id, min_access=min_access,
    )
    result = await db.execute(
        select(Thread).where(Thread.id == thread_id, Thread.session_id == session_id)
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    return thread


def _sse_event(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def _thread_reply_count(db: AsyncSession, thread_id: UUID) -> int:
    result = await db.execute(
        select(func.count()).select_from(Message).where(Message.thread_id == thread_id)
    )
    return result.scalar() or 0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/sessions/{session_id}/threads",
    response_model=ThreadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_thread(
    project_id: UUID,
    session_id: UUID,
    body: ThreadCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    await require_orbit_session_in_project(
        db, current.id, project_id, session_id, min_access="write",
    )

    msg_result = await db.execute(
        select(Message).where(
            Message.id == body.parent_message_id,
            Message.session_id == session_id,
        )
    )
    parent_msg = msg_result.scalar_one_or_none()
    if parent_msg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Parent message not found",
        )

    existing = await db.execute(
        select(Thread).where(
            Thread.session_id == session_id,
            Thread.parent_message_id == body.parent_message_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A thread already exists for this message",
        )

    title = parent_msg.content[:80].strip() or "Thread"

    thread = Thread(
        session_id=session_id,
        parent_message_id=body.parent_message_id,
        title=title,
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)

    return {**thread.__dict__, "reply_count": 0}


@router.get(
    "/projects/{project_id}/sessions/{session_id}/threads",
    response_model=list[ThreadResponse],
)
async def list_threads(
    project_id: UUID,
    session_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, Any]]:
    await require_orbit_session_in_project(
        db, current.id, project_id, session_id, min_access="read",
    )
    result = await db.execute(
        select(Thread)
        .where(Thread.session_id == session_id)
        .order_by(Thread.created_at.asc())
    )
    threads = result.scalars().all()
    out = []
    for t in threads:
        count = await _thread_reply_count(db, t.id)
        out.append({**t.__dict__, "reply_count": count})
    return out


@router.get(
    "/projects/{project_id}/sessions/{session_id}/threads/{thread_id}",
    response_model=ThreadDetailResponse,
)
async def get_thread(
    project_id: UUID,
    session_id: UUID,
    thread_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    thread = await _require_thread(
        db, current.id, project_id, session_id, thread_id, min_access="read",
    )
    msg_result = await db.execute(
        select(Message)
        .where(Message.thread_id == thread_id)
        .order_by(Message.created_at.asc())
    )
    messages = list(msg_result.scalars().all())
    count = len(messages)
    return {**thread.__dict__, "reply_count": count, "messages": messages}


@router.delete(
    "/projects/{project_id}/sessions/{session_id}/threads/{thread_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_thread(
    project_id: UUID,
    session_id: UUID,
    thread_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    thread = await _require_thread(
        db, current.id, project_id, session_id, thread_id, min_access="write",
    )
    await db.delete(thread)
    await db.commit()


@router.post("/projects/{project_id}/sessions/{session_id}/threads/{thread_id}/chat")
async def thread_chat(
    project_id: UUID,
    session_id: UUID,
    thread_id: UUID,
    body: ThreadChatRequest,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """Stream an AI response within a branch thread via SSE."""
    from app.services.ai_service import chat_stream_thread

    session = await require_orbit_session_in_project(
        db, current.id, project_id, session_id, min_access="write",
    )
    thread = await _require_thread(
        db, current.id, project_id, session_id, thread_id, min_access="write",
    )

    scan_matches = scan_text(body.message)
    redacted_message = body.message
    if scan_matches:
        for match in sorted(scan_matches, key=lambda m: m.start, reverse=True):
            placeholder = make_placeholder(
                f"detected_{match.pattern_name.lower().replace(' ', '_')}"
            )
            redacted_message = (
                redacted_message[: match.start] + placeholder + redacted_message[match.end :]
            )

    user_msg = Message(
        session_id=session_id,
        thread_id=thread_id,
        role=MessageRole.user,
        content=body.message,
        metadata_={
            "model": body.model or session.claude_model,
            "secret_scan": {
                "has_secrets": len(scan_matches) > 0,
                "count": len(scan_matches),
            },
        },
    )
    db.add(user_msg)
    await db.commit()
    await db.refresh(user_msg)

    model = body.model or session.claude_model

    async def event_generator():
        yield _sse_event("user_message", {
            "id": str(user_msg.id),
            "content": body.message,
            "thread_id": str(thread_id),
        })

        async for event in chat_stream_thread(
            db,
            project_id=project_id,
            session_id=session_id,
            thread_id=thread_id,
            parent_message_id=thread.parent_message_id,
            user_message=redacted_message,
            user_message_id=user_msg.id,
            model=model,
            ai_config=session.ai_config,
        ):
            yield _sse_event(event["type"], event)

        yield _sse_event("done", {})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
