"""Daily Coach — assemble Today brief from watchlists + integrations."""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.coach import CoachProfile
from app.models.context import SessionLayer, SessionLayerType
from app.models.session import Message, MessageRole, Session as OrbitSession
from app.models.skill import SkillPlugin, UserPluginConfig
from app.models.user import User
from app.services import mcp_client

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")

EMPTY_WATCHLISTS: dict[str, list[Any]] = {
    "jira": [],
    "meetings": [],
    "repos": [],
}

DEFAULT_REMINDER_PREFS: dict[str, Any] = {
    "enabled": True,
    "standup_minutes_before": 15,
    "default_orbit_project_id": None,
}


def _normalize_watchlists(raw: dict[str, Any] | None) -> dict[str, list[Any]]:
    data = raw or {}
    return {
        "jira": list(data.get("jira") or []),
        "meetings": list(data.get("meetings") or []),
        "repos": list(data.get("repos") or []),
    }


def _normalize_reminder_prefs(raw: dict[str, Any] | None) -> dict[str, Any]:
    prefs = dict(DEFAULT_REMINDER_PREFS)
    if raw:
        if "enabled" in raw:
            prefs["enabled"] = bool(raw["enabled"])
        if "standup_minutes_before" in raw:
            try:
                prefs["standup_minutes_before"] = max(0, int(raw["standup_minutes_before"]))
            except (TypeError, ValueError):
                pass
        if "default_orbit_project_id" in raw:
            val = raw.get("default_orbit_project_id")
            prefs["default_orbit_project_id"] = str(val) if val else None
    return prefs


async def get_or_create_profile(db: AsyncSession, user_id: UUID) -> CoachProfile:
    result = await db.execute(select(CoachProfile).where(CoachProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if profile is not None:
        return profile
    profile = CoachProfile(
        user_id=user_id,
        watchlists=dict(EMPTY_WATCHLISTS),
        reminder_prefs=dict(DEFAULT_REMINDER_PREFS),
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


async def get_watchlists(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    profile = await get_or_create_profile(db, user_id)
    return {
        "watchlists": _normalize_watchlists(profile.watchlists),
        "reminder_prefs": _normalize_reminder_prefs(profile.reminder_prefs),
    }


async def put_watchlists(
    db: AsyncSession,
    user_id: UUID,
    *,
    watchlists: dict[str, Any] | None = None,
    reminder_prefs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = await get_or_create_profile(db, user_id)
    if watchlists is not None:
        profile.watchlists = _normalize_watchlists(watchlists)
        flag_modified(profile, "watchlists")
    if reminder_prefs is not None:
        profile.reminder_prefs = _normalize_reminder_prefs(reminder_prefs)
        flag_modified(profile, "reminder_prefs")
    await db.commit()
    await db.refresh(profile)
    return {
        "watchlists": _normalize_watchlists(profile.watchlists),
        "reminder_prefs": _normalize_reminder_prefs(profile.reminder_prefs),
    }


# ── Integration helpers ─────────────────────────────────────────────────


async def _plugin_enabled(db: AsyncSession, user_id: UUID, slug: str) -> bool:
    result = await db.execute(
        select(UserPluginConfig.id)
        .join(SkillPlugin, SkillPlugin.id == UserPluginConfig.plugin_id)
        .where(
            SkillPlugin.slug == slug,
            UserPluginConfig.user_id == user_id,
            UserPluginConfig.enabled,
        )
    )
    return result.scalar_one_or_none() is not None


async def _get_github_token(db: AsyncSession, user_id: UUID) -> str | None:
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
        return None
    return cfg.config_values.get("GITHUB_PERSONAL_ACCESS_TOKEN") or None


async def _get_gitlab_config(
    db: AsyncSession, user_id: UUID
) -> tuple[str, str, bool] | None:
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
        return None
    token = cfg.config_values.get("GITLAB_PERSONAL_ACCESS_TOKEN") or cfg.config_values.get(
        "GITLAB_TOKEN", ""
    )
    if not token:
        return None
    api = (cfg.config_values.get("GITLAB_API_URL") or "https://gitlab.com/api/v4").strip().rstrip("/")
    # Users often paste host-only (gitlab.cee.redhat.com) — httpx needs a scheme.
    if api and "://" not in api:
        api = f"https://{api}"
    if "/api/" not in api:
        api = f"{api}/api/v4"
    raw = cfg.config_values.get("GITLAB_SSL_VERIFY")
    if raw is not None and str(raw).strip() != "":
        verify = str(raw).strip().lower() in ("1", "true", "yes", "on")
    else:
        verify = "gitlab.com" in api.lower()
    return token, api, verify


def _parse_mcp_json(text: str) -> Any:
    if not text or text.startswith("Error"):
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some MCP tools wrap JSON in markdown fences or prose.
        start = text.find("{")
        start_arr = text.find("[")
        if start_arr >= 0 and (start < 0 or start_arr < start):
            start = start_arr
        if start < 0:
            return None
        chunk = text[start:]
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            return None


async def list_jira_projects(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    """Return Jira projects visible to the user via Atlassian integration."""
    if not await _plugin_enabled(db, user_id, "atlassian"):
        return {
            "connected": False,
            "projects": [],
            "error": "Connect Atlassian (Jira) under Integrations to pick projects.",
        }
    raw = await mcp_client.execute_tool(
        "mcp_atlassian__jira_get_all_projects",
        {},
        db,
        user_id,
        truncate=False,
    )
    if not raw or str(raw).startswith("Error"):
        return {
            "connected": True,
            "projects": [],
            "error": (raw or "Could not load Jira projects")[:300],
        }
    parsed = _parse_mcp_json(raw)
    rows: list[Any]
    if isinstance(parsed, list):
        rows = parsed
    elif isinstance(parsed, dict):
        rows = (
            parsed.get("projects")
            or parsed.get("values")
            or parsed.get("data")
            or []
        )
        if not isinstance(rows, list):
            rows = []
    else:
        rows = []

    projects: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (
            row.get("key")
            or row.get("projectKey")
            or row.get("project_key")
            or ""
        )
        key = str(key).strip().upper()
        if not key or key in seen:
            continue
        seen.add(key)
        name = str(row.get("name") or row.get("projectName") or key)
        projects.append({"key": key, "name": name})
    projects.sort(key=lambda p: (p["name"].lower(), p["key"]))
    return {"connected": True, "projects": projects, "error": None}


_DOC_URL_RE = re.compile(
    r"https://docs\.google\.com/document/d/([a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)


async def _get_google_user_config(
    db: AsyncSession, user_id: UUID
) -> UserPluginConfig | None:
    result = await db.execute(
        select(UserPluginConfig)
        .join(SkillPlugin, SkillPlugin.id == UserPluginConfig.plugin_id)
        .where(
            SkillPlugin.slug == "google-drive",
            UserPluginConfig.user_id == user_id,
            UserPluginConfig.enabled,
        )
    )
    return result.scalar_one_or_none()


def _google_token_info(user_config: UserPluginConfig) -> dict[str, Any] | None:
    from app.core.secret_vault import decrypt_value

    cfg = user_config.config_values or {}
    encrypted_creds = cfg.get("oauth_credentials")
    if not encrypted_creds:
        return None
    try:
        data = json.loads(decrypt_value(encrypted_creds))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


async def _google_access_token(
    user_config: UserPluginConfig, *, force_refresh: bool = False
) -> str | None:
    """Return a usable Google access token (optionally force-refresh)."""
    from app.services.mcp_client import _refresh_gdrive_token

    cfg = user_config.config_values or {}
    encrypted_client = cfg.get("oauth_client_config")
    token_info = _google_token_info(user_config)
    if not token_info:
        return None
    access = token_info.get("access_token") or ""
    if force_refresh and encrypted_client and token_info.get("refresh_token"):
        refreshed = await _refresh_gdrive_token(user_config, token_info, encrypted_client)
        if refreshed:
            return refreshed
    return str(access) if access else None


def _notes_from_event(event: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (notes_url, notes_doc_id) from description / attachments."""
    text = " ".join(
        [
            str(event.get("description") or ""),
            str(event.get("location") or ""),
        ]
    )
    m = _DOC_URL_RE.search(text)
    if m:
        return m.group(0), m.group(1)
    for att in event.get("attachments") or []:
        if not isinstance(att, dict):
            continue
        url = att.get("fileUrl") or att.get("title") or ""
        m2 = _DOC_URL_RE.search(str(url))
        if m2:
            return m2.group(0), m2.group(1)
        mime = att.get("mimeType") or ""
        if "document" in mime and att.get("fileId"):
            fid = att["fileId"]
            return f"https://docs.google.com/document/d/{fid}", fid
    return None, None


def _rrule_days(rrule: str) -> list[int] | None:
    """Map RRULE BYDAY to Python weekday ints (Mon=0)."""
    map_day = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
    upper = rrule.upper()
    if "BYDAY=" not in upper:
        if "FREQ=DAILY" in upper:
            return [0, 1, 2, 3, 4, 5, 6]
        if "FREQ=WEEKLY" in upper:
            return None
        return None
    part = upper.split("BYDAY=", 1)[1].split(";", 1)[0]
    days: list[int] = []
    for token in part.split(","):
        token = token.strip()
        # Strip ordinal prefix like 1MO, -1FR
        code = token[-2:] if len(token) >= 2 else token
        if code in map_day:
            days.append(map_day[code])
    return sorted(set(days)) if days else None


def _calendar_api_failure(status_code: int, body: str) -> dict[str, Any]:
    """Map Google Calendar HTTP errors to a short coach response."""
    lower = (body or "").lower()
    needs_reauth = status_code in (401, 403)
    if "access_token_scope_insufficient" in lower or "insufficient authentication scopes" in lower:
        error = "Reconnect Google in Integrations and allow Calendar."
    elif "accessnotconfigured" in lower or "has not been used" in lower or "is disabled" in lower:
        error = "Enable Google Calendar API in Google Cloud Console for your OAuth project."
        needs_reauth = False
    elif status_code == 401:
        error = "Google session expired. Reconnect Google in Integrations."
    elif status_code == 403:
        error = "Calendar access denied. Reconnect Google in Integrations."
    else:
        error = f"Calendar error ({status_code})."
        needs_reauth = False
    return {
        "connected": True,
        "needs_reauth": needs_reauth,
        "meetings": [],
        "error": error,
    }


async def list_calendar_meetings(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    """Upcoming Google Calendar events for the meeting watchlist picker."""
    user_config = await _get_google_user_config(db, user_id)
    if user_config is None or not (user_config.config_values or {}).get("oauth_credentials"):
        return {
            "connected": False,
            "needs_reauth": False,
            "meetings": [],
            "error": "Connect Google in Integrations to pick meetings.",
        }

    token = await _google_access_token(user_config)
    if not token:
        return {
            "connected": False,
            "needs_reauth": True,
            "meetings": [],
            "error": "Google session expired. Reconnect Google in Integrations.",
        }
    # Persist refreshed OAuth tokens if the helper updated them.
    try:
        await db.commit()
    except Exception:
        await db.rollback()

    now = datetime.now(UTC)
    # Include the whole local-ish day (not only "from now"), so Today's filter
    # still sees this morning's meetings after they start.
    day_start = datetime.combine(now.date(), time.min, tzinfo=UTC) - timedelta(hours=14)
    time_min = day_start.isoformat().replace("+00:00", "Z")
    time_max = (now + timedelta(days=14)).isoformat().replace("+00:00", "Z")
    cal_params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 100,
    }

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {token}"},
            params=cal_params,
        )
        if resp.status_code == 401:
            token = await _google_access_token(user_config, force_refresh=True)
            try:
                await db.commit()
            except Exception:
                await db.rollback()
            if token:
                resp = await http.get(
                    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                    headers={"Authorization": f"Bearer {token}"},
                    params=cal_params,
                )
        if resp.status_code != 200:
            logger.warning(
                "Calendar events failed status=%s body=%s",
                resp.status_code,
                (resp.text or "")[:400],
            )
            return _calendar_api_failure(resp.status_code, resp.text or "")
        payload = resp.json()

    def _on_event_local_today(start_dt: datetime) -> bool:
        tz = start_dt.tzinfo or UTC
        return start_dt.astimezone(tz).date() == datetime.now(tz).date()

    # Group occurrences by series; prefer today's instance when picking one row.
    grouped: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for event in payload.get("items") or []:
        if not isinstance(event, dict) or event.get("status") == "cancelled":
            continue
        title = (event.get("summary") or "").strip() or "(No title)"
        start = event.get("start") or {}
        start_raw = start.get("dateTime") or start.get("date")
        if not start_raw:
            continue
        if "T" not in str(start_raw) and start.get("date") and not start.get("dateTime"):
            continue
        try:
            start_dt = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        weekday = start_dt.weekday()
        recurring_id = event.get("recurringEventId") or event.get("id")
        watch_key = str(recurring_id)
        days = [weekday]
        for r in event.get("recurrence") or []:
            parsed_days = _rrule_days(str(r))
            if parsed_days:
                days = parsed_days
                break
        notes_url, notes_doc_id = _notes_from_event(event)
        is_today = _on_event_local_today(start_dt)
        row = {
            "calendar_event_id": watch_key,
            "title": title,
            "start": start_dt.isoformat(),
            "time_local": start_dt.strftime("%H:%M"),
            "days_of_week": days,
            "notes_url": notes_url,
            "notes_doc_id": notes_doc_id,
            "html_link": event.get("htmlLink"),
            "is_today": is_today,
            "label": f"{title} · {start_dt.strftime('%a %H:%M')}",
        }
        grouped.setdefault(watch_key, []).append((start_dt, row))

    meetings: list[dict[str, Any]] = []
    for _key, occurrences in grouped.items():
        today_hits = [pair for pair in occurrences if pair[1].get("is_today")]
        if today_hits:
            _dt, chosen = min(today_hits, key=lambda p: p[0])
        else:
            # Next upcoming (or latest past if all before now)
            future = [pair for pair in occurrences if pair[0] >= now]
            _dt, chosen = min(future or occurrences, key=lambda p: p[0])
        meetings.append(chosen)
    meetings.sort(key=lambda m: m.get("start") or "")

    return {
        "connected": True,
        "needs_reauth": False,
        "meetings": meetings,
        "error": None,
    }


async def _get_jira_credentials(
    db: AsyncSession, user_id: UUID
) -> tuple[str, str, str] | None:
    """Return (base_url, email, api_token) for the user's Atlassian integration."""
    result = await db.execute(
        select(UserPluginConfig)
        .join(SkillPlugin, SkillPlugin.id == UserPluginConfig.plugin_id)
        .where(
            SkillPlugin.slug == "atlassian",
            UserPluginConfig.user_id == user_id,
            UserPluginConfig.enabled,
        )
    )
    cfg = result.scalar_one_or_none()
    if not cfg or not cfg.config_values:
        return None
    base = (cfg.config_values.get("JIRA_URL") or "").strip().rstrip("/")
    email = (cfg.config_values.get("JIRA_USERNAME") or "").strip()
    token = (cfg.config_values.get("JIRA_API_TOKEN") or "").strip()
    if not base or not email or not token:
        return None
    return base, email, token


async def _jira_search_rest(
    db: AsyncSession,
    user_id: UUID,
    jql: str,
    limit: int = 25,
    fields: list[str] | None = None,
) -> list[dict]:
    """Direct Jira REST search — more reliable than MCP stdio for Daily Coach."""
    creds = await _get_jira_credentials(db, user_id)
    if not creds:
        return []
    base, email, token = creds
    fields = list(fields or [
        "summary", "status", "priority", "labels", "components", "assignee", "updated",
    ])
    # Cloud removed /rest/api/3/search — use /search/jql (POST).
    endpoints = (
        ("POST", "/rest/api/3/search/jql"),
        ("POST", "/rest/api/3/search"),
        ("GET", "/rest/api/3/search"),
    )
    async with httpx.AsyncClient(timeout=30) as http:
        for method, path in endpoints:
            if method == "POST":
                resp = await http.post(
                    f"{base}{path}",
                    json={"jql": jql, "maxResults": limit, "fields": fields},
                    auth=(email, token),
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
            else:
                resp = await http.get(
                    f"{base}{path}",
                    params={"jql": jql, "maxResults": limit, "fields": ",".join(fields)},
                    auth=(email, token),
                    headers={"Accept": "application/json"},
                )
            if resp.status_code == 200:
                data = resp.json() or {}
                issues = data.get("issues") if isinstance(data, dict) else None
                return issues if isinstance(issues, list) else []
            logger.warning(
                "Jira REST %s %s failed status=%s body=%s",
                method,
                path,
                resp.status_code,
                (resp.text or "")[:240],
            )
    return []


async def _jira_search_mcp(db: AsyncSession, user_id: UUID, jql: str, limit: int = 25) -> list[dict]:
    raw = await mcp_client.execute_tool(
        "mcp_atlassian__jira_search",
        {"jql": jql, "limit": limit, "fields": "summary,status,priority,assignee,issuetype,updated"},
        db,
        user_id,
        truncate=False,
    )
    if not raw or str(raw).startswith("Error"):
        return []
    parsed = _parse_mcp_json(raw)
    if parsed is None:
        return []
    if isinstance(parsed, dict):
        issues = parsed.get("issues") or parsed.get("results") or []
        return issues if isinstance(issues, list) else []
    if isinstance(parsed, list):
        return parsed
    return []


async def _jira_search(
    db: AsyncSession,
    user_id: UUID,
    jql: str,
    limit: int = 25,
    fields: list[str] | None = None,
) -> list[dict]:
    # REST first — MCP atlassian stdio often dies with "Connection closed".
    issues = await _jira_search_rest(db, user_id, jql, limit=limit, fields=fields)
    if issues:
        return issues
    return await _jira_search_mcp(db, user_id, jql, limit=limit)


def _issue_fields(issue: dict[str, Any], *, browse_base: str | None = None) -> dict[str, Any]:
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else issue
    status = fields.get("status") or {}
    if isinstance(status, dict):
        status_name = status.get("name") or status.get("statusCategory", {}).get("name") or ""
    else:
        status_name = str(status)
    priority = fields.get("priority") or {}
    priority_name = priority.get("name") if isinstance(priority, dict) else str(priority or "")
    labels = [str(x) for x in (fields.get("labels") or []) if x]
    components = [
        str(c.get("name"))
        for c in (fields.get("components") or [])
        if isinstance(c, dict) and c.get("name")
    ]
    key = issue.get("key") or fields.get("key") or ""
    url = issue.get("url")
    if not url and browse_base and key:
        url = f"{browse_base}/browse/{key}"
    if not url:
        url = issue.get("self")
    return {
        "key": key,
        "summary": fields.get("summary") or issue.get("summary") or "",
        "status": status_name,
        "priority": priority_name,
        "labels": labels,
        "components": components,
        "url": url,
        "updated": fields.get("updated") or issue.get("updated"),
        "fields": fields,
    }


async def _fetch_jira_issues(
    db: AsyncSession,
    user_id: UUID,
    jira_items: list[dict[str, Any]],
    extra_fields: list[str] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return (issues, error_message)."""
    if not jira_items:
        return [], None
    if not await _plugin_enabled(db, user_id, "atlassian"):
        return [], "Connect Atlassian under Integrations to load Jira tickets."
    creds = await _get_jira_credentials(db, user_id)
    browse_base = creds[0] if creds else None
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    last_error: str | None = None
    for item in jira_items:
        key = (item.get("project_key") or "").strip().upper()
        if not key:
            continue
        jql = (
            f'project = "{key}" AND assignee = currentUser() '
            "AND statusCategory != Done ORDER BY priority DESC, updated DESC"
        )
        try:
            issues = await _jira_search(
                db, user_id, jql, limit=20, fields=_jira_field_list(extra_fields)
            )
        except Exception as exc:
            logger.exception("Jira search failed for project %s", key)
            last_error = f"Jira search failed for {key}: {exc}"
            continue
        if not issues:
            last_error = (
                f"No open issues found for {key} (or Jira could not be reached). "
                "Check the project key and Atlassian credentials."
            )
            continue
        for issue in issues:
            normalized = _issue_fields(issue, browse_base=browse_base)
            ik = normalized["key"]
            if not ik or ik in seen:
                continue
            seen.add(ik)
            normalized["project_key"] = key
            normalized["orbit_project_id"] = item.get("orbit_project_id")
            out.append(normalized)
    if out:
        return out, None
    return out, last_error


def _jira_field_list(extra: list[str] | None) -> list[str]:
    base = ["summary", "status", "priority", "labels", "components", "assignee", "updated"]
    for fid in extra or []:
        if fid and fid not in base:
            base.append(fid)
    return base


async def _github_me(token: str) -> str | None:
    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.get(f"{GITHUB_API}/user", headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
    if resp.status_code != 200:
        return None
    return (resp.json() or {}).get("login")


async def _github_list_pulls(token: str, owner: str, repo: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params={"state": "open", "per_page": 30},
        )
    if resp.status_code != 200:
        logger.warning("GitHub list pulls failed %s/%s: %s", owner, repo, resp.status_code)
        return []
    data = resp.json()
    return data if isinstance(data, list) else []


async def _github_pr_reviews(token: str, owner: str, repo: str, number: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}/reviews",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if resp.status_code != 200:
        return []
    data = resp.json()
    return data if isinstance(data, list) else []


async def _github_combined_status(
    token: str, owner: str, repo: str, ref: str
) -> str | None:
    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/commits/{ref}/status",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if resp.status_code != 200:
        return None
    return (resp.json() or {}).get("state")


async def _gitlab_me(api: str, token: str, verify: bool) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=20, verify=verify) as http:
        resp = await http.get(
            f"{api}/user",
            headers={"Authorization": f"Bearer {token}", "PRIVATE-TOKEN": token},
        )
    if resp.status_code != 200:
        return None
    data = resp.json()
    return data if isinstance(data, dict) else None


def _ci_from_pipeline(pipeline: Any) -> tuple[str | None, str | None]:
    if not isinstance(pipeline, dict):
        return None, None
    status = (pipeline.get("status") or "").lower()
    pipe_id = pipeline.get("id")
    token = str(pipe_id) if pipe_id else status
    if status in ("failed", "canceled"):
        return "failure", token
    if status == "success":
        return "success", token
    if status in ("running", "pending", "created"):
        return "pending", token
    return None, None


async def _gitlab_head_pipeline(
    api: str, token: str, verify: bool, project_path: str, iid: int
) -> dict[str, Any]:
    """One MR read. The open-MR list often omits pipeline status."""
    async with httpx.AsyncClient(timeout=30, verify=verify) as http:
        resp = await http.get(
            f"{api}/projects/{quote(project_path, safe='')}/merge_requests/{iid}",
            headers={"Authorization": f"Bearer {token}", "PRIVATE-TOKEN": token},
        )
    if resp.status_code != 200:
        return {}
    data = resp.json()
    if not isinstance(data, dict):
        return {}
    pipe = data.get("head_pipeline") or data.get("pipeline") or {}
    return pipe if isinstance(pipe, dict) else {}


async def _gitlab_list_mrs(
    api: str, token: str, verify: bool, project_path: str
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30, verify=verify) as http:
        resp = await http.get(
            f"{api}/projects/{quote(project_path, safe='')}/merge_requests",
            headers={"Authorization": f"Bearer {token}", "PRIVATE-TOKEN": token},
            params={"state": "opened", "per_page": 30},
        )
    if resp.status_code != 200:
        logger.warning("GitLab list MRs failed %s: %s", project_path, resp.status_code)
        return []
    data = resp.json()
    return data if isinstance(data, list) else []


def _extract_jira_keys(*texts: str | None) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        for m in JIRA_KEY_RE.finditer(text):
            key = m.group(1)
            if key not in seen:
                seen.add(key)
                found.append(key)
    return found


def _mr_next_action(
    *,
    is_author: bool,
    draft: bool,
    ci_state: str | None,
    mergeable: bool | None,
    review_decision: str | None,
    changes_requested: bool,
    reviewers_assigned: bool = False,
) -> str:
    if not is_author:
        return "Review this MR and leave comments or approve"
    if draft:
        return "Mark ready for review when the change is solid"
    if ci_state in ("failure", "error"):
        return "Fix failing CI checks"
    if changes_requested or review_decision == "CHANGES_REQUESTED":
        return "Address review feedback and re-request review"
    if mergeable is False:
        return "Resolve merge conflicts / rebase"
    if review_decision == "APPROVED":
        return "Merge when ready (checks look good)"
    if reviewers_assigned:
        return "Waiting on reviewers"
    if ci_state == "success":
        return "Ask for review. CI is green and nobody is assigned yet."
    return "Ask for review. Nobody is assigned yet."


async def _fetch_repo_mrs(
    db: AsyncSession,
    user_id: UUID,
    repo_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (my_mrs, reviews_waiting)."""
    my_mrs: list[dict[str, Any]] = []
    reviews_waiting: list[dict[str, Any]] = []
    if not repo_items:
        return my_mrs, reviews_waiting

    has_github = any((item.get("provider") or "github").lower() == "github" for item in repo_items)
    has_gitlab = any((item.get("provider") or "").lower() == "gitlab" for item in repo_items)

    gh_token = await _get_github_token(db, user_id) if has_github else None
    gh_login = None
    if gh_token:
        try:
            gh_login = await _github_me(gh_token)
        except Exception as exc:
            logger.warning("GitHub identity lookup failed: %s", exc)

    gl_cfg = await _get_gitlab_config(db, user_id) if has_gitlab else None
    gl_user = None
    if gl_cfg:
        try:
            token, api, verify = gl_cfg
            gl_user = await _gitlab_me(api, token, verify)
        except Exception as exc:
            logger.warning("GitLab identity lookup failed: %s", exc)
    gl_username = (gl_user or {}).get("username") if gl_user else None
    gl_id = (gl_user or {}).get("id") if gl_user else None

    for item in repo_items:
        provider = (item.get("provider") or "github").lower()
        owner = (item.get("owner") or "").strip()
        repo = (item.get("repo") or "").strip()
        if not owner or not repo:
            continue
        orbit_project_id = item.get("orbit_project_id")
        label = item.get("label") or f"{owner}/{repo}"

        if provider == "github" and gh_token:
            pulls = await _github_list_pulls(gh_token, owner, repo)
            for pr in pulls:
                number = pr.get("number")
                if number is None:
                    continue
                author = ((pr.get("user") or {}) if isinstance(pr.get("user"), dict) else {}).get(
                    "login"
                )
                is_author = bool(gh_login and author and author.lower() == gh_login.lower())
                head_sha = ((pr.get("head") or {}) if isinstance(pr.get("head"), dict) else {}).get(
                    "sha"
                )
                ci_state = (
                    await _github_combined_status(gh_token, owner, repo, head_sha)
                    if head_sha
                    else None
                )
                reviews = await _github_pr_reviews(gh_token, owner, repo, int(number))
                changes_requested = any(
                    (r.get("state") or "").upper() == "CHANGES_REQUESTED" for r in reviews
                )
                requested = pr.get("requested_reviewers") or []
                am_reviewer = False
                if gh_login:
                    am_reviewer = any(
                        isinstance(r, dict) and (r.get("login") or "").lower() == gh_login.lower()
                        for r in requested
                    )
                    if not am_reviewer:
                        # Also treat prior review participation as waiting if not author
                        am_reviewer = any(
                            isinstance(r, dict)
                            and ((r.get("user") or {}).get("login") or "").lower()
                            == gh_login.lower()
                            for r in reviews
                        ) and not is_author

                title = pr.get("title") or f"PR #{number}"
                head_ref = ((pr.get("head") or {}) if isinstance(pr.get("head"), dict) else {}).get(
                    "ref"
                )
                jira_keys = _extract_jira_keys(title, pr.get("body") or "", head_ref)
                mergeable = pr.get("mergeable")
                draft = bool(pr.get("draft"))
                entry = {
                    "provider": "github",
                    "owner": owner,
                    "repo": repo,
                    "number": int(number),
                    "title": title,
                    "url": pr.get("html_url"),
                    "draft": draft,
                    "ci_state": ci_state,
                    "mergeable": mergeable,
                    "changes_requested": changes_requested,
                    "jira_keys": jira_keys,
                    "orbit_project_id": orbit_project_id,
                    "repo_label": label,
                    "author": author,
                    "is_author": is_author,
                    "source_branch": head_ref,
                }
                entry["reviewers"] = [
                    r.get("login")
                    for r in requested
                    if isinstance(r, dict) and r.get("login")
                ]
                entry["next_action"] = _mr_next_action(
                    is_author=is_author,
                    draft=draft,
                    ci_state=ci_state,
                    mergeable=mergeable if isinstance(mergeable, bool) else None,
                    review_decision=None,
                    changes_requested=changes_requested,
                    reviewers_assigned=bool(entry["reviewers"]),
                )
                if is_author:
                    my_mrs.append(entry)
                elif am_reviewer or (gh_login and not is_author and requested):
                    # If review was explicitly requested from me
                    if am_reviewer or any(
                        isinstance(r, dict) and (r.get("login") or "").lower() == gh_login.lower()
                        for r in requested
                    ):
                        reviews_waiting.append(entry)

        elif provider == "gitlab" and gl_cfg:
            token, api, verify = gl_cfg
            project_path = f"{owner}/{repo}"
            mrs = await _gitlab_list_mrs(api, token, verify, project_path)
            for mr in mrs:
                number = mr.get("iid")
                if number is None:
                    continue
                author_obj = mr.get("author") if isinstance(mr.get("author"), dict) else {}
                author = author_obj.get("username")
                is_author = bool(
                    (gl_username and author and author.lower() == gl_username.lower())
                    or (gl_id and author_obj.get("id") == gl_id)
                )
                reviewers = mr.get("reviewers") or []
                am_reviewer = False
                if gl_username or gl_id:
                    for r in reviewers:
                        if not isinstance(r, dict):
                            continue
                        if gl_username and (r.get("username") or "").lower() == gl_username.lower():
                            am_reviewer = True
                        if gl_id and r.get("id") == gl_id:
                            am_reviewer = True
                title = mr.get("title") or f"MR !{number}"
                jira_keys = _extract_jira_keys(title, mr.get("description") or "", mr.get("source_branch"))
                draft = bool(mr.get("draft") or mr.get("work_in_progress"))
                merge_status = mr.get("merge_status")
                mergeable = True if merge_status == "can_be_merged" else (
                    False if merge_status == "cannot_be_merged" else None
                )
                pipeline = mr.get("head_pipeline") or mr.get("pipeline") or {}
                ci_state, pipeline_id = _ci_from_pipeline(pipeline)
                if ci_state is None and is_author:
                    pipeline = await _gitlab_head_pipeline(api, token, verify, project_path, int(number))
                    ci_state, pipeline_id = _ci_from_pipeline(pipeline)
                entry = {
                    "provider": "gitlab",
                    "owner": owner,
                    "repo": repo,
                    "number": int(number),
                    "title": title,
                    "url": mr.get("web_url"),
                    "draft": draft,
                    "ci_state": ci_state,
                    "pipeline_id": pipeline_id,
                    "mergeable": mergeable,
                    "changes_requested": False,
                    "jira_keys": jira_keys,
                    "orbit_project_id": orbit_project_id,
                    "repo_label": label,
                    "author": author,
                    "is_author": is_author,
                    "source_branch": mr.get("source_branch"),
                }
                entry["reviewers"] = [
                    r.get("username")
                    for r in reviewers
                    if isinstance(r, dict) and r.get("username")
                ]
                entry["next_action"] = _mr_next_action(
                    is_author=is_author,
                    draft=draft,
                    ci_state=ci_state,
                    mergeable=mergeable,
                    review_decision=None,
                    changes_requested=False,
                    reviewers_assigned=bool(entry["reviewers"]),
                )
                if is_author:
                    my_mrs.append(entry)
                elif am_reviewer:
                    reviews_waiting.append(entry)

    return my_mrs, reviews_waiting


def _manual_meeting_occurs_today(meeting: dict[str, Any], today: date) -> bool:
    """Fallback for meetings added without a calendar id (manual watch)."""
    days = meeting.get("days_of_week")
    if not days:
        return today.weekday() < 5
    try:
        return today.weekday() in {int(d) for d in days}
    except (TypeError, ValueError):
        return today.weekday() < 5


async def _todays_calendar_occurrences(
    db: AsyncSession, user_id: UUID, today: date
) -> list[dict[str, Any]]:
    """Timed primary-calendar events that start on ``today`` (UTC date window)."""
    user_config = await _get_google_user_config(db, user_id)
    if user_config is None or not (user_config.config_values or {}).get("oauth_credentials"):
        return []
    token = await _google_access_token(user_config)
    if not token:
        return []

    start = datetime.combine(today, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    params = {
        "timeMin": start.isoformat().replace("+00:00", "Z"),
        "timeMax": end.isoformat().replace("+00:00", "Z"),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 50,
    }
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        if resp.status_code == 401:
            token = await _google_access_token(user_config, force_refresh=True)
            try:
                await db.commit()
            except Exception:
                await db.rollback()
            if not token:
                return []
            resp = await http.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
        if resp.status_code != 200:
            logger.warning(
                "Today calendar occurrences failed status=%s body=%s",
                resp.status_code,
                (resp.text or "")[:300],
            )
            return []
        items = resp.json().get("items") or []

    out: list[dict[str, Any]] = []
    for event in items:
        if not isinstance(event, dict) or event.get("status") == "cancelled":
            continue
        start_obj = event.get("start") or {}
        start_raw = start_obj.get("dateTime") or start_obj.get("date")
        if not start_raw or ("T" not in str(start_raw) and start_obj.get("date")):
            continue
        try:
            start_dt = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        out.append(
            {
                "id": event.get("id"),
                "recurring_event_id": event.get("recurringEventId"),
                "title": (event.get("summary") or "").strip(),
                "start": start_dt,
                "time_local": start_dt.strftime("%H:%M"),
            }
        )
    return out


def _watched_meeting_occurrence_today(
    meeting: dict[str, Any],
    today: date,
    todays_events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return today's calendar occurrence for a watched meeting, if any.

    Calendar-linked watches follow the real series (daily, weekly, biweekly, moved).
    Manual watches fall back to days_of_week.
    """
    cal_id = (meeting.get("calendar_event_id") or "").strip()
    if cal_id:
        for ev in todays_events:
            if ev.get("recurring_event_id") == cal_id or ev.get("id") == cal_id:
                return ev
            # Title fallback if series id changed but name matches uniquely today
        title = (meeting.get("title") or "").strip().lower()
        if title:
            title_hits = [
                ev
                for ev in todays_events
                if (ev.get("title") or "").strip().lower() == title
            ]
            if len(title_hits) == 1:
                return title_hits[0]
        return None

    if _manual_meeting_occurs_today(meeting, today):
        return {
            "id": None,
            "recurring_event_id": None,
            "title": meeting.get("title"),
            "start": None,
            "time_local": meeting.get("time_local"),
        }
    return None


def _parse_time_local(value: str | None) -> time | None:
    if not value:
        return None
    try:
        parts = value.strip().split(":")
        return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except (TypeError, ValueError, IndexError):
        return None


async def _read_notes_snippet(
    db: AsyncSession, user_id: UUID, meeting: dict[str, Any]
) -> str | None:
    doc_id = meeting.get("notes_doc_id")
    if not doc_id:
        url = meeting.get("notes_url") or ""
        # Google Doc URL: .../document/d/<id>/...
        m = re.search(r"/document/d/([a-zA-Z0-9_-]+)", url)
        if m:
            doc_id = m.group(1)
    if not doc_id:
        return None
    if not await _plugin_enabled(db, user_id, "google-drive"):
        return None
    raw = await mcp_client.execute_tool(
        "mcp_google-drive__read_file",
        {"file_id": doc_id},
        db,
        user_id,
        truncate=False,
    )
    if not raw or raw.startswith("Error"):
        return None
    return raw[:4000]


def _build_standup_draft(
    *,
    meeting_title: str,
    notes_snippet: str | None,
    jira_issues: list[dict[str, Any]],
    my_mrs: list[dict[str, Any]],
) -> str:
    # Infer format from notes if present; else classic standup.
    format_hint = "Yesterday / Today / Blockers"
    if notes_snippet:
        lower = notes_snippet.lower()
        if "what i did" in lower or "done:" in lower:
            format_hint = "custom from notes"
        elif "wins" in lower and "plans" in lower:
            format_hint = "Wins / Plans / Blockers"

    in_progress = [
        i for i in jira_issues if "progress" in (i.get("status") or "").lower()
    ] or jira_issues[:5]
    done_ish = [
        i
        for i in jira_issues
        if any(x in (i.get("status") or "").lower() for x in ("review", "done", "qa"))
    ][:5]
    blocked_mrs = [
        m
        for m in my_mrs
        if m.get("ci_state") in ("failure", "error") or m.get("changes_requested")
    ][:3]

    lines: list[str] = [f"Standup — {meeting_title}", ""]
    if format_hint.startswith("Wins"):
        lines.append("Wins:")
        for i in done_ish or in_progress[:2]:
            lines.append(f"- {i['key']}: {i['summary']}")
        lines.append("")
        lines.append("Plans:")
        for i in in_progress[:4]:
            lines.append(f"- {i['key']}: {i['summary']}")
        lines.append("")
        lines.append("Blockers:")
        if blocked_mrs:
            for m in blocked_mrs:
                lines.append(f"- {m['repo_label']}#{m['number']}: {m['next_action']}")
        else:
            lines.append("- None")
    else:
        lines.append("Yesterday:")
        for i in (done_ish or in_progress)[:4]:
            lines.append(f"- {i['key']}: {i['summary']} ({i.get('status') or '—'})")
        if not done_ish and not in_progress:
            lines.append("- (add what you shipped)")
        lines.append("")
        lines.append("Today:")
        for i in in_progress[:4]:
            lines.append(f"- {i['key']}: {i['summary']}")
        for m in my_mrs[:3]:
            if m.get("next_action"):
                lines.append(f"- {m['repo_label']}#{m['number']}: {m['next_action']}")
        lines.append("")
        lines.append("Blockers:")
        if blocked_mrs:
            for m in blocked_mrs:
                lines.append(f"- {m['repo_label']}#{m['number']}: {m['next_action']}")
        else:
            lines.append("- None")

    if notes_snippet:
        lines.append("")
        lines.append("(Draft shaped using notes linked to this meeting — edit before posting.)")
    return "\n".join(lines)


def _rank_focus_items(
    *,
    jira_issues: list[dict[str, Any]],
    my_mrs: list[dict[str, Any]],
    reviews_waiting: list[dict[str, Any]],
    standups: list[dict[str, Any]],
    now: datetime,
    reminder_minutes: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for s in standups:
        score = 40
        why = "Watched standup meeting today"
        minutes_until = s.get("minutes_until")
        if isinstance(minutes_until, (int, float)) and 0 <= minutes_until <= reminder_minutes:
            score = 100
            why = f"Standup in {int(minutes_until)} min — copy your draft"
        elif isinstance(minutes_until, (int, float)) and minutes_until < 0:
            score = 55
            why = "Standup time passed — post update if you have not"
        items.append({
            "id": f"standup:{s['meeting_id']}",
            "lane": "Standup",
            "title": s.get("title") or "Standup",
            "why": why,
            "score": score,
            "cta": "copy_standup",
            "meeting_id": s["meeting_id"],
            "draft": s.get("draft"),
        })

    for m in my_mrs:
        score = 50
        why = m.get("next_action") or "Open MR needs attention"
        if m.get("ci_state") in ("failure", "error"):
            score = 95
            why = "CI failing — unblock merge path"
        elif m.get("changes_requested"):
            score = 88
            why = "Changes requested — address feedback"
        elif m.get("mergeable") is False:
            score = 80
            why = "Merge conflicts — rebase/resolve"
        elif m.get("draft"):
            score = 45
        jira = ", ".join(m.get("jira_keys") or []) or None
        items.append({
            "id": f"my_mr:{m['provider']}:{m['owner']}/{m['repo']}#{m['number']}",
            "lane": "My MR",
            "title": f"{m['repo_label']}#{m['number']}: {m['title']}",
            "why": why + (f" · linked {jira}" if jira else ""),
            "score": score,
            "cta": "focus",
            "mr": m,
        })

    for m in reviews_waiting:
        items.append({
            "id": f"review:{m['provider']}:{m['owner']}/{m['repo']}#{m['number']}",
            "lane": "Review",
            "title": f"{m['repo_label']}#{m['number']}: {m['title']}",
            "why": "Review requested — unblock a teammate",
            "score": 70,
            "cta": "open_review",
            "mr": m,
        })

    for issue in jira_issues:
        status = (issue.get("status") or "").lower()
        score = 35
        why = f"Jira · {issue.get('status') or 'open'}"
        if "progress" in status:
            score = 60
            why = "In progress — keep moving or close today"
        elif "block" in status:
            score = 75
            why = "Blocked ticket — escalate or unblock"
        # Boost if linked to a failing MR
        linked = False
        for m in my_mrs:
            if issue["key"] in (m.get("jira_keys") or []):
                linked = True
                if m.get("ci_state") in ("failure", "error"):
                    score = max(score, 90)
                    why = f"Linked to failing MR {m['repo_label']}#{m['number']}"
                else:
                    score = max(score, 65)
                    why = f"Linked to MR {m['repo_label']}#{m['number']}"
                break
        items.append({
            "id": f"jira:{issue['key']}",
            "lane": "Jira",
            "title": f"{issue['key']}: {issue['summary']}",
            "why": why,
            "score": score,
            "cta": "focus",
            "issue": issue,
            "linked_mr": linked,
        })

    items.sort(key=lambda x: (-x["score"], x["title"]))
    # Dedupe-ish: keep top 5
    return items[:5]


async def assemble_today(db: AsyncSession, user: User, *, refresh: bool = False) -> dict[str, Any]:
    # Saved board. External calls happen once a day, or when Refresh is pressed.
    from app.services.coach_runtime import build_today

    return await build_today(db, user, refresh=refresh)


async def regenerate_standup_draft(
    db: AsyncSession, user: User, meeting_id: str
) -> dict[str, Any]:
    """Return the saved post-meeting note. Does not read the doc again."""
    from app.services.coach_runtime import saved_standup

    return await saved_standup(db, user, meeting_id)


async def create_focus_session(
    db: AsyncSession,
    user: User,
    *,
    orbit_project_id: UUID,
    issue_key: str | None = None,
    issue_url: str | None = None,
    issue_summary: str | None = None,
    mr: dict[str, Any] | None = None,
    brief: str | None = None,
) -> dict[str, Any]:
    title_bits = []
    if issue_key:
        title_bits.append(issue_key)
    if mr:
        title_bits.append(f"{mr.get('owner')}/{mr.get('repo')}#{mr.get('number')}")
    title = "Focus: " + (" · ".join(title_bits) if title_bits else "Today")

    session = OrbitSession(
        title=title[:512],
        project_id=orbit_project_id,
        user_id=user.id,
        claude_model="auto",
        tags=["coach-focus"],
    )
    db.add(session)
    await db.flush()

    if issue_key:
        db.add(
            SessionLayer(
                session_id=session.id,
                type=SessionLayerType.jira_ticket,
                label=f"{issue_key}: {issue_summary or ''}".strip(": ").rstrip(": ").strip()
                or issue_key,
                reference_url=issue_url,
                cached_content={"key": issue_key, "summary": issue_summary, "source": "coach"},
                token_count=0,
            )
        )

    mr_layer: SessionLayer | None = None
    if mr:
        url = mr.get("url")
        if not url:
            if mr.get("provider") == "gitlab":
                url = (
                    f"https://gitlab.com/{mr['owner']}/{mr['repo']}"
                    f"/-/merge_requests/{mr['number']}"
                )
            else:
                url = f"https://github.com/{mr['owner']}/{mr['repo']}/pull/{mr['number']}"
        cached: dict[str, Any] = {
            "provider": mr.get("provider"),
            "owner": mr.get("owner"),
            "repo": mr.get("repo"),
            "number": mr.get("number"),
            "source": "coach",
        }
        if url:
            cached["pr_checkout_status"] = "fetching"
            cached["pr_checkout_progress"] = 0
            cached["pr_checkout_stage"] = "Fetching MR"
        mr_layer = SessionLayer(
            session_id=session.id,
            type=SessionLayerType.pull_request,
            label=(
                f"{mr.get('repo_label') or mr.get('repo')}#{mr['number']}: "
                f"{mr.get('title') or ''}"
            ).strip(),
            reference_url=url,
            cached_content=cached,
            token_count=0,
        )
        db.add(mr_layer)

    seed = brief or _default_focus_brief(issue_key, issue_summary, mr)
    db.add(
        Message(
            session_id=session.id,
            role=MessageRole.assistant,
            content=seed,
            metadata_={"source": "coach_focus"},
        )
    )
    await db.commit()
    await db.refresh(session)
    return {
        "session_id": str(session.id),
        "project_id": str(orbit_project_id),
        "title": session.title,
        "url": f"/projects/{orbit_project_id}/sessions/{session.id}",
        "pr_layer_id": str(mr_layer.id) if mr_layer and mr_layer.reference_url else None,
    }


def _default_focus_brief(
    issue_key: str | None,
    issue_summary: str | None,
    mr: dict[str, Any] | None,
) -> str:
    lines = ["Focus session started from Daily Coach.", ""]
    if issue_key:
        lines.append(f"**Ticket:** {issue_key}" + (f" — {issue_summary}" if issue_summary else ""))
    if mr:
        lines.append(
            f"**MR/PR:** {mr.get('owner')}/{mr.get('repo')}#{mr.get('number')} — {mr.get('title') or ''}"
        )
        if mr.get("next_action"):
            lines.append(f"**Suggested next step:** {mr['next_action']}")
        if mr.get("ci_state"):
            lines.append(f"**CI:** {mr['ci_state']}")
    lines.append("")
    lines.append("Tell me what you want to do next, or ask for a plan on this work.")
    return "\n".join(lines)
