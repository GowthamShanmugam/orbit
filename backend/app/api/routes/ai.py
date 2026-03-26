"""AI chat endpoints — streaming chat via SSE, model listing."""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.projects import require_project_access
from app.api.routes.sessions import require_orbit_session
from app.core.database import get_db
from app.core.secret_scanner import scan_text
from app.core.secret_vault import make_placeholder
from app.core.security import get_current_user
from app.models.session import Message, MessageRole
from app.models.user import User
from app.services.ai_service import AVAILABLE_MODELS, chat_stream

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    model: str | None = None


class ModelInfo(BaseModel):
    id: str
    display_name: str
    description: str
    max_tokens: int


@router.get("/ai/models", response_model=list[ModelInfo])
async def list_models(
    _current: Annotated[User, Depends(get_current_user)],
) -> list[ModelInfo]:
    return [
        ModelInfo(id=mid, **info)
        for mid, info in AVAILABLE_MODELS.items()
    ]


@router.post("/projects/{project_id}/sessions/{session_id}/chat")
async def chat(
    project_id: UUID,
    session_id: UUID,
    body: ChatRequest,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """Stream an AI response via Server-Sent Events.

    The frontend should use EventSource or fetch with ReadableStream to consume.
    """
    await require_project_access(db, current.id, project_id)
    session = await require_orbit_session(db, current.id, session_id)

    scan_matches = scan_text(body.message)
    redacted_message = body.message
    if scan_matches:
        for match in sorted(scan_matches, key=lambda m: m.start, reverse=True):
            original = body.message[match.start:match.end]
            placeholder = make_placeholder(f"detected_{match.pattern_name.lower().replace(' ', '_')}")
            redacted_message = (
                redacted_message[:match.start] + placeholder + redacted_message[match.end:]
            )

    user_msg = Message(
        session_id=session_id,
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
            "secret_warnings": [
                {
                    "pattern": m.pattern_name,
                    "severity": m.severity,
                    "suggestion": m.suggestion,
                    "masked": m.matched_text,
                }
                for m in scan_matches
            ],
        })

        async for event in chat_stream(
            db,
            project_id=project_id,
            session_id=session_id,
            user_message=redacted_message,
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


def _sse_event(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
