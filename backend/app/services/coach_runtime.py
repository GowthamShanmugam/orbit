"""Saved Today board.

Page loads read this state. Jira, GitLab, and the calendar are fetched once
per local day (or when watchlists change). The standup doc is read once,
one hour after the watched meeting. Comments and CI arrive as webhooks and
update a single row per MR or ticket.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.coach import CoachProfile
from app.models.user import User
from app.services import coach_service
from app.services.coach_service import (
    JIRA_KEY_RE,
    _fetch_jira_issues,
    _fetch_repo_mrs,
    _get_gitlab_config,
    _get_google_user_config,
    _get_jira_credentials,
    _gitlab_me,
    _google_access_token,
    _normalize_reminder_prefs,
    _normalize_watchlists,
    _plugin_enabled,
    _todays_calendar_occurrences,
    _watched_meeting_occurrence_today,
    get_or_create_profile,
)

logger = logging.getLogger(__name__)

HAIKU = "claude-haiku-4-5-20251001"


def _haiku_model() -> str:
    from app.services.ai_service import _resolve_model_for_provider

    return _resolve_model_for_provider(HAIKU)
_MR_NUM_RE = re.compile(r"!(?P<n>\d+)\b|#(?P<h>\d+)\b")


def _local_today() -> str:
    return datetime.now().astimezone().date().isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _watch_fp(watchlists: dict[str, Any]) -> str:
    raw = json.dumps(watchlists, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _public_issue(issue: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in issue.items() if k != "fields"}


def _empty_state() -> dict[str, Any]:
    return {
        "snapshot_on": None,
        "watch_fp": None,
        "occurrences": [],
        "standup_reads": {},
        "doc_tab": {},
        "my_mrs": [],
        "reviews_waiting": [],
        "jira_issues": [],
        "attention": {},
        "seen_events": {},
        "me": {},
        "jira_field_ids": {},
        "notices": [],
    }


def _state_of(profile: CoachProfile) -> dict[str, Any]:
    state = dict(profile.state or {})
    base = _empty_state()
    base.update(state)
    base["attention"] = dict(base.get("attention") or {})
    base["seen_events"] = dict(base.get("seen_events") or {})
    base["standup_reads"] = dict(base.get("standup_reads") or {})
    base["me"] = dict(base.get("me") or {})
    base["jira_field_ids"] = dict(base.get("jira_field_ids") or {})
    base["doc_tab"] = dict(base.get("doc_tab") or {})
    return base


async def _save(db: AsyncSession, profile: CoachProfile, state: dict[str, Any]) -> None:
    profile.state = state
    flag_modified(profile, "state")
    await db.commit()
    await db.refresh(profile)


def _repo_full(item: dict[str, Any]) -> str:
    return f"{(item.get('owner') or '').strip()}/{(item.get('repo') or '').strip()}".strip("/").lower()


def _match_repo(watchlists: dict[str, Any], path: str) -> dict[str, Any] | None:
    want = (path or "").strip().strip("/").lower()
    if not want:
        return None
    for item in watchlists.get("repos") or []:
        if _repo_full(item) == want:
            return item
    return None


def _mr_key(provider: str, owner: str, repo: str, number: int | str) -> str:
    return f"mr:{provider}:{owner}/{repo}!{number}"


def _remember_event(state: dict[str, Any], key: str, event_id: str) -> bool:
    """Return True if this event was already applied."""
    seen = state["seen_events"]
    if event_id and seen.get(key) == event_id:
        return True
    if event_id:
        seen[key] = event_id
    return False


def _set_attention(
    state: dict[str, Any],
    key: str,
    *,
    kind: str,
    title: str,
    detail: str,
    url: str | None,
    event_id: str,
    count_comment: bool,
    jira_keys: list[str] | None = None,
    mr: dict[str, Any] | None = None,
    issue: dict[str, Any] | None = None,
) -> None:
    if _remember_event(state, key, event_id):
        return
    prev = state["attention"].get(key) or {}
    count = int(prev.get("count") or 0)
    if count_comment:
        count = count + 1 if prev and prev.get("kind") == "comment" else 1
    flags = list(prev.get("flags") or [])
    show_detail = detail
    show_kind = kind
    if kind == "ci_red":
        if "ci_red" not in flags:
            flags.append("ci_red")
        if prev.get("kind") == "comment" and prev.get("detail"):
            show_detail = prev["detail"]
            show_kind = "comment"
            count = int(prev.get("count") or 1)
    elif kind == "ci_green":
        flags = [f for f in flags if f != "ci_red"]
        if prev.get("kind") == "ci_red" or not prev:
            state["attention"].pop(key, None)
            return
        show_detail = prev.get("detail") or detail
        show_kind = prev.get("kind") or kind
        count = int(prev.get("count") or 0)
    state["attention"][key] = {
        "key": key,
        "kind": show_kind,
        "title": title or prev.get("title") or key,
        "detail": (show_detail or "")[:500],
        "count": count,
        "url": url or prev.get("url"),
        "flags": flags,
        "updated_at": datetime.now(UTC).isoformat(),
        "jira_keys": jira_keys if jira_keys is not None else list(prev.get("jira_keys") or []),
        "mr": mr if mr is not None else prev.get("mr"),
        "issue": issue if issue is not None else prev.get("issue"),
        "blink": True,
    }


def clear_attention_key(state: dict[str, Any], key: str) -> None:
    state["attention"].pop(key, None)


def _adf_text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text") or "")
    parts = [_adf_text(child) for child in node.get("content") or []]
    text = "".join(parts)
    if node.get("type") in ("paragraph", "heading", "listItem"):
        return text + "\n"
    return text


def _doc_text(body: dict[str, Any] | None) -> str:
    parts: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        para = node.get("paragraph")
        if isinstance(para, dict):
            for el in para.get("elements") or []:
                if isinstance(el, dict):
                    run = (el.get("textRun") or {}).get("content")
                    if run:
                        parts.append(str(run))
        table = node.get("table")
        if isinstance(table, dict):
            for row in table.get("tableRows") or []:
                if not isinstance(row, dict):
                    continue
                for cell in row.get("tableCells") or []:
                    if isinstance(cell, dict):
                        for block in (cell.get("content") or []):
                            if isinstance(block, dict):
                                walk(block)
        for block in node.get("content") or []:
            if isinstance(block, dict) and block is not node:
                walk(block)

    if isinstance(body, dict):
        walk(body)
    return "".join(parts).strip()


def _flatten_tabs(tabs: list[Any] | None, out: list[dict[str, Any]]) -> None:
    for tab in tabs or []:
        if not isinstance(tab, dict):
            continue
        out.append(tab)
        _flatten_tabs(tab.get("childTabs"), out)


def _tab_sort_key(title: str, index: int) -> tuple[int, str, int]:
    """Prefer a tab whose title looks like a date. Else keep document order."""
    match = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", title)
    if match:
        y, m, d = match.groups()
        return (1, f"{int(y):04d}-{int(m):02d}-{int(d):02d}", index)
    return (0, "", index)


def _latest_tab_from_doc(payload: dict[str, Any]) -> dict[str, Any] | None:
    tabs: list[dict[str, Any]] = []
    _flatten_tabs(payload.get("tabs"), tabs)
    if not tabs and payload.get("body"):
        text = _doc_text(payload.get("body"))
        return {"title": payload.get("title") or "Doc", "text": text}
    best: dict[str, Any] | None = None
    best_key: tuple[int, str, int] = (-1, "", -1)
    for i, tab in enumerate(tabs):
        props = tab.get("tabProperties") or {}
        title = str(props.get("title") or f"Tab {i + 1}")
        index = int(props.get("index") or i)
        text = _doc_text((tab.get("documentTab") or {}).get("body"))
        if not text:
            continue
        key = _tab_sort_key(title, index)
        if key > best_key:
            best_key = key
            best = {"title": title, "text": text}
    return best


async def _read_latest_tab(token: str, doc_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"https://docs.googleapis.com/v1/documents/{doc_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"includeTabsContent": "true"},
        )
    if resp.status_code != 200:
        logger.warning("Standup doc read failed %s: %s", doc_id, resp.status_code)
        return None
    tab = _latest_tab_from_doc(resp.json() or {})
    if not tab or not tab.get("text"):
        return None
    text = str(tab["text"])[:6000]
    tab["text"] = text
    tab["hash"] = hashlib.sha256(text.encode()).hexdigest()[:16]
    return tab


def _named_from_text(text: str) -> tuple[list[str], list[int]]:
    keys: list[str] = []
    seen: set[str] = set()
    for match in JIRA_KEY_RE.finditer(text or ""):
        key = match.group(1)
        if key not in seen:
            seen.add(key)
            keys.append(key)
    mrs: list[int] = []
    seen_n: set[int] = set()
    for match in _MR_NUM_RE.finditer(text or ""):
        raw = match.group("n") or match.group("h")
        if not raw:
            continue
        num = int(raw)
        if num not in seen_n:
            seen_n.add(num)
            mrs.append(num)
    return keys, mrs


async def _haiku_off_track(
    user: User,
    tab_title: str,
    tab_text: str,
    my_mrs: list[dict[str, Any]],
    jira_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    keys, mrs = _named_from_text(tab_text)
    work_lines = []
    for mr in my_mrs[:12]:
        work_lines.append(
            f"MR !{mr.get('number')} {mr.get('title')} CI={mr.get('ci_state') or 'unknown'} "
            f"keys={','.join(mr.get('jira_keys') or [])}"
        )
    for issue in jira_issues[:12]:
        work_lines.append(
            f"{issue.get('key')} [{issue.get('status')}] {issue.get('summary')}"
        )
    prompt = (
        "Compare the latest standup tab with this person's open work. "
        "Return JSON only, no markdown, with keys "
        "named_keys (array of ticket keys the tab asks them to do), "
        "named_mrs (array of MR numbers the tab mentions), "
        "and alert (string or null). "
        "alert is set only when their open work misses the tab's plan or a named item is failing. "
        "If they are on that plan, alert is null. Do not invent keys.\n\n"
        f"Tab title: {tab_title}\n"
        f"Tab text:\n{tab_text[:4000]}\n\n"
        f"Open work:\n" + "\n".join(work_lines)
    )
    try:
        from app.services import usage_metering
        from app.services.ai_client import get_ai_client

        client = get_ai_client()
        async with usage_metering.usage_tracking_context(user_id=user.id, kind="coach_standup"):
            response = await client.messages.create(
                model=_haiku_model(),
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            await usage_metering.record_response_usage(response, model=HAIKU, kind="coach_standup")
        raw = response.content[0].text.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            named_keys = [str(k) for k in (parsed.get("named_keys") or []) if k]
            named_mrs = []
            for n in parsed.get("named_mrs") or []:
                try:
                    named_mrs.append(int(n))
                except (TypeError, ValueError):
                    continue
            alert = parsed.get("alert")
            return {
                "named_keys": named_keys or keys,
                "named_mrs": named_mrs or mrs,
                "alert": str(alert) if alert else None,
            }
    except Exception:
        logger.exception("Standup haiku call failed")
    return {"named_keys": keys, "named_mrs": mrs, "alert": None}


async def _jira_field_catalog(db: AsyncSession, user_id: UUID) -> dict[str, str]:
    creds = await _get_jira_credentials(db, user_id)
    if not creds:
        return {}
    base, email, token = creds
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"{base}/rest/api/3/field",
            auth=(email, token),
            headers={"Accept": "application/json"},
        )
    if resp.status_code != 200:
        return {}
    found: dict[str, str] = {}
    for field in resp.json() or []:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "").lower()
        fid = str(field.get("id") or "")
        if not fid:
            continue
        if "story point" in name and "story_points" not in found:
            found["story_points"] = fid
        elif name == "sprint" or name.endswith(" sprint"):
            found.setdefault("sprint", fid)
    return found


def _field_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _missing_field_names(issue: dict[str, Any], field_ids: dict[str, str]) -> list[str]:
    missing: list[str] = []
    if _field_empty(issue.get("priority")):
        missing.append("priority")
    if _field_empty(issue.get("labels")):
        missing.append("label")
    if _field_empty(issue.get("components")):
        missing.append("component")
    raw = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    sp = field_ids.get("story_points")
    if sp and _field_empty(raw.get(sp)):
        missing.append("story points")
    sprint = field_ids.get("sprint")
    if sprint and _field_empty(raw.get(sprint)):
        missing.append("sprint")
    return missing


async def _merged_gitlab(
    db: AsyncSession, user_id: UUID, repos: list[dict[str, Any]], username: str | None
) -> list[dict[str, Any]]:
    cfg = await _get_gitlab_config(db, user_id)
    if not cfg or not username:
        return []
    token, api, verify = cfg
    since = (datetime.now(UTC) - timedelta(days=5)).date().isoformat()
    headers = {"Authorization": f"Bearer {token}", "PRIVATE-TOKEN": token}
    out: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30, verify=verify) as http:
        for item in repos:
            if (item.get("provider") or "").lower() != "gitlab":
                continue
            owner = (item.get("owner") or "").strip()
            repo = (item.get("repo") or "").strip()
            if not owner or not repo:
                continue
            path = quote(f"{owner}/{repo}", safe="")
            resp = await http.get(
                f"{api}/projects/{path}/merge_requests",
                headers=headers,
                params={
                    "state": "merged",
                    "author_username": username,
                    "updated_after": since,
                    "per_page": 20,
                },
            )
            if resp.status_code != 200:
                continue
            for mr in resp.json() or []:
                if not isinstance(mr, dict) or not mr.get("merged_at"):
                    continue
                title = mr.get("title") or ""
                keys = coach_service._extract_jira_keys(
                    title, mr.get("description") or "", mr.get("source_branch")
                )
                out.append({
                    "provider": "gitlab",
                    "owner": owner,
                    "repo": repo,
                    "number": mr.get("iid"),
                    "title": title,
                    "url": mr.get("web_url"),
                    "merged_at": mr.get("merged_at"),
                    "jira_keys": keys,
                })
    return out


def _field_display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        parts = [_field_display(item) for item in value]
        return ", ".join(part for part in parts if part)
    if isinstance(value, dict):
        return str(value.get("name") or value.get("value") or "")
    text = str(value).strip()
    if "name=" in text:
        match = re.search(r"name=([^,\]]+)", text)
        if match:
            return match.group(1).strip()
    return text


def _sprint_entries(value: Any) -> list[dict[str, str]]:
    items = value if isinstance(value, list) else [value]
    found: list[dict[str, str]] = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            state = str(item.get("state") or "").strip().upper()
            end_raw = str(item.get("endDate") or "")
            end = end_raw[:10] if end_raw and "null" not in end_raw.lower() else ""
        else:
            text = str(item)
            name_m = re.search(r"name=([^,\]]+)", text)
            state_m = re.search(r"state=([^,\]]+)", text)
            end_m = re.search(r"endDate=([^,\]]+)", text)
            name = name_m.group(1).strip() if name_m else ""
            state = state_m.group(1).strip().upper() if state_m else ""
            end = ""
            if end_m and "null" not in end_m.group(1).lower():
                end = end_m.group(1)[:10]
        if not name:
            continue
        found.append({"name": name, "state": state, "end": end})
    return found


def _active_sprint(issues: list[dict[str, Any]], field_ids: dict[str, str]) -> dict[str, Any] | None:
    sprint_id = field_ids.get("sprint") or ""
    today = datetime.now().astimezone().date().isoformat()
    counts: dict[str, dict[str, Any]] = {}
    for issue in issues:
        raw = (issue.get("fields") or {}).get(sprint_id) if sprint_id else None
        for entry in _sprint_entries(raw):
            if entry.get("state") and entry["state"] != "ACTIVE":
                continue
            slot = counts.setdefault(entry["name"], {"name": entry["name"], "end": "", "count": 0})
            slot["count"] += 1
            if entry.get("end"):
                slot["end"] = entry["end"]
    if not counts:
        return None
    open_sprints = [slot for slot in counts.values() if not slot.get("end") or slot["end"] >= today]
    pool = open_sprints or list(counts.values())
    return max(pool, key=lambda slot: (slot["count"], slot.get("end") or ""))


def _situation_fp(state: dict[str, Any]) -> str:
    bits: list[str] = []
    field_ids = state.get("jira_field_ids") or {}
    sprint_id = field_ids.get("sprint") or ""
    for issue in state.get("jira_issues") or []:
        raw = (issue.get("fields") or {}).get(sprint_id) if sprint_id else None
        names = ",".join(entry["name"] for entry in _sprint_entries(raw))
        bits.append(
            f"{issue.get('key')}|{issue.get('status')}|{issue.get('updated')}|{names}"
        )
    for mr in state.get("my_mrs") or []:
        bits.append(
            f"mr|{mr.get('number')}|{mr.get('ci_state')}|{mr.get('next_action')}|"
            f"{','.join(mr.get('reviewers') or [])}|"
            f"{','.join(mr.get('jira_keys') or [])}"
        )
    for row in (state.get("attention") or {}).values():
        if not isinstance(row, dict):
            continue
        if row.get("kind") in ("comment", "ci_red", "jira_comment"):
            bits.append(f"att|{row.get('key')}|{row.get('detail')}|{row.get('flags')}")
    raw = "plan-v4\n" + "\n".join(bits)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _situation_lines(state: dict[str, Any], sprint_name: str) -> list[str]:
    field_ids = state.get("jira_field_ids") or {}
    sprint_id = field_ids.get("sprint") or ""
    mrs_by_key: dict[str, list[dict[str, Any]]] = {}
    for mr in state.get("my_mrs") or []:
        for key in mr.get("jira_keys") or []:
            mrs_by_key.setdefault(key, []).append(mr)
    lines: list[str] = []
    for issue in state.get("jira_issues") or []:
        raw = (issue.get("fields") or {}).get(sprint_id) if sprint_id else None
        in_sprint = any(entry["name"] == sprint_name for entry in _sprint_entries(raw))
        linked = mrs_by_key.get(issue.get("key") or "", [])
        mr_bits = []
        for mr in linked:
            mr_bits.append(
                f"!{mr.get('number')} CI={mr.get('ci_state') or 'unknown'} "
                f"draft={mr.get('draft')} reviewers={','.join(mr.get('reviewers') or []) or 'none'} "
                f"next={mr.get('next_action') or ''}"
            )
        lines.append(
            f"{issue.get('key')} | {issue.get('summary')} | status={issue.get('status')} | "
            f"priority={issue.get('priority')} | in_sprint={in_sprint} | "
            f"MRs={'; '.join(mr_bits) or 'none'}"
        )
    return lines


async def _build_sprint_plan(user: User, state: dict[str, Any]) -> dict[str, Any] | None:
    issues = [issue for issue in (state.get("jira_issues") or []) if issue.get("key")]
    if not issues:
        return None
    field_ids = state.get("jira_field_ids") or {}
    sprint = _active_sprint(issues, field_ids)
    today = datetime.now().astimezone().date()
    sprint_name = sprint["name"] if sprint else "unknown sprint"
    end = (sprint or {}).get("end") or ""
    days_left: int | None = None
    if end:
        try:
            end_day = date.fromisoformat(end)
            cursor = today
            days_left = 0
            while cursor <= end_day:
                if cursor.weekday() < 5:
                    days_left += 1
                cursor += timedelta(days=1)
        except ValueError:
            days_left = None
    lines = _situation_lines(state, sprint_name)
    prompt = (
        f"Today is {today.isoformat()} ({today.strftime('%A')}). "
        f"Active sprint: {sprint_name}. "
        + (
            f"It ends {end}. {days_left} working days left, including today. Do not count Saturday or Sunday.\n"
            if days_left is not None
            else "The sprint end date is not in the data. Plan the next 5 weekdays only.\n"
        )
        + "Plan only tickets with in_sprint=True. Ignore in_sprint=False.\n"
        "Goal: finish as many in-sprint tickets as the working days allow.\n"
        "Read next= and reviewers= literally.\n"
        "If next starts with 'Waiting on reviewers', the MR is already with reviewers. "
        "Put that ticket in waiting, not in today.\n"
        "If next starts with 'Ask for review', nobody is assigned. That is today's work: ask for review. Put it in today.\n"
        "If next starts with 'Fix failing CI', that ticket needs time today.\n"
        "If status contains Review and MRs=none, there is no open MR in the watched repos. "
        "Do not say review feedback is coming. Put it in waiting and say the Jira status is ahead of any open MR: "
        "either the MR was already merged, or the ticket should move back to in progress.\n"
        "today: at most 3 tickets to touch today. In-progress first, then red CI, then a new ticket with no MR.\n"
        "waiting: blocked tickets only. Two sentences each: what it is blocked on, and the first step when that clears. "
        "Also put one check for that ticket on a later day.\n"
        "days: each weekday after today until the sprint ends (at most 8). "
        "Spread new tickets with no MR across those days. Do not leave a weekday empty if work remains.\n"
        "A ticket is on at most one of today or a later day, plus waiting if it is blocked on review. "
        "Never also in wont_finish.\n"
        "wont_finish: in-sprint tickets that still will not fit. Usually this list is empty.\n"
        "Each plan is 2 or 3 sentences about what to do that day and why. Not a title.\n"
        "Use only keys and MR numbers from the list. Do not invent story points or dates.\n"
        "Return JSON only, no markdown:\n"
        '{"sprint":"","days_left":0,"end":"",'
        '"today":[{"key":"PROJ-1","plan":""}],'
        '"waiting":[{"key":"PROJ-2","plan":""}],'
        '"days":[{"date":"YYYY-MM-DD","label":"Mon","items":[{"key":"PROJ-3","plan":""}]}],'
        '"wont_finish":[{"key":"PROJ-4","why":""}]}\n\n'
        + "\n".join(lines)
    )
    try:
        from app.services import usage_metering
        from app.services.ai_client import get_ai_client

        client = get_ai_client()
        async with usage_metering.usage_tracking_context(user_id=user.id, kind="coach_sprint_plan"):
            response = await client.messages.create(
                model=_haiku_model(),
                max_tokens=1400,
                messages=[{"role": "user", "content": prompt}],
            )
            await usage_metering.record_response_usage(
                response, model=HAIKU, kind="coach_sprint_plan"
            )
        raw = response.content[0].text.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw)
    except Exception:
        logger.exception("Sprint plan failed")
        return None
    if not isinstance(parsed, dict):
        return None
    parsed["sprint"] = str(parsed.get("sprint") or sprint_name)
    parsed["days_left"] = days_left
    parsed["end"] = end
    days = []
    for day in parsed.get("days") or []:
        if not isinstance(day, dict):
            continue
        items = [item for item in (day.get("items") or []) if isinstance(item, dict) and item.get("key")]
        if items:
            day["items"] = items
            days.append(day)
    parsed["days"] = days
    parsed["built_at"] = datetime.now(UTC).isoformat()
    return parsed


async def _ensure_sprint_plan(user: User, state: dict[str, Any]) -> None:
    fp = _situation_fp(state)
    if state.get("sprint_plan_fp") == fp or state.get("sprint_plan_failed_fp") == fp:
        return
    plan = await _build_sprint_plan(user, state)
    if plan:
        state["sprint_plan"] = plan
        state["sprint_plan_fp"] = fp
        state.pop("sprint_plan_failed_fp", None)
    else:
        state["sprint_plan_failed_fp"] = fp


def _issue_brief(issue: dict[str, Any], field_ids: dict[str, str]) -> str:
    raw = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    sp = _field_display(raw.get(field_ids.get("story_points") or ""))
    sprint = _field_display(raw.get(field_ids.get("sprint") or ""))
    return (
        f"{issue.get('key')} | {issue.get('summary')} | status={issue.get('status') or ''} | "
        f"priority={issue.get('priority') or ''} | labels={', '.join(issue.get('labels') or [])} | "
        f"components={', '.join(issue.get('components') or [])} | "
        f"story points={sp} | sprint={sprint}"
    )


async def _suggest_jira_fields(user: User, state: dict[str, Any]) -> bool:
    """One Haiku call: which blanks matter, and the best value already used on similar tickets."""
    issues = [issue for issue in (state.get("jira_issues") or []) if issue.get("key")]
    if not issues:
        return True
    field_ids = state.get("jira_field_ids") or {}
    lines = [_issue_brief(issue, field_ids) for issue in issues[:20]]
    prompt = (
        "These are one person's open Jira tickets. Text after '=' is the current value. "
        "An empty value means the field is unset.\n"
        "Suggest a fill only when the exact value already appears on another ticket in this list. "
        "Copy that value. Name the ticket you copied from in why.\n"
        "If a field is empty on every ticket, do not invent a number or name. "
        "Put that field once in gaps.\n"
        "Return JSON only, no markdown: "
        '{"gaps":[{"name":"story points","why":"blank on every open ticket"}],'
        '"suggestions":[{"key":"PROJ-1","fields":[{"name":"priority","value":"Critical","why":"same component as PROJ-2"}]}]}\n'
        "Omit a ticket that needs nothing.\n\n"
        + "\n".join(lines)
    )
    try:
        from app.services import usage_metering
        from app.services.ai_client import get_ai_client

        client = get_ai_client()
        async with usage_metering.usage_tracking_context(user_id=user.id, kind="coach_jira_fields"):
            response = await client.messages.create(
                model=_haiku_model(),
                max_tokens=700,
                messages=[{"role": "user", "content": prompt}],
            )
            await usage_metering.record_response_usage(
                response, model=HAIKU, kind="coach_jira_fields"
            )
        raw = response.content[0].text.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw)
    except Exception:
        logger.exception("Jira field suggestion failed")
        return False

    suggestions = parsed.get("suggestions") if isinstance(parsed, dict) else None
    if not isinstance(suggestions, list):
        return False

    by_key = {issue.get("key"): issue for issue in issues}
    attention = state["attention"]
    for key in list(attention):
        if key.startswith("jira-fields:"):
            attention.pop(key, None)

    gaps = parsed.get("gaps") if isinstance(parsed.get("gaps"), list) else []
    gap_lines: list[str] = []
    for gap in gaps[:4]:
        if not isinstance(gap, dict):
            continue
        name = str(gap.get("name") or "").strip()
        why = str(gap.get("why") or "").strip()
        if name:
            gap_lines.append(f"{name}: {why or 'no matching value on your open tickets'}")
    if gap_lines:
        attention["jira-fields:gaps"] = {
            "key": "jira-fields:gaps",
            "kind": "jira_fields",
            "title": "No matching value to copy",
            "detail": "\n".join(gap_lines) + "\nToday will not change the ticket.",
            "count": len(gap_lines),
            "url": None,
            "flags": [],
            "updated_at": datetime.now(UTC).isoformat(),
            "jira_keys": [],
            "issue": None,
            "mr": None,
            "blink": False,
        }

    for row in suggestions[:8]:
        if not isinstance(row, dict):
            continue
        ikey = str(row.get("key") or "")
        issue = by_key.get(ikey)
        fields = row.get("fields") if isinstance(row.get("fields"), list) else []
        lines_out: list[str] = []
        for field in fields[:4]:
            if not isinstance(field, dict):
                continue
            name = str(field.get("name") or "").strip()
            value = str(field.get("value") or "").strip()
            why = str(field.get("why") or "").strip()
            if not name or not value:
                continue
            lines_out.append(f"{name} → {value}" + (f" ({why})" if why else ""))
        if not ikey or not lines_out:
            continue
        attention[f"jira-fields:{ikey}"] = {
            "key": f"jira-fields:{ikey}",
            "kind": "jira_fields",
            "title": f"{ikey}: suggested fields",
            "detail": "\n".join(lines_out) + "\nToday will not change the ticket.",
            "count": len(lines_out),
            "url": (issue or {}).get("url"),
            "flags": [],
            "updated_at": datetime.now(UTC).isoformat(),
            "jira_keys": [ikey],
            "issue": _public_issue(issue) if issue else {"key": ikey},
            "mr": None,
            "blink": False,
        }
    return True


def _apply_ci_attention(state: dict[str, Any]) -> None:
    """Turn pipeline status from the MR read into a Needs you row. No webhook."""
    attention = state["attention"]
    open_keys: set[str] = set()
    failing: list[tuple[str, dict[str, Any]]] = []
    passing: list[tuple[str, dict[str, Any]]] = []
    for mr in state.get("my_mrs") or []:
        if mr.get("is_author") is False:
            continue
        number = mr.get("number")
        if number is None:
            continue
        key = _mr_key(mr.get("provider") or "gitlab", mr.get("owner") or "", mr.get("repo") or "", number)
        open_keys.add(key)
        if mr.get("ci_state") in ("failure", "error"):
            failing.append((key, mr))
        elif mr.get("ci_state") == "success":
            passing.append((key, mr))
    for key in list(attention):
        row = attention.get(key) or {}
        if row.get("kind") == "ci_red" and key not in open_keys:
            attention.pop(key, None)
    for key, mr in failing:
        pipe = mr.get("pipeline_id") or "red"
        number = mr.get("number")
        _set_attention(
            state,
            key,
            kind="ci_red",
            title=f"{mr.get('repo_label') or mr.get('repo')}!{number}",
            detail="Pipeline failed",
            url=mr.get("url"),
            event_id=f"ci:{pipe}:failure",
            count_comment=False,
            jira_keys=list(mr.get("jira_keys") or []),
            mr=mr,
        )
    for key, mr in passing:
        pipe = mr.get("pipeline_id") or "green"
        number = mr.get("number")
        _set_attention(
            state,
            key,
            kind="ci_green",
            title=f"{mr.get('repo_label') or mr.get('repo')}!{number}",
            detail="Pipeline passed",
            url=mr.get("url"),
            event_id=f"ci:{pipe}:success",
            count_comment=False,
        )


def _apply_daily_notices(state: dict[str, Any], merged: list[dict[str, Any]]) -> None:
    """Notify about empty Jira fields and quiet tickets after a merged MR. No writes."""
    field_ids = state.get("jira_field_ids") or {}
    issues = list(state.get("jira_issues") or [])
    by_key = {i.get("key"): i for i in issues if i.get("key")}
    attention = state["attention"]

    for key in list(attention):
        if key.startswith("jira-fields:") or key.startswith("jira-quiet:"):
            attention.pop(key, None)

    used: set[str] = set()
    for issue in issues:
        if not _field_empty(issue.get("priority")):
            used.add("priority")
        if not _field_empty(issue.get("labels")):
            used.add("label")
        if not _field_empty(issue.get("components")):
            used.add("component")
        raw = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        sp = field_ids.get("story_points")
        sprint = field_ids.get("sprint")
        if sp and not _field_empty(raw.get(sp)):
            used.add("story points")
        if sprint and not _field_empty(raw.get(sprint)):
            used.add("sprint")

    field_rows = 0
    for issue in issues:
        if field_rows >= 8:
            break
        status = (issue.get("status") or "").lower()
        if "done" in status or "closed" in status:
            continue
        missing = [name for name in _missing_field_names(issue, field_ids) if name in used]
        if not missing:
            continue
        ikey = issue.get("key")
        if not ikey:
            continue
        field_rows += 1
        attention[f"jira-fields:{ikey}"] = {
            "key": f"jira-fields:{ikey}",
            "kind": "jira_fields",
            "title": f"{ikey} is missing {', '.join(missing)}",
            "detail": "Other open tickets in this project set these. Today will not change the ticket.",
            "count": 1,
            "url": issue.get("url"),
            "flags": [],
            "updated_at": datetime.now(UTC).isoformat(),
            "jira_keys": [ikey],
            "issue": _public_issue(issue),
            "mr": None,
            "blink": False,
        }

    now = datetime.now(UTC)
    for mr in merged:
        merged_at = _parse_dt(mr.get("merged_at"))
        if merged_at is None or now - merged_at < timedelta(days=2):
            continue
        for jira_key in mr.get("jira_keys") or []:
            issue = by_key.get(jira_key)
            if not issue:
                continue
            updated = _parse_dt(issue.get("updated"))
            if updated is not None and updated > merged_at + timedelta(minutes=10):
                continue
            attention[f"jira-quiet:{jira_key}"] = {
                "key": f"jira-quiet:{jira_key}",
                "kind": "jira_quiet",
                "title": f"{jira_key} still open after !{mr.get('number')} merged",
                "detail": (
                    "The MR has been merged for two days and the ticket has not been updated. "
                    "Close it if the work is finished. Today will not close it."
                ),
                "count": 1,
                "url": issue.get("url") or mr.get("url"),
                "flags": [],
                "updated_at": datetime.now(UTC).isoformat(),
                "jira_keys": [jira_key],
                "issue": _public_issue(issue),
                "mr": mr,
                "blink": True,
            }


async def _take_snapshot(
    db: AsyncSession,
    user: User,
    state: dict[str, Any],
    watchlists: dict[str, Any],
) -> None:
    field_ids = dict(state.get("jira_field_ids") or {})
    cached_on = field_ids.get("cached_on")
    if not cached_on or cached_on < (
        datetime.now().astimezone().date() - timedelta(days=7)
    ).isoformat():
        found = await _jira_field_catalog(db, user.id)
        if found:
            field_ids.update(found)
            field_ids["cached_on"] = _local_today()
            state["jira_field_ids"] = field_ids

    extra = [v for k, v in field_ids.items() if k in ("story_points", "sprint") and v]
    jira_issues, jira_error = await _fetch_jira_issues(
        db, user.id, watchlists["jira"], extra_fields=extra
    )
    my_mrs, reviews = await _fetch_repo_mrs(db, user.id, watchlists["repos"])
    gl_cfg = await _get_gitlab_config(db, user.id)
    gl_user = None
    if gl_cfg:
        try:
            token, api, verify = gl_cfg
            gl_user = await _gitlab_me(api, token, verify)
        except Exception:
            logger.warning("GitLab identity lookup failed during daily snapshot", exc_info=True)
    username = (gl_user or {}).get("username") if isinstance(gl_user, dict) else None
    gh_login = None
    gh_token = await coach_service._get_github_token(db, user.id)
    if gh_token:
        gh_login = await coach_service._github_me(gh_token)
    creds = await _get_jira_credentials(db, user.id)
    state["me"] = {
        "gitlab": username,
        "github": gh_login,
        "jira_email": creds[1] if creds else None,
    }
    today = datetime.now().astimezone().date()
    events = await _todays_calendar_occurrences(db, user.id, today)
    occurrences: list[dict[str, Any]] = []
    for meeting in watchlists["meetings"]:
        hit = _watched_meeting_occurrence_today(meeting, today, events)
        start = hit.get("start") if hit else None
        if not isinstance(start, datetime):
            continue
        occurrences.append({
            "meeting_id": meeting.get("id"),
            "title": meeting.get("title") or "Meeting",
            "start": start.isoformat(),
            "time_local": hit.get("time_local") if hit else meeting.get("time_local"),
            "notes_doc_id": meeting.get("notes_doc_id"),
            "notes_url": meeting.get("notes_url"),
        })
    notices: list[str] = []
    if jira_error:
        notices.append(jira_error)
    state["my_mrs"] = my_mrs
    state["reviews_waiting"] = reviews
    state["jira_issues"] = jira_issues
    state["occurrences"] = occurrences
    state["notices"] = notices
    state["snapshot_on"] = _local_today()
    state["watch_fp"] = _watch_fp(watchlists)
    merged = await _merged_gitlab(db, user.id, watchlists["repos"], username)
    _apply_daily_notices(state, merged)
    _apply_ci_attention(state)


async def _standup_if_due(
    db: AsyncSession,
    user: User,
    state: dict[str, Any],
) -> None:
    now = datetime.now(UTC)
    reads = state["standup_reads"]
    user_config = await _get_google_user_config(db, user.id)
    token = await _google_access_token(user_config) if user_config else None
    for occ in state.get("occurrences") or []:
        start = _parse_dt(occ.get("start"))
        if start is None:
            continue
        read_key = f"{occ.get('meeting_id')}|{occ.get('start')}"
        if read_key in reads:
            continue
        if now < start + timedelta(hours=1):
            continue
        doc_id = occ.get("notes_doc_id")
        if not doc_id or not token:
            reads[read_key] = {
                "read_at": now.isoformat(),
                "skipped": "no_doc" if not doc_id else "no_google",
                "alert": None,
                "named_keys": [],
                "named_mrs": [],
                "tab_title": None,
            }
            continue
        tab = await _read_latest_tab(token, str(doc_id))
        if not tab:
            reads[read_key] = {
                "read_at": now.isoformat(),
                "skipped": "unread",
                "alert": "Could not read the latest standup tab.",
                "named_keys": [],
                "named_mrs": [],
                "tab_title": None,
            }
            continue
        prev = state.get("doc_tab") or {}
        if prev.get("doc_id") == doc_id and prev.get("hash") == tab["hash"]:
            reads[read_key] = {
                "read_at": now.isoformat(),
                "alert": "The latest standup tab has not changed since the last read.",
                "named_keys": list(prev.get("named_keys") or []),
                "named_mrs": list(prev.get("named_mrs") or []),
                "tab_title": tab["title"],
            }
            continue
        judged = await _haiku_off_track(
            user,
            tab["title"],
            tab["text"],
            list(state.get("my_mrs") or []),
            list(state.get("jira_issues") or []),
        )
        state["doc_tab"] = {
            "doc_id": doc_id,
            "hash": tab["hash"],
            "named_keys": judged["named_keys"],
            "named_mrs": judged["named_mrs"],
            "title": tab["title"],
        }
        reads[read_key] = {
            "read_at": now.isoformat(),
            "alert": judged["alert"],
            "named_keys": judged["named_keys"],
            "named_mrs": judged["named_mrs"],
            "tab_title": tab["title"],
        }


def _latest_standup(state: dict[str, Any]) -> dict[str, Any] | None:
    reads = state.get("standup_reads") or {}
    latest: dict[str, Any] | None = None
    latest_at = ""
    for read in reads.values():
        if not isinstance(read, dict):
            continue
        at = str(read.get("read_at") or "")
        if at >= latest_at:
            latest_at = at
            latest = read
    return latest


def _priority_bonus(issue: dict[str, Any] | None) -> int:
    name = ((issue or {}).get("priority") or "").lower()
    if "highest" in name or name == "blocker":
        return 3
    if "high" in name:
        return 2
    if "medium" in name:
        return 1
    return 0


def _focus_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    standup = _latest_standup(state)
    named_keys = set((standup or {}).get("named_keys") or [])
    named_mrs = set((standup or {}).get("named_mrs") or [])
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        if item["id"] in seen:
            return
        seen.add(item["id"])
        items.append(item)

    for row in (state.get("attention") or {}).values():
        if not isinstance(row, dict):
            continue
        kind = row.get("kind")
        score = 40
        if kind == "comment":
            score = 92
        elif kind == "jira_comment":
            score = 90
        elif kind == "jira_quiet":
            score = 78
        elif "ci_red" in (row.get("flags") or []) or kind == "ci_red":
            score = 74
        keys = set(row.get("jira_keys") or [])
        mr = row.get("mr") if isinstance(row.get("mr"), dict) else None
        number = (mr or {}).get("number")
        if keys & named_keys or (number in named_mrs):
            score += 15
        count = int(row.get("count") or 0)
        why = row.get("detail") or row.get("title") or ""
        if count > 1 and kind == "comment":
            why = f"{count} new comments. Latest: {why}"
        add({
            "id": row["key"],
            "lane": "MR" if str(row["key"]).startswith("mr:") else "Jira",
            "title": row.get("title") or row["key"],
            "why": why,
            "score": score,
            "cta": "focus" if mr or row.get("issue") else "open",
            "mr": mr,
            "issue": row.get("issue"),
            "blink": bool(row.get("blink")),
        })

    for mr in state.get("my_mrs") or []:
        keys = set(mr.get("jira_keys") or [])
        number = mr.get("number")
        if not (keys & named_keys or number in named_mrs):
            continue
        why = "The latest standup tab names this."
        if mr.get("ci_state") in ("failure", "error"):
            why = "The latest standup tab names this, and CI is red."
        add({
            "id": f"standup-mr:{mr.get('provider')}:{number}",
            "lane": "My MR",
            "title": f"{mr.get('repo_label')}!{number}: {mr.get('title')}",
            "why": why,
            "score": 84 + (10 if mr.get("ci_state") in ("failure", "error") else 0),
            "cta": "focus",
            "mr": mr,
            "blink": mr.get("ci_state") in ("failure", "error"),
        })

    for issue in state.get("jira_issues") or []:
        if issue.get("key") not in named_keys:
            continue
        add({
            "id": f"standup-jira:{issue.get('key')}",
            "lane": "Jira",
            "title": f"{issue.get('key')}: {issue.get('summary')}",
            "why": "The latest standup tab names this ticket.",
            "score": 80 + _priority_bonus(issue),
            "cta": "focus",
            "issue": _public_issue(issue),
            "blink": False,
        })

    if not items:
        for issue in state.get("jira_issues") or []:
            status = (issue.get("status") or "").lower()
            if "progress" not in status:
                continue
            add({
                "id": f"jira:{issue.get('key')}",
                "lane": "Jira",
                "title": f"{issue.get('key')}: {issue.get('summary')}",
                "why": "In progress. The standup tab has not named a ticket yet.",
                "score": 40 + _priority_bonus(issue),
                "cta": "focus",
                "issue": _public_issue(issue),
                "blink": False,
            })

    items.sort(key=lambda row: (-int(row["score"]), row["title"]))
    return items[:3]


def _meeting_soon(state: dict[str, Any]) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for occ in state.get("occurrences") or []:
        start = _parse_dt(occ.get("start"))
        if start is None:
            continue
        minutes = (start - now).total_seconds() / 60.0
        if 0 <= minutes <= 15:
            rows.append({
                "key": f"meeting:{occ.get('meeting_id')}:{occ.get('start')}",
                "kind": "meeting",
                "title": occ.get("title") or "Meeting",
                "detail": f"Starts in {int(minutes)} min",
                "count": 1,
                "url": None,
                "flags": [],
                "blink": True,
                "jira_keys": [],
            })
    return rows


def _standup_cards(state: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    reads = state.get("standup_reads") or {}
    now = datetime.now(UTC)
    for occ in state.get("occurrences") or []:
        start = _parse_dt(occ.get("start"))
        read_key = f"{occ.get('meeting_id')}|{occ.get('start')}"
        read = reads.get(read_key) if isinstance(reads.get(read_key), dict) else None
        due = start + timedelta(hours=1) if start else None
        if read:
            draft = read.get("alert") or "Latest tab checked. Nothing looks off the plan."
        elif due and now < due:
                draft = (
                    "The latest tab is read one hour after this meeting ("
                    + due.astimezone().strftime("%I:%M %p").lstrip("0")
                    + ")."
                )
        else:
            draft = "Waiting for the one-hour read."
        cards.append({
            "meeting_id": occ.get("meeting_id"),
            "title": occ.get("title") or "Meeting",
            "notes_url": occ.get("notes_url"),
            "time_local": occ.get("time_local"),
            "draft": draft,
            "has_notes": bool(occ.get("notes_doc_id")),
        })
    return cards


def _public_sprint_plan(plan: Any) -> dict[str, Any] | None:
    if not isinstance(plan, dict):
        return None
    days = []
    for day in plan.get("days") or []:
        if not isinstance(day, dict):
            continue
        items = [item for item in (day.get("items") or []) if isinstance(item, dict) and item.get("key")]
        if items:
            days.append({**day, "items": items})
    return {**plan, "days": days}


async def build_today(db: AsyncSession, user: User, *, refresh: bool = False) -> dict[str, Any]:
    profile = await get_or_create_profile(db, user.id)
    watchlists = _normalize_watchlists(profile.watchlists)
    reminder_prefs = _normalize_reminder_prefs(profile.reminder_prefs)
    state = _state_of(profile)
    fp = _watch_fp(watchlists)
    changed = False
    if refresh or state.get("snapshot_on") != _local_today() or state.get("watch_fp") != fp:
        await _take_snapshot(db, user, state, watchlists)
        state["field_rule"] = "used-by-project"
        changed = True
    elif state.get("field_rule") != "used-by-project":
        _apply_daily_notices(state, [])
        state["field_rule"] = "used-by-project"
        changed = True
    mrs_now = state.get("my_mrs") or []
    if mrs_now and any("reviewers" not in mr for mr in mrs_now):
        my_mrs, reviews = await _fetch_repo_mrs(db, user.id, watchlists["repos"])
        state["my_mrs"] = my_mrs
        state["reviews_waiting"] = reviews
        changed = True
    if state.get("field_suggest_version") != 2 and state.get("field_suggest_failed_on") != _local_today():
        ok = await _suggest_jira_fields(user, state)
        state["field_suggest_on"] = _local_today()
        state["field_suggest_ok"] = bool(ok)
        if ok:
            state["field_suggest_version"] = 2
        else:
            state["field_suggest_failed_on"] = _local_today()
        changed = True
    plan_fp_before = state.get("sprint_plan_fp")
    failed_fp_before = state.get("sprint_plan_failed_fp")
    await _ensure_sprint_plan(user, state)
    if (
        state.get("sprint_plan_fp") != plan_fp_before
        or state.get("sprint_plan_failed_fp") != failed_fp_before
    ):
        changed = True
    reads_before = json.dumps(state.get("standup_reads") or {}, sort_keys=True)
    await _standup_if_due(db, user, state)
    if json.dumps(state.get("standup_reads") or {}, sort_keys=True) != reads_before:
        changed = True
    if changed:
        await _save(db, profile, state)

    default_orbit = reminder_prefs.get("default_orbit_project_id")
    my_mrs = []
    for mr in state.get("my_mrs") or []:
        row = dict(mr)
        if default_orbit and not row.get("orbit_project_id"):
            row["orbit_project_id"] = default_orbit
        my_mrs.append(row)
    reviews = []
    for mr in state.get("reviews_waiting") or []:
        row = dict(mr)
        if default_orbit and not row.get("orbit_project_id"):
            row["orbit_project_id"] = default_orbit
        reviews.append(row)
    sprint_id = (state.get("jira_field_ids") or {}).get("sprint") or ""
    jira_issues = []
    for issue in state.get("jira_issues") or []:
        row = _public_issue(issue)
        names = [entry["name"] for entry in _sprint_entries((issue.get("fields") or {}).get(sprint_id))]
        row["sprint"] = ", ".join(names)
        if default_orbit and not row.get("orbit_project_id"):
            row["orbit_project_id"] = default_orbit
        jira_issues.append(row)

    attention = list((state.get("attention") or {}).values())
    attention.extend(_meeting_soon(state))
    attention.sort(key=lambda row: (not row.get("blink"), row.get("title") or ""))

    integrations = {
        "atlassian": await _plugin_enabled(db, user.id, "atlassian"),
        "github": await _plugin_enabled(db, user.id, "github"),
        "gitlab": await _plugin_enabled(db, user.id, "gitlab"),
        "google_drive": await _plugin_enabled(db, user.id, "google-drive"),
    }
    hook = str(profile.id)
    return {
        "date": _local_today(),
        "generated_at": datetime.now(UTC).isoformat(),
        "focus": _focus_items(state),
        "standups": _standup_cards(state),
        "my_mrs": my_mrs,
        "reviews_waiting": reviews,
        "jira_issues": jira_issues,
        "attention": attention,
        "sprint_plan": _public_sprint_plan(state.get("sprint_plan")),
        "reminders": [
            {"message": row["detail"], "title": row["title"], "meeting_id": row["key"], "type": "meeting"}
            for row in attention
            if row.get("kind") == "meeting"
        ],
        "notices": list(state.get("notices") or []),
        "watchlists": watchlists,
        "reminder_prefs": reminder_prefs,
        "integrations": integrations,
        "hooks": {
            "gitlab": f"/coach/hooks/gitlab/{hook}",
            "github": f"/coach/hooks/github/{hook}",
            "jira": f"/coach/hooks/jira/{hook}",
        },
        "snapshot_on": state.get("snapshot_on"),
    }


async def saved_standup(db: AsyncSession, user: User, meeting_id: str) -> dict[str, Any]:
    profile = await get_or_create_profile(db, user.id)
    state = _state_of(profile)
    watchlists = _normalize_watchlists(profile.watchlists)
    meeting = next((m for m in watchlists["meetings"] if m.get("id") == meeting_id), None)
    if meeting is None:
        raise ValueError("Meeting not on watchlist")
    draft = "The latest tab is read one hour after the meeting, and only once."
    for occ in state.get("occurrences") or []:
        if occ.get("meeting_id") != meeting_id:
            continue
        read_key = f"{meeting_id}|{occ.get('start')}"
        read = (state.get("standup_reads") or {}).get(read_key)
        if isinstance(read, dict) and read.get("alert"):
            draft = str(read["alert"])
        elif isinstance(read, dict):
            draft = "Latest tab checked. Nothing looks off the plan."
    return {
        "meeting_id": meeting_id,
        "title": meeting.get("title") or "Meeting",
        "draft": draft,
        "has_notes": bool(meeting.get("notes_doc_id") or meeting.get("notes_url")),
        "notes_url": meeting.get("notes_url"),
    }


async def clear_attention(db: AsyncSession, user: User, key: str) -> None:
    profile = await get_or_create_profile(db, user.id)
    state = _state_of(profile)
    clear_attention_key(state, key)
    await _save(db, profile, state)


async def _profile_by_hook(db: AsyncSession, profile_id: UUID) -> CoachProfile | None:
    return await db.get(CoachProfile, profile_id)


async def handle_gitlab(db: AsyncSession, profile_id: UUID, payload: dict[str, Any]) -> None:
    profile = await _profile_by_hook(db, profile_id)
    if profile is None or not isinstance(payload, dict):
        return
    watchlists = _normalize_watchlists(profile.watchlists)
    project = payload.get("project") or {}
    path = project.get("path_with_namespace") or ""
    repo = _match_repo(watchlists, path)
    if repo is None:
        return
    state = _state_of(profile)
    kind = payload.get("object_kind")
    me = (state.get("me") or {}).get("gitlab") or ""
    owner = repo.get("owner") or ""
    name = repo.get("repo") or ""

    if kind == "note":
        attrs = payload.get("object_attributes") or {}
        if attrs.get("noteable_type") != "MergeRequest" or attrs.get("system"):
            return
        mr = payload.get("merge_request") or {}
        number = mr.get("iid")
        if number is None:
            return
        username = ((payload.get("user") or {}).get("username") or "")
        key = _mr_key("gitlab", owner, name, number)
        if me and username.lower() == str(me).lower():
            if not _remember_event(state, key, f"note:{attrs.get('id')}"):
                clear_attention_key(state, key)
                await _save(db, profile, state)
            return
        title = mr.get("title") or f"!{number}"
        _set_attention(
            state,
            key,
            kind="comment",
            title=f"{owner}/{name}!{number}: {title}",
            detail=str(attrs.get("note") or ""),
            url=mr.get("url"),
            event_id=f"note:{attrs.get('id')}",
            count_comment=True,
            jira_keys=coach_service._extract_jira_keys(title, attrs.get("note") or ""),
        )
        await _save(db, profile, state)
        return

    if kind == "pipeline":
        attrs = payload.get("object_attributes") or {}
        status = (attrs.get("status") or "").lower()
        mr = payload.get("merge_request") or {}
        number = mr.get("iid")
        if number is None:
            ref = attrs.get("ref")
            for row in state.get("my_mrs") or []:
                if row.get("source_branch") and row.get("source_branch") == ref:
                    number = row.get("number")
                    mr = row
                    break
        if number is None:
            return
        key = _mr_key("gitlab", owner, name, number)
        if status in ("failed", "canceled"):
            _set_attention(
                state,
                key,
                kind="ci_red",
                title=f"{owner}/{name}!{number}",
                detail="Pipeline failed",
                url=mr.get("url") or mr.get("web_url"),
                event_id=f"pipe:{attrs.get('id')}:{status}",
                count_comment=False,
            )
        elif status == "success":
            _set_attention(
                state,
                key,
                kind="ci_green",
                title=f"{owner}/{name}!{number}",
                detail="Pipeline passed",
                url=mr.get("url"),
                event_id=f"pipe:{attrs.get('id')}:{status}",
                count_comment=False,
            )
        await _save(db, profile, state)


async def handle_github(db: AsyncSession, profile_id: UUID, event: str, payload: dict[str, Any]) -> None:
    profile = await _profile_by_hook(db, profile_id)
    if profile is None or not isinstance(payload, dict):
        return
    watchlists = _normalize_watchlists(profile.watchlists)
    repo_obj = payload.get("repository") or {}
    full = repo_obj.get("full_name") or ""
    repo = _match_repo(watchlists, full)
    if repo is None:
        return
    state = _state_of(profile)
    owner = repo.get("owner") or ""
    name = repo.get("repo") or ""
    me = (state.get("me") or {}).get("github") or ""

    if event in ("issue_comment", "pull_request_review_comment"):
        comment = payload.get("comment") or {}
        pr = payload.get("pull_request") or payload.get("issue") or {}
        number = pr.get("number")
        if number is None:
            return
        user_login = ((comment.get("user") or {}).get("login") or "")
        key = _mr_key("github", owner, name, number)
        if me and user_login.lower() == me.lower():
            if not _remember_event(state, key, f"gh:{comment.get('id')}"):
                clear_attention_key(state, key)
                await _save(db, profile, state)
            return
        _set_attention(
            state,
            key,
            kind="comment",
            title=f"{full}#{number}: {pr.get('title') or ''}",
            detail=str(comment.get("body") or ""),
            url=comment.get("html_url") or pr.get("html_url"),
            event_id=f"gh:{comment.get('id')}",
            count_comment=True,
        )
        await _save(db, profile, state)
        return

    if event == "check_run":
        check = payload.get("check_run") or {}
        if (check.get("conclusion") or "") not in ("failure", "timed_out", "cancelled"):
            return
        prs = check.get("pull_requests") or []
        if not prs:
            return
        number = (prs[0] or {}).get("number")
        if number is None:
            return
        _set_attention(
            state,
            _mr_key("github", owner, name, number),
            kind="ci_red",
            title=f"{full}#{number}",
            detail=f"Check failed: {check.get('name') or 'CI'}",
            url=check.get("html_url"),
            event_id=f"check:{check.get('id')}",
            count_comment=False,
        )
        await _save(db, profile, state)


async def handle_jira(db: AsyncSession, profile_id: UUID, payload: dict[str, Any]) -> None:
    profile = await _profile_by_hook(db, profile_id)
    if profile is None or not isinstance(payload, dict):
        return
    event = str(payload.get("webhookEvent") or "")
    if "comment" not in event:
        return
    issue = payload.get("issue") or {}
    issue_key = issue.get("key") or ""
    project_key = issue_key.split("-")[0] if "-" in issue_key else ""
    watchlists = _normalize_watchlists(profile.watchlists)
    watched = {
        (item.get("project_key") or "").upper()
        for item in watchlists.get("jira") or []
    }
    if project_key.upper() not in watched:
        return
    comment = payload.get("comment") or {}
    author = comment.get("author") or {}
    email = (author.get("emailAddress") or "").lower()
    state = _state_of(profile)
    me = ((state.get("me") or {}).get("jira_email") or "").lower()
    key = f"jira-comment:{issue_key}"
    event_id = f"jira:{comment.get('id')}"
    if me and email == me:
        if not _remember_event(state, key, event_id):
            clear_attention_key(state, key)
            await _save(db, profile, state)
        return
    body = comment.get("body")
    text = _adf_text(body) if isinstance(body, dict) else str(body or "")
    summary = ((issue.get("fields") or {}).get("summary") or "")
    _set_attention(
        state,
        key,
        kind="jira_comment",
        title=f"{issue_key}: {summary}".strip(),
        detail=text.strip(),
        url=f"{(issue.get('self') or '').split('/rest/')[0]}/browse/{issue_key}" if issue.get("self") else None,
        event_id=event_id,
        count_comment=True,
        jira_keys=[issue_key],
        issue={"key": issue_key, "summary": summary},
    )
    await _save(db, profile, state)
