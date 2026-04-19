"""PR Review routes — thin proxy to GitHub REST + GraphQL APIs.

Supports GitHub-style review workflow:
  - Single comment (immediate): create + submit in one step
  - Start a review (pending): accumulate comments, then submit with event
  - Submit review: COMMENT / APPROVE / REQUEST_CHANGES
  - Delete own comments and discard pending reviews
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal
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
GITHUB_API = "https://api.github.com"
GQL_URL = "https://api.github.com/graphql"


def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _get_github_token(db: AsyncSession, user_id: UUID) -> str:
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
    tool_name: str, args: dict[str, Any], db: AsyncSession, user_id: UUID,
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


async def _graphql(token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            GQL_URL,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            json={"query": query, "variables": variables},
        )
    if resp.status_code != 200:
        logger.warning("GitHub GraphQL HTTP %d: %s", resp.status_code, resp.text[:500])
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    body = resp.json()
    if "errors" in body:
        errors = body["errors"]
        msg = errors[0].get("message", str(errors)) if errors else "Unknown GraphQL error"
        err_type = errors[0].get("type", "") if errors else ""
        logger.warning("GitHub GraphQL error: %s (type=%s)", msg, err_type)
        lower = msg.lower()
        if "not found" in lower:
            code = 404
        elif "can not" in lower or "cannot" in lower or "forbidden" in lower or err_type == "FORBIDDEN":
            code = 403
        else:
            code = 502
        raise HTTPException(status_code=code, detail=msg)
    return body.get("data", {})


async def _get_pr_node_id(token: str, owner: str, repo: str, pr_number: int) -> str:
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=_gh_headers(token),
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    node_id = resp.json().get("node_id")
    if not node_id:
        raise HTTPException(status_code=500, detail="PR node_id not found")
    return node_id


GQL_CREATE_REVIEW = """
mutation($input: AddPullRequestReviewInput!) {
  addPullRequestReview(input: $input) {
    pullRequestReview { id databaseId }
  }
}
"""

GQL_ADD_THREAD = """
mutation($input: AddPullRequestReviewThreadInput!) {
  addPullRequestReviewThread(input: $input) {
    thread {
      id
      comments(first: 1) {
        nodes { id databaseId }
      }
    }
  }
}
"""

GQL_SUBMIT_REVIEW = """
mutation($input: SubmitPullRequestReviewInput!) {
  submitPullRequestReview(input: $input) {
    pullRequestReview { id state url }
  }
}
"""

GQL_DELETE_REVIEW = """
mutation($input: DeletePullRequestReviewInput!) {
  deletePullRequestReview(input: $input) {
    pullRequestReview { id }
  }
}
"""


def _build_thread_input(
    review_id: str, payload: "CreateCommentBody",
) -> dict[str, Any]:
    inp: dict[str, Any] = {
        "pullRequestReviewId": review_id,
        "path": payload.path,
        "body": payload.body,
        "line": payload.line,
        "side": payload.side,
        "subjectType": "LINE",
    }
    if payload.start_line is not None:
        inp["startLine"] = payload.start_line
        inp["startSide"] = payload.start_side or payload.side
    return inp


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
    await require_project_access(db, current.id, project_id)
    token = await _get_github_token(db, current.id)
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=_gh_headers(token),
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


# ── PR Files ────────────────────────────────────────────────────────────


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
        db, current.id,
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
        db, current.id,
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
    await require_project_access(db, current.id, project_id)
    token = await _get_github_token(db, current.id)
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/comments",
            headers=_gh_headers(token),
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
    """Create an inline comment and immediately submit it (single comment)."""
    await require_project_access(db, current.id, project_id)
    token = await _get_github_token(db, current.id)
    pr_node_id = await _get_pr_node_id(token, owner, repo, pr_number)

    review_data = await _graphql(token, GQL_CREATE_REVIEW, {
        "input": {"pullRequestId": pr_node_id, "commitOID": payload.commit_id}
    })
    review_id = review_data["addPullRequestReview"]["pullRequestReview"]["id"]

    await _graphql(token, GQL_ADD_THREAD, {
        "input": _build_thread_input(review_id, payload)
    })

    result = await _graphql(token, GQL_SUBMIT_REVIEW, {
        "input": {"pullRequestReviewId": review_id, "event": "COMMENT", "body": ""}
    })
    return result.get("submitPullRequestReview", {"status": "ok"})


# ── Pending Review (Start a Review) ─────────────────────────────────────


async def _find_pending_review(
    token: str, owner: str, repo: str, pr_number: int,
) -> dict[str, Any] | None:
    """Find the authenticated user's PENDING review on a PR, if any."""
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            headers=_gh_headers(token),
            params={"per_page": "100"},
        )
    if resp.status_code != 200:
        return None
    for r in resp.json():
        if r.get("state") == "PENDING":
            return r
    return None


async def _find_or_create_pending_review(
    token: str, owner: str, repo: str, pr_number: int, commit_id: str,
) -> tuple[str, int | None]:
    """Return (node_id, database_id) of a pending review, creating one if needed."""
    existing = await _find_pending_review(token, owner, repo, pr_number)
    if existing:
        return existing["node_id"], existing.get("id")

    pr_node_id = await _get_pr_node_id(token, owner, repo, pr_number)
    review_data = await _graphql(token, GQL_CREATE_REVIEW, {
        "input": {"pullRequestId": pr_node_id, "commitOID": commit_id}
    })
    review = review_data["addPullRequestReview"]["pullRequestReview"]
    return review["id"], review.get("databaseId")


@router.get("/projects/{project_id}/reviews/pulls/{pr_number}/pending-review")
async def get_pending_review(
    project_id: UUID,
    pr_number: int,
    owner: str = Query(...),
    repo: str = Query(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Check if the user has an existing pending review on this PR."""
    await require_project_access(db, current.id, project_id)
    token = await _get_github_token(db, current.id)
    pending = await _find_pending_review(token, owner, repo, pr_number)
    if not pending:
        return {"pending": False}

    review_id = pending["id"]
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}"
            f"/reviews/{review_id}/comments",
            headers=_gh_headers(token),
            params={"per_page": "100"},
        )
    comments = resp.json() if resp.status_code == 200 else []

    return {
        "pending": True,
        "review_node_id": pending["node_id"],
        "review_id": review_id,
        "comments": comments,
    }


class StartReviewBody(BaseModel):
    path: str
    line: int
    side: str
    body: str
    commit_id: str
    start_line: int | None = None
    start_side: str | None = None


@router.post("/projects/{project_id}/reviews/pulls/{pr_number}/pending-review")
async def start_pending_review(
    project_id: UUID,
    pr_number: int,
    payload: StartReviewBody,
    owner: str = Query(...),
    repo: str = Query(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new pending review (or reuse existing) with an inline comment."""
    await require_project_access(db, current.id, project_id)
    token = await _get_github_token(db, current.id)

    review_node_id, review_db_id = await _find_or_create_pending_review(
        token, owner, repo, pr_number, payload.commit_id,
    )

    comment_body = CreateCommentBody(
        path=payload.path, line=payload.line, side=payload.side,
        body=payload.body, commit_id=payload.commit_id,
        start_line=payload.start_line, start_side=payload.start_side,
    )
    result = await _graphql(token, GQL_ADD_THREAD, {
        "input": _build_thread_input(review_node_id, comment_body)
    })

    comment_id = None
    nodes = (result.get("addPullRequestReviewThread", {})
             .get("thread", {}).get("comments", {}).get("nodes", []))
    if nodes:
        comment_id = nodes[0].get("databaseId")

    return {"review_node_id": review_node_id, "review_id": review_db_id, "comment_id": comment_id}


class AddReviewCommentBody(BaseModel):
    review_node_id: str
    path: str
    line: int
    side: str
    body: str
    commit_id: str
    start_line: int | None = None
    start_side: str | None = None


@router.post("/projects/{project_id}/reviews/pulls/{pr_number}/pending-review/comments")
async def add_pending_review_comment(
    project_id: UUID,
    pr_number: int,
    payload: AddReviewCommentBody,
    owner: str = Query(...),
    repo: str = Query(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Add another inline comment to an existing pending review."""
    await require_project_access(db, current.id, project_id)
    token = await _get_github_token(db, current.id)

    comment_body = CreateCommentBody(
        path=payload.path, line=payload.line, side=payload.side,
        body=payload.body, commit_id=payload.commit_id,
        start_line=payload.start_line, start_side=payload.start_side,
    )
    result = await _graphql(token, GQL_ADD_THREAD, {
        "input": _build_thread_input(payload.review_node_id, comment_body)
    })

    comment_id = None
    nodes = (result.get("addPullRequestReviewThread", {})
             .get("thread", {}).get("comments", {}).get("nodes", []))
    if nodes:
        comment_id = nodes[0].get("databaseId")

    return {"status": "ok", "comment_id": comment_id}


class SubmitReviewBody(BaseModel):
    review_node_id: str
    event: Literal["COMMENT", "APPROVE", "REQUEST_CHANGES"]
    body: str = ""


@router.post("/projects/{project_id}/reviews/pulls/{pr_number}/pending-review/submit")
async def submit_pending_review(
    project_id: UUID,
    pr_number: int,
    payload: SubmitReviewBody,
    owner: str = Query(...),
    repo: str = Query(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Submit a pending review with COMMENT, APPROVE, or REQUEST_CHANGES."""
    await require_project_access(db, current.id, project_id)
    token = await _get_github_token(db, current.id)

    result = await _graphql(token, GQL_SUBMIT_REVIEW, {
        "input": {
            "pullRequestReviewId": payload.review_node_id,
            "event": payload.event,
            "body": payload.body,
        }
    })
    return result.get("submitPullRequestReview", {"status": "ok"})


class DirectReviewBody(BaseModel):
    event: Literal["COMMENT", "APPROVE", "REQUEST_CHANGES"]
    body: str = ""


@router.post("/projects/{project_id}/reviews/pulls/{pr_number}/review")
async def create_direct_review(
    project_id: UUID,
    pr_number: int,
    payload: DirectReviewBody,
    owner: str = Query(...),
    repo: str = Query(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create and submit a review in one step (no inline comments).

    Uses the REST API: POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews
    with an event, which creates and submits immediately.
    """
    await require_project_access(db, current.id, project_id)
    token = await _get_github_token(db, current.id)

    req_body: dict[str, Any] = {"event": payload.event}
    if payload.body:
        req_body["body"] = payload.body

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            headers=_gh_headers(token),
            json=req_body,
        )
    if resp.status_code not in (200, 201):
        detail = resp.text
        try:
            data = resp.json()
            detail = data.get("message", resp.text)
            if data.get("errors"):
                err_msgs = [e.get("message", str(e)) for e in data["errors"] if isinstance(e, dict)]
                if err_msgs:
                    detail = err_msgs[0]
        except Exception:
            pass
        logger.warning("GitHub review API %d: %s", resp.status_code, detail)
        code = 403 if resp.status_code == 422 else resp.status_code
        raise HTTPException(status_code=code, detail=detail)
    return resp.json()


class DiscardReviewBody(BaseModel):
    review_node_id: str
    review_db_id: int | None = None


@router.post("/projects/{project_id}/reviews/pulls/{pr_number}/pending-review/discard")
async def discard_pending_review(
    project_id: UUID,
    pr_number: int,
    payload: DiscardReviewBody,
    owner: str = Query(...),
    repo: str = Query(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Discard (delete) a pending review and all its pending comments.

    Tries REST API first (more reliable), falls back to GraphQL.
    """
    await require_project_access(db, current.id, project_id)
    token = await _get_github_token(db, current.id)

    review_id = payload.review_db_id
    if not review_id:
        pending = await _find_pending_review(token, owner, repo, pr_number)
        if pending:
            review_id = pending.get("id")

    if review_id:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.delete(
                f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}"
                f"/reviews/{review_id}",
                headers=_gh_headers(token),
            )
        if resp.status_code in (200, 204):
            return {"status": "discarded"}
        logger.warning("REST delete review %d: %s", resp.status_code, resp.text[:300])

    result = await _graphql(token, GQL_DELETE_REVIEW, {
        "input": {"pullRequestReviewId": payload.review_node_id}
    })
    return result.get("deletePullRequestReview", {"status": "ok"})


# ── Delete Comment ──────────────────────────────────────────────────────


@router.delete(
    "/projects/{project_id}/reviews/pulls/{pr_number}/comments/{comment_id}"
)
async def delete_comment(
    project_id: UUID,
    pr_number: int,
    comment_id: int,
    owner: str = Query(...),
    repo: str = Query(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Delete a PR review comment (only your own)."""
    await require_project_access(db, current.id, project_id)
    token = await _get_github_token(db, current.id)

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.delete(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/comments/{comment_id}",
            headers=_gh_headers(token),
        )
    if resp.status_code not in (204, 200):
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return {"status": "deleted"}


# ── Reply to Comment ────────────────────────────────────────────────────


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
    await require_project_access(db, current.id, project_id)
    token = await _get_github_token(db, current.id)

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}"
            f"/comments/{comment_id}/replies",
            headers=_gh_headers(token),
            json={"body": payload.body},
        )
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


# ── PR Reviews List ─────────────────────────────────────────────────────


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
    token = await _get_github_token(db, current.id)
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            headers=_gh_headers(token),
            params={"per_page": "100"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return {"reviews": resp.json()}


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
        db, current.id,
    )
    return data if isinstance(data, dict) else {"checks": data}
