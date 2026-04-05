"""Turn ``SessionLayer`` rows into prompt text for ``assemble_context``.

Layers may ship pre-loaded body text in ``cached_content["text"]``. If not, we still
inject label, type, and ``reference_url`` so the model sees what the user attached
without requiring them to paste the URL every turn.
"""

from __future__ import annotations

from app.models.context import SessionLayer, SessionLayerType


def _estimate_tokens(char_len: int) -> int:
    """Rough heuristic (~4 chars per token)."""
    return max(1, char_len // 4)


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
        lines.append(
            "PR details are not pre-loaded here. Use GitHub/GitLab MCP or repo tools if needed."
        )

    if len(lines) == 1:
        # Label-only layer (no URL, no cached text) — still mention it.
        lines.append(
            "(No reference URL or cached notes. Add notes when creating the layer, or paste details in chat.)"
        )

    chunk = "\n".join(lines)
    est = layer.token_count if layer.token_count > 0 else max(24, _estimate_tokens(len(chunk)))
    return chunk, est
