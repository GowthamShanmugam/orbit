"""Turn ``SessionLayer`` rows into prompt text for ``assemble_context``.

Layers may ship pre-loaded body text in ``cached_content["text"]``. If not, we still
inject label, type, and ``reference_url`` so the model sees what the user attached
without requiring them to paste the URL every turn.
"""

from __future__ import annotations

import re

from app.models.context import SessionLayer, SessionLayerType


def _estimate_tokens(char_len: int) -> int:
    """Rough heuristic (~4 chars per token)."""
    return max(1, char_len // 4)


def _parse_github_pr(url: str) -> tuple[str, str, int] | None:
    m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", url, re.I)
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3))


def _parse_gitlab_mr(url: str) -> tuple[str, int] | None:
    """Return (project_path, merge_request_iid) for GitLab MR URLs."""
    m = re.search(r"https?://[^/]+/(.+?)/-/merge_requests/(\d+)", url, re.I)
    if not m:
        m = re.search(r"https?://[^/]+/(.+?)/merge_requests/(\d+)", url, re.I)
    if not m:
        return None
    path = m.group(1).strip("/")
    if not path or "/" not in path:
        return None
    return path, int(m.group(2))


def layer_to_prompt_chunk(layer: SessionLayer) -> tuple[str, int] | None:
    """
    Return (markdown chunk, estimated_tokens) or None if nothing to emit.

    Uses ``cached_content["text"]`` (or ``summary``) when present; otherwise builds
    a metadata block from label, type, and reference URL.
    """
    if not str(layer.label).strip():
        return None

    cc = layer.cached_content or {}
    raw = cc.get("text") or cc.get("summary")
    body_text = (raw if isinstance(raw, str) else str(raw or "")).strip()
    if body_text:
        header = f"--- Layer: {layer.label} ({layer.type.value}) ---"
        chunk = f"{header}\n{body_text}"
        est = layer.token_count if layer.token_count > 0 else _estimate_tokens(len(chunk))
        return chunk, est

    lines: list[str] = [f"--- Layer: {layer.label} ({layer.type.value}) ---"]
    if layer.reference_url:
        lines.append(f"Reference: {layer.reference_url}")
    if layer.type == SessionLayerType.jira_ticket:
        lines.append(
            "Full issue body is not pre-loaded here. If you need description or comments, "
            "use the Atlassian MCP tools (e.g. get issue by key from the URL or reference)."
        )
    elif layer.type == SessionLayerType.pull_request:
        url = (layer.reference_url or "").strip()
        if not url:
            # Users often paste the MR/PR URL into Label only.
            maybe = (layer.label or "").strip()
            if _parse_github_pr(maybe) or _parse_gitlab_mr(maybe):
                url = maybe
        gl = _parse_gitlab_mr(url) if url else None
        gh = _parse_github_pr(url) if url else None
        cc_status = (layer.cached_content or {}).get("pr_checkout_status")
        if cc_status:
            lines.append(f"pr_checkout_status: {cc_status}")
        if gl:
            project_path, iid = gl
            lines.append(f"provider: gitlab")
            lines.append(f"project_id: {project_path}")
            lines.append(f"merge_request_iid: {iid}")
            lines.append(
                "Use GitLab MCP tools with these exact arguments, for example "
                f'project_id="{project_path}" and merge_request_iid={iid} '
                "(or projectId / merge_request_iid per the tool schema). "
                "Fetch the MR details and changes/diff before reviewing. "
                "Do not ask the user to paste the diff unless tools fail. "
                "If a local PR/MR checkout is listed in session context, verify code "
                "with repo_* tools against that checkout (not main)."
            )
        elif gh:
            owner, repo, number = gh
            lines.append("provider: github")
            lines.append(f"owner: {owner}")
            lines.append(f"repo: {repo}")
            lines.append(f"pull_number: {number}")
            lines.append(
                "Use GitHub MCP / pull_request tools with these values to fetch the PR "
                "and diff before reviewing. Do not ask the user to paste the diff unless tools fail. "
                "If a local PR/MR checkout is listed in session context, verify code "
                "with repo_* tools against that checkout (not main)."
            )
        else:
            lines.append(
                "PR details are not pre-loaded here. Use GitHub/GitLab MCP or repo tools if needed."
            )
    elif layer.type in (SessionLayerType.google_doc, SessionLayerType.google_drive_folder):
        doc_id_hint = ""
        if layer.reference_url:
            m = re.search(r"/d/([a-zA-Z0-9_-]+)", layer.reference_url)
            if m:
                doc_id_hint = f" The document ID is: {m.group(1)}"
        lines.append(
            "The document content is not pre-loaded here. You MUST fetch it using the "
            "Google MCP tools (e.g. get_doc with the document ID from the URL) before "
            "answering questions about it." + doc_id_hint
        )

    if len(lines) == 1:
        # Label-only layer (no URL, no cached text) — still mention it.
        lines.append(
            "(No reference URL or cached notes. Add notes when creating the layer, or paste details in chat.)"
        )

    chunk = "\n".join(lines)
    est = layer.token_count if layer.token_count > 0 else max(24, _estimate_tokens(len(chunk)))
    return chunk, est
