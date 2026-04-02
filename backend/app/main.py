"""
ASGI application entrypoint.

Run locally::

    uvicorn app.main:app --reload --reload-dir app --reload-dir alembic --host 0.0.0.0 --port 8000
"""

from app.application import create_app

app = create_app()
