"""PR Review routes — thin proxy to GitHub MCP tools.

All endpoints require the calling user to have a configured GitHub integration
(UserPluginConfig with slug='github' and an enabled status).

Uses the @modelcontextprotocol/server-github MCP server which exposes:
  - list_pull_requests(owner, repo, state?, ...)
  - get_pull_request(owner, repo, pull_number)
  - get_pull_request_files(owner, repo, pull_number)
  - get_pull_request_comments(owner, repo, pull_number)
  - get_pull_request_reviews(owner, repo, pull_number)
  - get_pull_request_status(owner, repo, pull_number)
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.projects import require_project_access
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.skill import SkillPlugin, UserPluginConfig
from app.models.user import User
from app.services import mcp_client

router = APIRouter()
logger = logging.getLogger(__name__)

GITHUB_TOOL_PREFIX = "mcp_github__"


async def _get_github_token(db: AsyncSession, user_id: UUID) -> str:
    """Retrieve the user's GitHub PAT from their plugin config."""
    result = await db.execute(
        select(UserPluginConfig)
        .join(SkillPlugin, SkillPlugin.id == UserPluginConfig.plugin_id)
        .where(
            SkillPlugin.slug == "github",
            UserPluginConfig.user_id == user_id,
            UserPluginConfig.enabled,
        )
    )
    cfg = result.scalar_one_or_none()
    if not cfg or not cfg.config_values:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub integration not configured.",
        )
    token = cfg.config_values.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub token not found in configuration.",
        )
    return token


async def _call_github_tool(
    tool_name: str,
    args: dict[str, Any],
    db: AsyncSession,
    user_id: UUID,
) -> Any:
    full_name = f"{GITHUB_TOOL_PREFIX}{tool_name}"
    try:
        raw = await mcp_client.execute_tool(full_name, args, db, user_id)
    except Exception as exc:
        logger.warning("GitHub MCP tool %s failed: %s", tool_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub tool call failed: {exc}",
        ) from exc

    if isinstance(raw, str) and raw.startswith("Error"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=raw)

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


# ── List PRs ────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/reviews/pulls")
async def list_pulls(
    project_id: UUID,
    owner: str = Query(...),
    repo: str = Query(...),
    state: str = Query("open"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    await require_project_access(db, current.id, project_id)
    data = await _call_github_tool(
        "list_pull_requests",
        {"owner": owner, "repo": repo, "state": state},
        db,
        current.id,
    )
    if isinstance(data, list):
        return data
    return data if isinstance(data, list) else [data] if data else []


# ── PR Detail ───────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/reviews/pulls/{pr_number}")
async def get_pull(
    project_id: UUID,
    pr_number: int,
    owner: str = Query(...),
    repo: str = Query(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Fetch PR detail via the GitHub REST API directly.

    The MCP get_pull_request tool has a Zod validation bug that rejects PRs
    from deleted forks (head.repo is null). Calling the API directly avoids this.
    """
    await require_project_access(db, current.id, project_id)
    token = await _get_github_token(db, current.id)
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if resp.status_code != 200:
        logger.warning(
            "GitHub API returned %d for %s/%s#%d",
            resp.status_code, owner, repo, pr_number,
        )
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


# ── PR Files (includes patches) ─────────────────────────────────────────

@router.get("/projects/{project_id}/reviews/pulls/{pr_number}/diff")
async def get_pull_diff(
    project_id: UUID,
    pr_number: int,
    owner: str = Query(...),
    repo: str = Query(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await require_project_access(db, current.id, project_id)
    data = await _call_github_tool(
        "get_pull_request_files",
        {"owner": owner, "repo": repo, "pull_number": pr_number},
        db,
        current.id,
    )
    return data if isinstance(data, dict) else {"files": data}


@router.get("/projects/{project_id}/reviews/pulls/{pr_number}/files")
async def get_pull_files(
    project_id: UUID,
    pr_number: int,
    owner: str = Query(...),
    repo: str = Query(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await require_project_access(db, current.id, project_id)
    data = await _call_github_tool(
        "get_pull_request_files",
        {"owner": owner, "repo": repo, "pull_number": pr_number},
        db,
        current.id,
    )
    return data if isinstance(data, dict) else {"files": data}


# ── PR Comments ─────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/reviews/pulls/{pr_number}/comments")
async def get_pull_comments(
    project_id: UUID,
    pr_number: int,
    owner: str = Query(...),
    repo: str = Query(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Fetch PR review comments via the REST API directly.

    The REST API includes in_reply_to_id which is needed for threading.
    The MCP tool may strip this field.
    """
    await require_project_access(db, current.id, project_id)
    token = await _get_github_token(db, current.id)
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params={"per_page": "100"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return {"comments": resp.json()}


class CreateCommentBody(BaseModel):
    path: str
    line: int
    side: str
    body: str
    commit_id: str
    start_line: int | None = None
    start_side: str | None = None


GQL_HEADERS = {"Content-Type": "application/json"}
GQL_URL = "https://api.github.com/graphql"


async def _graphql(token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Execute a GitHub GraphQL query; raise HTTPException on error."""
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            GQL_URL,
            headers={**GQL_HEADERS, "Authorization": f"Bearer {token}"},
            json={"query": query, "variables": variables},
        )
    if resp.status_code != 200:
        logger.warning("GitHub GraphQL HTTP %d: %s", resp.status_code, resp.text[:500])
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    body = resp.json()
    if "errors" in body:
        errors = body["errors"]
        msg = errors[0].get("message", str(errors)) if errors else "Unknown GraphQL error"
        logger.warning("GitHub GraphQL error: %s | variables: %s", msg, json.dumps(variables)[:500])
        raise HTTPException(status_code=422, detail=msg)
    return body.get("data", {})


@router.post("/projects/{project_id}/reviews/pulls/{pr_number}/comments")
async def create_pull_comment(
    project_id: UUID,
    pr_number: int,
    payload: CreateCommentBody,
    owner: str = Query(...),
    repo: str = Query(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create an inline review comment via the GitHub GraphQL API.

    Uses a 3-step flow:
    1. Get PR node_id from REST API
    2. Create a pending review (addPullRequestReview, no event)
    3. Add comment thread (addPullRequestReviewThread with line/side)
    4. Submit the review (submitPullRequestReview)
    """
    await require_project_access(db, current.id, project_id)
    token = await _get_github_token(db, current.id)

    # 1 ── Get the PR node_id
    async with httpx.AsyncClient(timeout=30) as http:
        pr_resp = await http.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if pr_resp.status_code != 200:
        raise HTTPException(status_code=pr_resp.status_code, detail=pr_resp.text)
    pr_node_id = pr_resp.json().get("node_id")
    if not pr_node_id:
        raise HTTPException(status_code=500, detail="PR node_id not found")

    # 2 ── Create a pending review
    create_review = """
    mutation($input: AddPullRequestReviewInput!) {
      addPullRequestReview(input: $input) {
        pullRequestReview { id }
      }
    }
    """
    review_data = await _graphql(token, create_review, {
        "input": {
            "pullRequestId": pr_node_id,
            "commitOID": payload.commit_id,
        }
    })
    review_id = review_data["addPullRequestReview"]["pullRequestReview"]["id"]

    # 3 ── Add the inline comment thread to the pending review
    add_thread = """
    mutation($input: AddPullRequestReviewThreadInput!) {
      addPullRequestReviewThread(input: $input) {
        thread { id }
      }
    }
    """
    thread_input: dict[str, Any] = {
        "pullRequestReviewId": review_id,
        "path": payload.path,
        "body": payload.body,
        "line": payload.line,
        "side": payload.side,
        "subjectType": "LINE",
    }
    if payload.start_line is not None:
        thread_input["startLine"] = payload.start_line
        thread_input["startSide"] = payload.start_side or payload.side

    await _graphql(token, add_thread, {"input": thread_input})

    # 4 ── Submit the review
    submit_review = """
    mutation($input: SubmitPullRequestReviewInput!) {
      submitPullRequestReview(input: $input) {
        pullRequestReview { id state url }
      }
    }
    """
    result = await _graphql(token, submit_review, {
        "input": {
            "pullRequestReviewId": review_id,
            "event": "COMMENT",
            "body": "",
        }
    })

    return result.get("submitPullRequestReview", {"status": "ok"})


class ReplyCommentBody(BaseModel):
    body: str


@router.post(
    "/projects/{project_id}/reviews/pulls/{pr_number}/comments/{comment_id}/replies"
)
async def reply_to_comment(
    project_id: UUID,
    pr_number: int,
    comment_id: int,
    payload: ReplyCommentBody,
    owner: str = Query(...),
    repo: str = Query(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reply to an existing PR review comment via the GitHub REST API."""
    await require_project_access(db, current.id, project_id)
    token = await _get_github_token(db, current.id)

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
            f"/comments/{comment_id}/replies",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"body": payload.body},
        )
    if resp.status_code not in (200, 201):
        logger.warning(
            "GitHub API reply returned %d for %s/%s#%d comment %d: %s",
            resp.status_code, owner, repo, pr_number, comment_id, resp.text[:300],
        )
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


# ── PR Reviews ──────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/reviews/pulls/{pr_number}/reviews")
async def get_pull_reviews(
    project_id: UUID,
    pr_number: int,
    owner: str = Query(...),
    repo: str = Query(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await require_project_access(db, current.id, project_id)
    data = await _call_github_tool(
        "get_pull_request_reviews",
        {"owner": owner, "repo": repo, "pull_number": pr_number},
        db,
        current.id,
    )
    return data if isinstance(data, dict) else {"reviews": data}


# ── CI Checks ───────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/reviews/pulls/{pr_number}/checks")
async def get_pull_checks(
    project_id: UUID,
    pr_number: int,
    owner: str = Query(...),
    repo: str = Query(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await require_project_access(db, current.id, project_id)
    data = await _call_github_tool(
        "get_pull_request_status",
        {"owner": owner, "repo": repo, "pull_number": pr_number},
        db,
        current.id,
    )
    return data if isinstance(data, dict) else {"checks": data}
