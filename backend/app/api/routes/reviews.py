"""PR Review routes — thin proxy to GitHub REST + GraphQL APIs.

Supports GitHub-style review workflow:
  - Single comment (immediate): create + submit in one step
  - Start a review (pending): accumulate comments, then submit with event
  - Submit review: COMMENT / APPROVE / REQUEST_CHANGES
  - Delete own comments and discard pending reviews
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlparse
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
Provider = Literal["github", "gitlab"]


def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gl_headers(token: str) -> dict[str, str]:
    # PRIVATE-TOKEN is the classic GitLab header; Bearer works on newer instances.
    return {
        "Authorization": f"Bearer {token}",
        "PRIVATE-TOKEN": token,
        "Accept": "application/json",
    }


def _normalize_gitlab_api_base(api: str) -> str:
    """Ensure the base URL points at the REST API (…/api/v4), not the web UI."""
    api = (api or "").strip().rstrip("/")
    if not api:
        return "https://gitlab.com/api/v4"
    path = (urlparse(api).path or "").rstrip("/")
    if "/api/" not in path:
        api = f"{api}/api/v4"
    return api


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


def _gitlab_verify_ssl(api_base: str, config_values: dict[str, Any]) -> bool:
    """TLS verify setting for GitLab HTTP calls.

    Self-hosted GitLab often uses a private CA / self-signed cert. Default:
    verify for gitlab.com, skip verify for other hosts. Override with
    ``GITLAB_SSL_VERIFY`` = true/false in the integration config.
    """
    raw = config_values.get("GITLAB_SSL_VERIFY")
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    host = api_base.lower()
    return "gitlab.com" in host


async def _get_gitlab_config(db: AsyncSession, user_id: UUID) -> tuple[str, str, bool]:
    """Return (token, api_base, verify_ssl) for the user's GitLab integration."""
    result = await db.execute(
        select(UserPluginConfig)
        .join(SkillPlugin, SkillPlugin.id == UserPluginConfig.plugin_id)
        .where(
            SkillPlugin.slug == "gitlab",
            UserPluginConfig.user_id == user_id,
            UserPluginConfig.enabled,
        )
    )
    cfg = result.scalar_one_or_none()
    if not cfg or not cfg.config_values:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitLab integration not configured.",
        )
    token = (cfg.config_values.get("GITLAB_PERSONAL_ACCESS_TOKEN") or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitLab token not found in configuration.",
        )
    api = _normalize_gitlab_api_base(
        cfg.config_values.get("GITLAB_API_URL") or "https://gitlab.com/api/v4"
    )
    return token, api, _gitlab_verify_ssl(api, cfg.config_values)


def _gitlab_project_path(owner: str, repo: str) -> str:
    return f"{owner.strip('/')}/{repo.strip('/')}"


def _count_diff_stats(diff: str) -> tuple[int, int]:
    additions = deletions = 0
    for line in (diff or "").splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


def _normalize_gitlab_mr(mr: dict[str, Any]) -> dict[str, Any]:
    """Map GitLab MR JSON to the GitHub-like shape the Orbit UI expects."""
    author = mr.get("author") or {}
    login = author.get("username") or author.get("name") or "unknown"
    src = mr.get("source_branch") or ""
    tgt = mr.get("target_branch") or ""
    diff_refs = mr.get("diff_refs") if isinstance(mr.get("diff_refs"), dict) else {}
    sha = diff_refs.get("head_sha") or mr.get("sha") or ""
    state = mr.get("state") or "opened"
    if state == "opened":
        state = "open"
    elif state == "merged":
        state = "closed"
    return {
        "number": mr.get("iid") or mr.get("id"),
        "title": mr.get("title") or "",
        "state": state,
        "user": {"login": login},
        "author": login,
        "created_at": mr.get("created_at") or "",
        "updated_at": mr.get("updated_at") or "",
        "head": {"ref": src, "sha": sha},
        "base": {"ref": tgt},
        "draft": bool(mr.get("draft") or mr.get("work_in_progress")),
        "html_url": mr.get("web_url") or "",
        "body": mr.get("description") or "",
        "merged_at": mr.get("merged_at"),
        "additions": mr.get("additions"),
        "deletions": mr.get("deletions"),
        "changed_files": mr.get("changes_count"),
        "provider": "gitlab",
    }


def _normalize_gitlab_changes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    changes = payload.get("changes") or []
    files: list[dict[str, Any]] = []
    for ch in changes:
        if not isinstance(ch, dict):
            continue
        diff = ch.get("diff") or ""
        additions, deletions = _count_diff_stats(diff)
        new_path = ch.get("new_path") or ch.get("old_path") or "unknown"
        old_path = ch.get("old_path") or new_path
        if ch.get("new_file"):
            status = "added"
        elif ch.get("deleted_file"):
            status = "removed"
        elif ch.get("renamed_file"):
            status = "renamed"
        else:
            status = "modified"
        files.append(
            {
                "filename": new_path,
                "previous_filename": old_path if old_path != new_path else None,
                "status": status,
                "additions": additions,
                "deletions": deletions,
                "patch": diff,
            }
        )
    return files


async def _gitlab_request(
    api_base: str,
    token: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    verify: bool = True,
    expect_json: bool = True,
) -> Any:
    url = f"{api_base}{path}"
    try:
        async with httpx.AsyncClient(
            timeout=60, verify=verify, follow_redirects=True
        ) as http:
            resp = await http.get(url, headers=_gl_headers(token), params=params)
    except httpx.ConnectError as exc:
        hint = ""
        if "CERTIFICATE" in str(exc).upper() or "SSL" in str(exc).upper():
            hint = (
                " TLS verification failed (common with self-signed GitLab). "
                "Set GITLAB_SSL_VERIFY=false on the GitLab integration, or use a trusted CA."
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach GitLab API:{hint} {exc}",
        ) from exc
    if resp.status_code != 200:
        # Never surface GitLab 3xx/login redirects as Orbit 302 — the UI can't follow them.
        detail = resp.text[:800] if resp.text else resp.reason_phrase
        if 300 <= resp.status_code < 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    f"GitLab API redirected ({resp.status_code}) instead of returning JSON. "
                    f"Check GITLAB_API_URL ends with /api/v4 and the token is valid. "
                    f"Tried: {url}"
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY
            if resp.status_code >= 500
            else resp.status_code,
            detail=f"GitLab API error ({resp.status_code}): {detail}",
        )
    if not expect_json:
        return resp.text or ""
    try:
        return resp.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "GitLab returned non-JSON (often the login HTML page). "
                f"Check GITLAB_API_URL and token. Tried: {url}"
            ),
        ) from exc


async def _gitlab_get(
    api_base: str,
    token: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    verify: bool = True,
) -> Any:
    return await _gitlab_request(
        api_base, token, path, params=params, verify=verify, expect_json=True
    )


async def _gitlab_get_text(
    api_base: str,
    token: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    verify: bool = True,
) -> str:
    text = await _gitlab_request(
        api_base, token, path, params=params, verify=verify, expect_json=False
    )
    return text if isinstance(text, str) else str(text)


async def _gitlab_send(
    api_base: str,
    token: str,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    verify: bool = True,
    ok: tuple[int, ...] = (200, 201, 204),
) -> Any:
    """GitLab write call. Raises HTTPException with GitLab's message."""
    url = f"{api_base}{path}"
    try:
        async with httpx.AsyncClient(timeout=60, verify=verify, follow_redirects=True) as http:
            resp = await http.request(method, url, headers=_gl_headers(token), json=json_body)
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach GitLab API: {exc}",
        ) from exc
    if resp.status_code not in ok:
        detail = resp.text[:800] if resp.text else resp.reason_phrase
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY
            if resp.status_code >= 500
            else resp.status_code,
            detail=f"GitLab API error ({resp.status_code}): {detail}",
        )
    if resp.status_code == 204 or not (resp.content or b"").strip():
        return {}
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text[:500]}


def _gitlab_mr_path(owner: str, repo: str, pr_number: int) -> str:
    project = quote(_gitlab_project_path(owner, repo), safe="")
    return f"/projects/{project}/merge_requests/{pr_number}"


async def _gitlab_diff_refs(
    api: str, token: str, owner: str, repo: str, pr_number: int, *, verify: bool
) -> dict[str, str]:
    mr = await _gitlab_get(api, token, _gitlab_mr_path(owner, repo, pr_number), verify=verify)
    refs = mr.get("diff_refs") if isinstance(mr, dict) else None
    if not isinstance(refs, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitLab MR is missing diff_refs, so inline comments cannot be placed.",
        )
    base_sha = refs.get("base_sha") or ""
    start_sha = refs.get("start_sha") or ""
    head_sha = refs.get("head_sha") or ""
    if not (base_sha and start_sha and head_sha):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitLab MR diff_refs are incomplete (need base, start, and head SHA).",
        )
    return {"base_sha": base_sha, "start_sha": start_sha, "head_sha": head_sha}


def _gitlab_position(
    refs: dict[str, str], path: str, line: int, side: str
) -> dict[str, Any]:
    pos: dict[str, Any] = {
        "base_sha": refs["base_sha"],
        "start_sha": refs["start_sha"],
        "head_sha": refs["head_sha"],
        "position_type": "text",
        "old_path": path,
        "new_path": path,
    }
    if (side or "RIGHT").upper() == "LEFT":
        pos["old_line"] = line
    else:
        pos["new_line"] = line
    return pos


def _gitlab_position_line(pos: dict[str, Any]) -> tuple[int, str] | None:
    new_line = pos.get("new_line")
    old_line = pos.get("old_line")
    if new_line:
        return int(new_line), "RIGHT"
    if old_line:
        return int(old_line), "LEFT"
    rng = pos.get("line_range") if isinstance(pos.get("line_range"), dict) else {}
    end = rng.get("end") or rng.get("start") or {}
    if isinstance(end, dict):
        if end.get("new_line"):
            return int(end["new_line"]), "RIGHT"
        if end.get("old_line"):
            return int(end["old_line"]), "LEFT"
    return None


def _gitlab_note_to_comment(
    note: dict[str, Any],
    *,
    discussion_id: str | None = None,
    position: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not (note.get("note") or note.get("body")):
        return None
    pos = position if isinstance(position, dict) else {}
    if not pos and isinstance(note.get("position"), dict):
        pos = note["position"]
    located = _gitlab_position_line(pos) if pos else None
    author = note.get("author") if isinstance(note.get("author"), dict) else {}
    body = note.get("note") or note.get("body") or ""
    comment: dict[str, Any] = {
        "id": note.get("id"),
        "path": (pos.get("new_path") or pos.get("old_path") or "") if pos else "",
        "line": located[0] if located else None,
        "side": located[1] if located else "RIGHT",
        "body": body,
        "user": {"login": author.get("username") or author.get("name") or "unknown"},
        "discussion_id": discussion_id,
        "created_at": note.get("created_at"),
    }
    return comment


def _gitlab_discussions_to_comments(discussions: Any) -> list[dict[str, Any]]:
    """Keep every human note. Replies stay on the first note so the review page can answer them."""
    comments: list[dict[str, Any]] = []
    if not isinstance(discussions, list):
        return comments
    for disc in discussions:
        if not isinstance(disc, dict):
            continue
        notes = [
            note
            for note in (disc.get("notes") or [])
            if isinstance(note, dict) and not note.get("system") and (note.get("body") or note.get("note"))
        ]
        if not notes:
            continue
        disc_id = str(disc.get("id") or "")
        pos: dict[str, Any] = {}
        for note in notes:
            if isinstance(note.get("position"), dict) and note.get("position"):
                pos = note["position"]
                break
        root_id = notes[0].get("id")
        for index, note in enumerate(notes):
            mapped = _gitlab_note_to_comment(note, discussion_id=disc_id, position=pos or None)
            if mapped is None:
                continue
            if index > 0 and root_id is not None:
                mapped["in_reply_to_id"] = root_id
            comments.append(mapped)
    return comments


async def _gitlab_list_drafts(
    api: str, token: str, owner: str, repo: str, pr_number: int, *, verify: bool
) -> list[dict[str, Any]]:
    data = await _gitlab_get(
        api, token, f"{_gitlab_mr_path(owner, repo, pr_number)}/draft_notes", verify=verify
    )
    return [n for n in data if isinstance(n, dict)] if isinstance(data, list) else []


async def _gitlab_create_draft(
    api: str,
    token: str,
    owner: str,
    repo: str,
    pr_number: int,
    *,
    body: str,
    path: str,
    line: int,
    side: str,
    verify: bool,
) -> dict[str, Any]:
    refs = await _gitlab_diff_refs(api, token, owner, repo, pr_number, verify=verify)
    created = await _gitlab_send(
        api,
        token,
        "POST",
        f"{_gitlab_mr_path(owner, repo, pr_number)}/draft_notes",
        json_body={
            "note": body,
            "position": _gitlab_position(refs, path, line, side),
        },
        verify=verify,
    )
    return created if isinstance(created, dict) else {}


async def _gitlab_publish_drafts(
    api: str,
    token: str,
    owner: str,
    repo: str,
    pr_number: int,
    *,
    summary: str,
    event: str,
    verify: bool,
) -> dict[str, Any]:
    """Publish draft notes, then approve or leave a changes-requested note."""
    base = _gitlab_mr_path(owner, repo, pr_number)
    if summary.strip():
        await _gitlab_send(
            api,
            token,
            "POST",
            f"{base}/draft_notes",
            json_body={"note": summary.strip()},
            verify=verify,
        )
    await _gitlab_send(
        api, token, "POST", f"{base}/draft_notes/bulk_publish", json_body={}, verify=verify
    )
    if event == "APPROVE":
        refs = await _gitlab_diff_refs(api, token, owner, repo, pr_number, verify=verify)
        await _gitlab_send(
            api,
            token,
            "POST",
            f"{base}/approve",
            json_body={"sha": refs["head_sha"]},
            verify=verify,
        )
    elif event == "REQUEST_CHANGES" and not summary.strip():
        await _gitlab_send(
            api,
            token,
            "POST",
            f"{base}/notes",
            json_body={"body": "Changes requested."},
            verify=verify,
        )
    return {"status": "ok", "event": event}


def _deep_decode(obj: Any) -> Any:
    """Recursively parse JSON-encoded string values inside dicts/lists."""
    if isinstance(obj, str):
        try:
            parsed = json.loads(obj)
            if isinstance(parsed, (dict, list)):
                return _deep_decode(parsed)
        except (json.JSONDecodeError, TypeError):
            pass
        return obj
    if isinstance(obj, dict):
        return {k: _deep_decode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_decode(item) for item in obj]
    return obj


async def _call_github_tool(
    tool_name: str, args: dict[str, Any], db: AsyncSession, user_id: UUID,
) -> Any:
    full_name = f"{GITHUB_TOOL_PREFIX}{tool_name}"
    try:
        raw = await mcp_client.execute_tool(full_name, args, db, user_id, truncate=False)
    except Exception as exc:
        logger.warning("GitHub MCP tool %s failed: %s", tool_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub tool call failed: {exc}",
        ) from exc
    if isinstance(raw, str) and raw.startswith("Error"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=raw)
    try:
        parsed = json.loads(raw)
        return _deep_decode(parsed)
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
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await require_project_access(db, current.id, project_id)
    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        project = _gitlab_project_path(owner, repo)
        mr = await _gitlab_get(
            api,
            token,
            f"/projects/{quote(project, safe='')}/merge_requests/{pr_number}",
            verify=verify,
        )
        return _normalize_gitlab_mr(mr if isinstance(mr, dict) else {})

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
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await require_project_access(db, current.id, project_id)
    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        project = _gitlab_project_path(owner, repo)
        payload = await _gitlab_get(
            api,
            token,
            f"/projects/{quote(project, safe='')}/merge_requests/{pr_number}/changes",
            verify=verify,
        )
        files = _normalize_gitlab_changes(payload if isinstance(payload, dict) else {})
        return {"files": files}

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
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await require_project_access(db, current.id, project_id)
    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        project = _gitlab_project_path(owner, repo)
        payload = await _gitlab_get(
            api,
            token,
            f"/projects/{quote(project, safe='')}/merge_requests/{pr_number}/changes",
            verify=verify,
        )
        files = _normalize_gitlab_changes(payload if isinstance(payload, dict) else {})
        return {"files": files}

    data = await _call_github_tool(
        "get_pull_request_files",
        {"owner": owner, "repo": repo, "pull_number": pr_number},
        db, current.id,
    )
    return data if isinstance(data, dict) else {"files": data}


_MAX_FILE_CONTENT_CHARS = 1_000_000


def _safe_rel_path(path: str) -> str:
    rel = (path or "").strip().lstrip("/")
    if not rel or rel.startswith("..") or "/../" in f"/{rel}/" or "\\" in rel:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path.")
    return rel


def _read_checkout_file(checkout_root: str, rel: str) -> str | None:
    root = Path(checkout_root).resolve()
    target = (root / rel).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        return None
    try:
        raw = target.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:4096]:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Binary files cannot be expanded in the diff view.",
        )
    text = raw.decode("utf-8", errors="replace")
    if len(text) > _MAX_FILE_CONTENT_CHARS:
        text = text[:_MAX_FILE_CONTENT_CHARS]
    return text


async def _fetch_github_file_at_ref(
    *,
    owner: str,
    repo: str,
    path: str,
    ref: str,
    token: str,
) -> str:
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/contents/{quote(path, safe='/')}",
            headers={**_gh_headers(token), "Accept": "application/vnd.github.raw"},
            params={"ref": ref},
        )
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=f"File not found at head: {path}")
    if resp.status_code != 200:
        # Fall back to JSON contents (base64) when raw Accept is ignored.
        async with httpx.AsyncClient(timeout=30) as http:
            resp2 = await http.get(
                f"{GITHUB_API}/repos/{owner}/{repo}/contents/{quote(path, safe='/')}",
                headers=_gh_headers(token),
                params={"ref": ref},
            )
        if resp2.status_code == 404:
            raise HTTPException(status_code=404, detail=f"File not found at head: {path}")
        if resp2.status_code != 200:
            raise HTTPException(status_code=resp2.status_code, detail=resp2.text[:500])
        payload = resp2.json()
        if isinstance(payload, dict) and payload.get("encoding") == "base64":
            raw = base64.b64decode(payload.get("content") or "")
            if b"\x00" in raw[:4096]:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="Binary files cannot be expanded in the diff view.",
                )
            text = raw.decode("utf-8", errors="replace")
        else:
            text = resp2.text
    else:
        raw = resp.content
        if b"\x00" in raw[:4096]:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Binary files cannot be expanded in the diff view.",
            )
        text = raw.decode("utf-8", errors="replace")
    if len(text) > _MAX_FILE_CONTENT_CHARS:
        text = text[:_MAX_FILE_CONTENT_CHARS]
    return text


async def _fetch_gitlab_file_at_ref(
    *,
    api: str,
    token: str,
    owner: str,
    repo: str,
    path: str,
    ref: str,
    verify: bool,
) -> str:
    project = quote(_gitlab_project_path(owner, repo), safe="")
    file_path = quote(path, safe="")
    text = await _gitlab_get_text(
        api,
        token,
        f"/projects/{project}/repository/files/{file_path}/raw",
        params={"ref": ref},
        verify=verify,
    )
    if "\x00" in text[:4096]:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Binary files cannot be expanded in the diff view.",
        )
    if len(text) > _MAX_FILE_CONTENT_CHARS:
        text = text[:_MAX_FILE_CONTENT_CHARS]
    return text


@router.get("/projects/{project_id}/reviews/pulls/{pr_number}/file-content")
async def get_pull_file_content(
    project_id: UUID,
    pr_number: int,
    path: str = Query(..., description="File path relative to repo root (new/head side)"),
    owner: str = Query(...),
    repo: str = Query(...),
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the PR/MR head version of a file for diff hunk expansion."""
    await require_project_access(db, current.id, project_id)
    rel = _safe_rel_path(path)

    # Prefer local checkout (same path AI review uses).
    try:
        from app.services.pr_checkout_service import ensure_pr_checkout_for_ref

        info = await ensure_pr_checkout_for_ref(
            db,
            project_id=project_id,
            user_id=current.id,
            provider=provider,
            owner=owner,
            repo=repo,
            number=pr_number,
        )
        if info and info.path:
            content = _read_checkout_file(info.path, rel)
            if content is not None:
                return {
                    "path": rel,
                    "content": content,
                    "source": "checkout",
                    "sha": info.sha,
                }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Checkout read for file-content failed; falling back to API")

    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        refs = await _gitlab_diff_refs(api, token, owner, repo, pr_number, verify=verify)
        head_sha = refs.get("head_sha") or ""
        if not head_sha:
            raise HTTPException(status_code=404, detail="GitLab MR has no head SHA.")
        content = await _fetch_gitlab_file_at_ref(
            api=api,
            token=token,
            owner=owner,
            repo=repo,
            path=rel,
            ref=head_sha,
            verify=verify,
        )
        return {"path": rel, "content": content, "source": "gitlab", "sha": head_sha}

    token = await _get_github_token(db, current.id)
    async with httpx.AsyncClient(timeout=30) as http:
        pr_resp = await http.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=_gh_headers(token),
        )
    if pr_resp.status_code != 200:
        raise HTTPException(status_code=pr_resp.status_code, detail=pr_resp.text[:500])
    pr = pr_resp.json()
    head = pr.get("head") if isinstance(pr, dict) else {}
    head_sha = ((head or {}).get("sha") or "")[:40]
    if not head_sha:
        raise HTTPException(status_code=404, detail="GitHub PR has no head SHA.")
    content = await _fetch_github_file_at_ref(
        owner=owner, repo=repo, path=rel, ref=head_sha, token=token
    )
    return {"path": rel, "content": content, "source": "github", "sha": head_sha}


class FlowChartBody(BaseModel):
    path: str
    start_line: int | None = None
    end_line: int | None = None
    patch: str | None = None


@router.post("/projects/{project_id}/reviews/pulls/{pr_number}/flow-chart")
async def get_pull_flow_chart(
    project_id: UUID,
    pr_number: int,
    owner: str = Query(...),
    repo: str = Query(...),
    provider: Provider = Query("github"),
    body: FlowChartBody | None = None,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Build a Mermaid flowchart for a changed function / file region (read-only)."""
    from app.models.project import Project
    from app.services import usage_metering
    from app.services.ai_flow_chart import build_flow_chart

    await require_project_access(db, current.id, project_id)
    if not body or not (body.path or "").strip():
        raise HTTPException(status_code=400, detail="path is required.")
    rel = _safe_rel_path(body.path)

    file_payload = await get_pull_file_content(
        project_id=project_id,
        pr_number=pr_number,
        path=rel,
        owner=owner,
        repo=repo,
        provider=provider,
        current=current,
        db=db,
    )
    content = str(file_payload.get("content") or "")
    patch = body.patch
    if not patch:
        try:
            files_payload = await get_pull_files(
                project_id=project_id,
                pr_number=pr_number,
                owner=owner,
                repo=repo,
                provider=provider,
                current=current,
                db=db,
            )
            raw_files = (
                files_payload.get("files") if isinstance(files_payload, dict) else files_payload
            )
            if isinstance(raw_files, list):
                for f in raw_files:
                    if isinstance(f, dict) and str(f.get("filename") or "") == rel:
                        p = f.get("patch")
                        if isinstance(p, str):
                            patch = p
                        break
        except Exception:
            logger.exception("Could not load patch for flow-chart; continuing without it")

    project = await db.get(Project, project_id)
    token = usage_metering.activate_usage_context(
        user_id=current.id,
        project_id=project_id,
        project_name=project.name if project else None,
        session_id=None,
        kind="ai_flow_chart",
    )
    try:
        result = await build_flow_chart(
            path=rel,
            file_content=content,
            patch=patch,
            start_line=body.start_line,
            end_line=body.end_line,
        )
    finally:
        usage_metering.deactivate_usage_context(token)
    return result


# ── PR Comments ─────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/reviews/pulls/{pr_number}/comments")
async def get_pull_comments(
    project_id: UUID,
    pr_number: int,
    owner: str = Query(...),
    repo: str = Query(...),
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await require_project_access(db, current.id, project_id)
    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        discussions = await _gitlab_get(
            api,
            token,
            f"{_gitlab_mr_path(owner, repo, pr_number)}/discussions",
            params={"per_page": "100"},
            verify=verify,
        )
        return {"comments": _gitlab_discussions_to_comments(discussions)}

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
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create an inline comment and immediately submit it (single comment)."""
    await require_project_access(db, current.id, project_id)
    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        refs = await _gitlab_diff_refs(api, token, owner, repo, pr_number, verify=verify)
        created = await _gitlab_send(
            api,
            token,
            "POST",
            f"{_gitlab_mr_path(owner, repo, pr_number)}/discussions",
            json_body={
                "body": payload.body,
                "position": _gitlab_position(refs, payload.path, payload.line, payload.side),
            },
            verify=verify,
        )
        return created if isinstance(created, dict) else {"status": "ok"}
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
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Check if the user has an existing pending review on this PR."""
    await require_project_access(db, current.id, project_id)
    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        drafts = await _gitlab_list_drafts(api, token, owner, repo, pr_number, verify=verify)
        comments = []
        for note in drafts:
            mapped = _gitlab_note_to_comment(note)
            if mapped:
                comments.append(mapped)
        if not comments:
            return {"pending": False}
        return {
            "pending": True,
            "review_node_id": "gitlab-drafts",
            "review_id": None,
            "comments": comments,
        }
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
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new pending review (or reuse existing) with an inline comment."""
    await require_project_access(db, current.id, project_id)
    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        created = await _gitlab_create_draft(
            api, token, owner, repo, pr_number,
            body=payload.body, path=payload.path, line=payload.line, side=payload.side,
            verify=verify,
        )
        return {
            "review_node_id": "gitlab-drafts",
            "review_id": None,
            "comment_id": created.get("id"),
        }
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
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Add another inline comment to an existing pending review."""
    await require_project_access(db, current.id, project_id)
    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        created = await _gitlab_create_draft(
            api, token, owner, repo, pr_number,
            body=payload.body, path=payload.path, line=payload.line, side=payload.side,
            verify=verify,
        )
        return {"status": "ok", "comment_id": created.get("id")}
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
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Submit a pending review with COMMENT, APPROVE, or REQUEST_CHANGES."""
    await require_project_access(db, current.id, project_id)
    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        return await _gitlab_publish_drafts(
            api, token, owner, repo, pr_number,
            summary=payload.body, event=payload.event, verify=verify,
        )
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
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create and submit a review in one step (no inline comments).

    Uses the REST API: POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews
    with an event, which creates and submits immediately.
    """
    await require_project_access(db, current.id, project_id)
    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        return await _gitlab_publish_drafts(
            api, token, owner, repo, pr_number,
            summary=payload.body, event=payload.event, verify=verify,
        )
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
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Discard (delete) a pending review and all its pending comments.

    Tries REST API first (more reliable), falls back to GraphQL.
    """
    await require_project_access(db, current.id, project_id)
    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        drafts = await _gitlab_list_drafts(api, token, owner, repo, pr_number, verify=verify)
        base = _gitlab_mr_path(owner, repo, pr_number)
        for note in drafts:
            note_id = note.get("id")
            if note_id is None:
                continue
            await _gitlab_send(
                api, token, "DELETE", f"{base}/draft_notes/{note_id}", verify=verify
            )
        return {"status": "discarded"}
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


# ── Edit Comment ─────────────────────────────────────────────────────────


class EditCommentBody(BaseModel):
    body: str


@router.patch(
    "/projects/{project_id}/reviews/pulls/{pr_number}/comments/{comment_id}"
)
async def edit_comment(
    project_id: UUID,
    pr_number: int,
    comment_id: int,
    payload: EditCommentBody,
    owner: str = Query(...),
    repo: str = Query(...),
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update a PR review comment body (only your own)."""
    await require_project_access(db, current.id, project_id)
    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        base = _gitlab_mr_path(owner, repo, pr_number)
        try:
            return await _gitlab_send(
                api, token, "PUT", f"{base}/draft_notes/{comment_id}",
                json_body={"note": payload.body}, verify=verify,
            )
        except HTTPException:
            return await _gitlab_send(
                api, token, "PUT", f"{base}/notes/{comment_id}",
                json_body={"body": payload.body}, verify=verify,
            )
    token = await _get_github_token(db, current.id)

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.patch(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/comments/{comment_id}",
            headers=_gh_headers(token),
            json={"body": payload.body},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


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
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Delete a PR review comment (only your own)."""
    await require_project_access(db, current.id, project_id)
    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        base = _gitlab_mr_path(owner, repo, pr_number)
        try:
            await _gitlab_send(
                api, token, "DELETE", f"{base}/draft_notes/{comment_id}", verify=verify
            )
        except HTTPException:
            await _gitlab_send(
                api, token, "DELETE", f"{base}/notes/{comment_id}", verify=verify
            )
        return {"status": "deleted"}
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
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await require_project_access(db, current.id, project_id)
    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        base = _gitlab_mr_path(owner, repo, pr_number)
        discussions = await _gitlab_get(
            api, token, f"{base}/discussions", params={"per_page": "100"}, verify=verify
        )
        discussion_id = None
        if isinstance(discussions, list):
            for disc in discussions:
                if not isinstance(disc, dict):
                    continue
                for note in disc.get("notes") or []:
                    if isinstance(note, dict) and note.get("id") == comment_id:
                        discussion_id = disc.get("id")
                        break
                if discussion_id:
                    break
        if not discussion_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Could not find that GitLab discussion to reply to.",
            )
        return await _gitlab_send(
            api,
            token,
            "POST",
            f"{base}/discussions/{discussion_id}/notes",
            json_body={"body": payload.body},
            verify=verify,
        )
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


# ── AI review suggestions (draft only — user keeps/discards) ─────────────


class AiReviewBody(BaseModel):
    title: str | None = None


@router.post("/projects/{project_id}/reviews/pulls/{pr_number}/ai-review")
async def run_ai_review(
    project_id: UUID,
    pr_number: int,
    owner: str = Query(...),
    repo: str = Query(...),
    provider: Provider = Query("github"),
    body: AiReviewBody | None = None,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Analyze the PR diff and return draft inline comments.

    Does **not** post to GitHub/GitLab. The client shows drafts so the user
    can keep (add to a pending review) or discard each one.
    """
    from app.models.project import Project
    from app.services import usage_metering
    from app.services.ai_pr_review import suggest_pr_comments
    from app.services.pr_checkout_service import ensure_pr_checkout_for_ref

    await require_project_access(db, current.id, project_id)

    # Reuse the same file-list path as get_pull_files.
    files_payload = await get_pull_files(
        project_id=project_id,
        pr_number=pr_number,
        owner=owner,
        repo=repo,
        provider=provider,
        current=current,
        db=db,
    )
    raw_files = files_payload.get("files") if isinstance(files_payload, dict) else files_payload
    if isinstance(raw_files, str):
        try:
            raw_files = json.loads(raw_files)
        except json.JSONDecodeError:
            raw_files = []
    if not isinstance(raw_files, list):
        raw_files = []
    files = [f for f in raw_files if isinstance(f, dict)]

    checkout_path: str | None = None
    try:
        info = await ensure_pr_checkout_for_ref(
            db,
            project_id=project_id,
            user_id=current.id,
            provider=provider,
            owner=owner,
            repo=repo,
            number=pr_number,
        )
        if info:
            checkout_path = info.path
    except Exception:
        logger.exception("PR checkout for AI review failed; continuing with diff only")

    title = (body.title if body else None) or f"PR #{pr_number}"
    project = await db.get(Project, project_id)
    token = usage_metering.activate_usage_context(
        user_id=current.id,
        project_id=project_id,
        project_name=project.name if project else None,
        session_id=None,
        kind="ai_pr_review",
    )
    try:
        suggestions, used_repo = await suggest_pr_comments(
            title=title,
            files=files,
            checkout_path=checkout_path,
        )
    finally:
        usage_metering.deactivate_usage_context(token)

    return {
        "suggestions": suggestions,
        "count": len(suggestions),
        "used_checkout": bool(checkout_path),
        "used_repo_reads": used_repo,
    }


# ── CI jobs + AI debug (GitLab-first) ────────────────────────────────────


def _normalize_gitlab_job(job: dict[str, Any]) -> dict[str, Any]:
    status = str(job.get("status") or "").lower()
    return {
        "id": str(job.get("id") or ""),
        "name": str(job.get("name") or "job"),
        "stage": str(job.get("stage") or ""),
        "status": status,
        "allow_failure": bool(job.get("allow_failure")),
        "web_url": str(job.get("web_url") or ""),
        "duration": job.get("duration"),
        "finished_at": job.get("finished_at"),
        "pipeline_id": str((job.get("pipeline") or {}).get("id") or job.get("pipeline_id") or ""),
        "failure": status in ("failed", "canceled"),
    }


_ARTIFACT_SKIP_EXT = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg",
    ".so", ".dll", ".dylib", ".a", ".o", ".wasm",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z",
    ".exe", ".bin", ".jar", ".war", ".class",
    ".mp4", ".webm", ".pdf", ".woff", ".woff2", ".ttf",
)
_ARTIFACT_NAME_HINTS = (
    "junit", "test-result", "test_result", "tests", "fail", "error",
    "report", "log", "output", "gotest", "coverage.xml", "surefire",
)
_MAX_ARTIFACT_ZIP_BYTES = 40 * 1024 * 1024
_MAX_ARTIFACT_FILE_BYTES = 400_000
_MAX_ARTIFACT_FILES = 12
_MAX_ARTIFACT_TOTAL_CHARS = 40_000


def _artifact_path_useful(path: str) -> bool:
    lower = path.lower().replace("\\", "/")
    if any(lower.endswith(ext) for ext in _ARTIFACT_SKIP_EXT):
        return False
    base = lower.rsplit("/", 1)[-1]
    if any(h in lower for h in _ARTIFACT_NAME_HINTS):
        return True
    return base.endswith((".xml", ".log", ".txt", ".out", ".err", ".json", ".tap"))


def _decode_artifact_bytes(raw: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


async def _gitlab_fetch_job_artifacts(
    api: str,
    token: str,
    encoded_project: str,
    job_id: str,
    *,
    verify: bool,
    job: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """Download the job artifacts zip and extract useful text files.

    Returns (combined_text, list_of_paths_used).
    """
    job = job or {}
    art_file = job.get("artifacts_file") if isinstance(job.get("artifacts_file"), dict) else {}
    size = art_file.get("size")
    try:
        if size is not None and int(size) > _MAX_ARTIFACT_ZIP_BYTES:
            return (
                f"(artifacts zip too large: {size} bytes; skipped download)",
                [],
            )
    except (TypeError, ValueError):
        pass

    # Some failed jobs keep artifacts; expired/missing return 404.
    url = f"{api}/projects/{encoded_project}/jobs/{job_id}/artifacts"
    try:
        async with httpx.AsyncClient(timeout=90, verify=verify, follow_redirects=True) as http:
            resp = await http.get(url, headers=_gl_headers(token))
    except httpx.ConnectError as exc:
        return (f"(could not download artifacts: {exc})", [])

    if resp.status_code == 404:
        return ("", [])
    if resp.status_code != 200:
        return (f"(artifact download failed: HTTP {resp.status_code})", [])
    if len(resp.content) > _MAX_ARTIFACT_ZIP_BYTES:
        return (f"(artifacts zip too large after download: {len(resp.content)} bytes)", [])

    try:
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
    except zipfile.BadZipFile:
        return ("(job artifacts were not a valid zip)", [])

    # Prefer failure-looking names first.
    names = [n for n in zf.namelist() if not n.endswith("/") and _artifact_path_useful(n)]
    names.sort(
        key=lambda n: (
            0 if re.search(r"junit|fail|error|test.?result", n, re.I) else 1,
            len(n),
            n.lower(),
        )
    )

    chunks: list[str] = []
    used: list[str] = []
    total = 0
    for name in names:
        if len(used) >= _MAX_ARTIFACT_FILES:
            break
        info = zf.getinfo(name)
        if info.file_size <= 0 or info.file_size > _MAX_ARTIFACT_FILE_BYTES:
            continue
        try:
            raw = zf.read(name)
        except Exception:
            continue
        text = _decode_artifact_bytes(raw).strip()
        if not text:
            continue
        # Skip huge minified one-liners.
        if len(text) > 2000 and text.count("\n") < 3 and not name.lower().endswith(".xml"):
            continue
        if total + len(text) > _MAX_ARTIFACT_TOTAL_CHARS:
            remain = _MAX_ARTIFACT_TOTAL_CHARS - total
            if remain < 500:
                break
            text = text[:remain] + "\n…(truncated)"
        chunks.append(f"### artifact: {name}\n{text}")
        used.append(name)
        total += len(text)
        if total >= _MAX_ARTIFACT_TOTAL_CHARS:
            break

    if not used:
        # Zip existed but nothing useful — still note file names for the model.
        listed = [n for n in zf.namelist() if not n.endswith("/")][:40]
        if listed:
            return (
                "Artifacts zip present, but no useful text files matched.\n"
                "Archive contains:\n- " + "\n- ".join(listed),
                [],
            )
        return ("", [])
    return ("\n\n".join(chunks), used)


def _summarize_gitlab_test_report(report: dict[str, Any]) -> str:
    """Flatten failed tests from GitLab pipeline test_report into short text."""
    lines: list[str] = []
    suites = report.get("test_suites") or []
    if not isinstance(suites, list):
        return ""
    for suite in suites:
        if not isinstance(suite, dict):
            continue
        sname = suite.get("name") or "suite"
        cases = suite.get("test_cases") or []
        if not isinstance(cases, list):
            continue
        for case in cases:
            if not isinstance(case, dict):
                continue
            if str(case.get("status") or "").lower() not in ("failed", "error"):
                continue
            cname = case.get("name") or case.get("classname") or "test"
            msg = case.get("system_output") or case.get("message") or ""
            lines.append(f"FAIL {sname} :: {cname}\n{str(msg)[:800]}")
            if len(lines) >= 30:
                break
        if len(lines) >= 30:
            break
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    header = ""
    if summary:
        header = (
            f"totals: total={summary.get('total')} failed={summary.get('failed')} "
            f"error={summary.get('error')} success={summary.get('success')}\n"
        )
    return header + "\n\n".join(lines)


async def _gitlab_list_ci_jobs(
    *,
    token: str,
    api: str,
    verify: bool,
    owner: str,
    repo: str,
    pr_number: int,
) -> dict[str, Any]:
    project = _gitlab_project_path(owner, repo)
    encoded = quote(project, safe="")
    pipelines = await _gitlab_get(
        api,
        token,
        f"/projects/{encoded}/merge_requests/{pr_number}/pipelines",
        params={"per_page": "10"},
        verify=verify,
    )
    if not isinstance(pipelines, list) or not pipelines:
        return {"provider": "gitlab", "pipeline_id": None, "pipeline_status": None, "jobs": []}

    latest = pipelines[0] if isinstance(pipelines[0], dict) else {}
    pipeline_id = latest.get("id")
    pipeline_status = latest.get("status")
    if not pipeline_id:
        return {"provider": "gitlab", "pipeline_id": None, "pipeline_status": None, "jobs": []}

    jobs_raw = await _gitlab_get(
        api,
        token,
        f"/projects/{encoded}/pipelines/{pipeline_id}/jobs",
        params={"per_page": "100"},
        verify=verify,
    )
    jobs = [_normalize_gitlab_job(j) for j in jobs_raw if isinstance(j, dict)] if isinstance(jobs_raw, list) else []
    # Failed / canceled first, then others.
    jobs.sort(key=lambda j: (0 if j.get("failure") else 1, j.get("name") or ""))
    return {
        "provider": "gitlab",
        "pipeline_id": str(pipeline_id),
        "pipeline_status": pipeline_status,
        "pipeline_web_url": latest.get("web_url") or "",
        "jobs": jobs,
        "failed_count": sum(1 for j in jobs if j.get("failure") and not j.get("allow_failure")),
    }


async def _github_list_ci_jobs(
    *,
    db: AsyncSession,
    user_id: UUID,
    owner: str,
    repo: str,
    pr_number: int,
) -> dict[str, Any]:
    """Best-effort check-run list via MCP; logs/artifacts are limited on GitHub."""
    detail = await _call_github_tool(
        "get_pull_request",
        {"owner": owner, "repo": repo, "pull_number": pr_number},
        db,
        user_id,
    )
    if not isinstance(detail, dict):
        detail = {}
    head = detail.get("head") if isinstance(detail.get("head"), dict) else {}
    sha = head.get("sha") or ""
    status_data = await _call_github_tool(
        "get_pull_request_status",
        {"owner": owner, "repo": repo, "pull_number": pr_number},
        db,
        user_id,
    )
    jobs: list[dict[str, Any]] = []
    raw_checks: list[Any] = []
    if isinstance(status_data, dict):
        for key in ("check_runs", "checks", "statuses"):
            val = status_data.get(key)
            if isinstance(val, list):
                raw_checks = val
                break
        if not raw_checks and isinstance(status_data.get("statuses"), list):
            raw_checks = status_data["statuses"]
    elif isinstance(status_data, list):
        raw_checks = status_data

    for item in raw_checks:
        if not isinstance(item, dict):
            continue
        conclusion = str(item.get("conclusion") or item.get("state") or "").lower()
        status = str(item.get("status") or "").lower()
        failed = conclusion in ("failure", "failed", "timed_out", "action_required", "cancelled", "canceled") or status in (
            "failure",
            "error",
        )
        jobs.append(
            {
                "id": str(item.get("id") or item.get("name") or ""),
                "name": str(item.get("name") or item.get("context") or "check"),
                "stage": str(item.get("suite") or ""),
                "status": conclusion or status or "unknown",
                "allow_failure": False,
                "web_url": str(item.get("html_url") or item.get("target_url") or ""),
                "duration": None,
                "finished_at": item.get("completed_at"),
                "pipeline_id": sha,
                "failure": failed,
                "summary": str(item.get("output", {}).get("summary") or item.get("description") or "")
                if isinstance(item.get("output"), dict)
                else str(item.get("description") or ""),
            }
        )
    jobs.sort(key=lambda j: (0 if j.get("failure") else 1, j.get("name") or ""))
    return {
        "provider": "github",
        "pipeline_id": sha or None,
        "pipeline_status": None,
        "pipeline_web_url": "",
        "jobs": jobs,
        "failed_count": sum(1 for j in jobs if j.get("failure")),
    }


@router.get("/projects/{project_id}/reviews/pulls/{pr_number}/ci-jobs")
async def list_ci_jobs(
    project_id: UUID,
    pr_number: int,
    owner: str = Query(...),
    repo: str = Query(...),
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List CI jobs for this PR/MR (failed first)."""
    await require_project_access(db, current.id, project_id)
    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        return await _gitlab_list_ci_jobs(
            token=token,
            api=api,
            verify=verify,
            owner=owner,
            repo=repo,
            pr_number=pr_number,
        )
    return await _github_list_ci_jobs(
        db=db, user_id=current.id, owner=owner, repo=repo, pr_number=pr_number
    )


@router.post("/projects/{project_id}/reviews/pulls/{pr_number}/ci-jobs/{job_id}/debug")
async def debug_ci_job(
    project_id: UUID,
    pr_number: int,
    job_id: str,
    owner: str = Query(...),
    repo: str = Query(...),
    provider: Provider = Query("github"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Fetch job log, test report, and useful artifact files; return AI diagnosis.

    Does not post comments. Client may offer Keep/Discard for suggested_comment.
    """
    from app.models.project import Project
    from app.services import usage_metering
    from app.services.ai_ci_debug import diagnose_ci_failure
    from app.services.pr_checkout_service import ensure_pr_checkout_for_ref

    await require_project_access(db, current.id, project_id)

    job_name = f"job {job_id}"
    job_status = "failed"
    web_url = ""
    log_text = ""
    test_report_text = ""
    artifacts_text = ""
    artifact_files: list[str] = []
    checkout_path: str | None = None
    try:
        info = await ensure_pr_checkout_for_ref(
            db,
            project_id=project_id,
            user_id=current.id,
            provider=provider,
            owner=owner,
            repo=repo,
            number=pr_number,
        )
        if info:
            checkout_path = info.path
    except Exception:
        logger.exception("PR checkout for CI debug failed; continuing without repo tools")

    if provider == "gitlab":
        token, api, verify = await _get_gitlab_config(db, current.id)
        project = _gitlab_project_path(owner, repo)
        encoded = quote(project, safe="")
        try:
            job = await _gitlab_get(api, token, f"/projects/{encoded}/jobs/{job_id}", verify=verify)
        except HTTPException:
            job = {}
        if isinstance(job, dict):
            job_name = str(job.get("name") or job_name)
            job_status = str(job.get("status") or job_status)
            web_url = str(job.get("web_url") or "")
            pipeline_id = (job.get("pipeline") or {}).get("id") if isinstance(job.get("pipeline"), dict) else job.get("pipeline_id")
        else:
            pipeline_id = None

        try:
            log_text = await _gitlab_get_text(
                api, token, f"/projects/{encoded}/jobs/{job_id}/trace", verify=verify
            )
        except HTTPException as exc:
            log_text = f"(could not fetch job trace: {exc.detail})"

        # Prefer last ~800 lines for the model.
        if log_text:
            lines = log_text.splitlines()
            if len(lines) > 800:
                log_text = "\n".join(lines[-800:])

        if pipeline_id:
            try:
                report = await _gitlab_get(
                    api,
                    token,
                    f"/projects/{encoded}/pipelines/{pipeline_id}/test_report",
                    verify=verify,
                )
                if isinstance(report, dict):
                    test_report_text = _summarize_gitlab_test_report(report)
            except HTTPException:
                test_report_text = ""

        # Same files shown under …/jobs/{id}/artifacts/browse — via the artifacts zip API.
        artifacts_text, artifact_files = await _gitlab_fetch_job_artifacts(
            api,
            token,
            encoded,
            str(job_id),
            verify=verify,
            job=job if isinstance(job, dict) else None,
        )
    else:
        # GitHub: use check summary text when we have it; full Actions logs need more work.
        listing = await _github_list_ci_jobs(
            db=db, user_id=current.id, owner=owner, repo=repo, pr_number=pr_number
        )
        match = next((j for j in listing.get("jobs") or [] if str(j.get("id")) == str(job_id)), None)
        if match:
            job_name = str(match.get("name") or job_name)
            job_status = str(match.get("status") or job_status)
            web_url = str(match.get("web_url") or "")
            log_text = str(match.get("summary") or "")
            if not log_text:
                log_text = (
                    f"GitHub check '{job_name}' concluded: {job_status}.\n"
                    f"URL: {web_url or '(none)'}\n"
                    "Full Actions job logs / artifacts are not fetched yet — open the URL for details."
                )

    project = await db.get(Project, project_id)
    usage_token = usage_metering.activate_usage_context(
        user_id=current.id,
        project_id=project_id,
        project_name=project.name if project else None,
        session_id=None,
        kind="ai_ci_debug",
    )
    try:
        diagnosis, used_repo = await diagnose_ci_failure(
            job_name=job_name,
            job_status=job_status,
            log_text=log_text,
            test_report_text=test_report_text,
            artifacts_text=artifacts_text,
            web_url=web_url,
            checkout_path=checkout_path,
        )
    finally:
        usage_metering.deactivate_usage_context(usage_token)

    return {
        "job_id": str(job_id),
        "job_name": job_name,
        "job_status": job_status,
        "web_url": web_url,
        "log_excerpt": (log_text or "")[-4000:],
        "used_test_report": bool(test_report_text.strip()),
        "used_artifacts": artifact_files,
        "artifacts_note": (
            artifacts_text[:500]
            if artifacts_text.startswith("(") or artifacts_text.startswith("Artifacts zip")
            else ""
        ),
        "used_checkout": bool(checkout_path),
        "used_repo_reads": used_repo,
        "diagnosis": diagnosis,
    }
