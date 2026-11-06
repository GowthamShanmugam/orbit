"""One-shot AI review of a PR diff → suggested inline comments (not posted yet).

May optionally read/search the PR/MR head checkout when the diff alone is not enough.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.services.ai_checkout_tools import run_with_checkout_tools
from app.services.ai_service import AVAILABLE_MODELS

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-sonnet-4-6"
_MAX_FILES = 40
_MAX_PATCH_CHARS = 12_000
_MAX_TOTAL_CHARS = 100_000
_MAX_SUGGESTIONS = 12

_SYSTEM = """You are a careful code reviewer.
Review the provided PR diff hunks.
You MAY call read_file or search_code on the PR/MR head checkout only when the
diff is not enough (e.g. to check a caller, shared helper, or test). Prefer the
diff alone when it is sufficient. Do not browse the whole repo.
Return ONLY a JSON array (no markdown fences, no prose) of suggested inline comments:
[
  {
    "path": "path/to/file.py",
    "line": 42,
    "side": "RIGHT",
    "severity": "high" | "medium" | "low",
    "body": "Clear actionable comment for the author"
  }
]

Rules:
- "line" must be a NEW-file (RIGHT) line number from a + line or context line in the diff.
- Prefer RIGHT side. Use LEFT only for deleted-line comments (rare).
- Only comment on real issues: bugs, security, broken logic, missing tests for risky changes.
- Do NOT invent speculative "might break" findings.
- Do NOT comment on style-only nits unless severe.
- Empty array [] is fine if the PR looks sound.
- Max 12 suggestions. Be concise (1-3 sentences per body).
"""


def _files_to_diff_blob(files: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    total = 0
    for f in files[:_MAX_FILES]:
        path = str(f.get("filename") or f.get("path") or "")
        if not path:
            continue
        patch = f.get("patch")
        if not isinstance(patch, str) or not patch.strip():
            continue
        clipped = patch if len(patch) <= _MAX_PATCH_CHARS else patch[:_MAX_PATCH_CHARS] + "\n…(truncated)"
        block = f"=== {path} ===\n{clipped}\n"
        if total + len(block) > _MAX_TOTAL_CHARS:
            break
        chunks.append(block)
        total += len(block)
    return "\n".join(chunks)


def _parse_suggestions(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("AI review returned non-JSON")
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        body = str(item.get("body") or "").strip()
        try:
            line = int(item.get("line"))
        except (TypeError, ValueError):
            continue
        if not path or not body or line < 1:
            continue
        side = str(item.get("side") or "RIGHT").upper()
        if side not in ("LEFT", "RIGHT"):
            side = "RIGHT"
        sev = str(item.get("severity") or "medium").lower()
        if sev not in ("high", "medium", "low"):
            sev = "medium"
        out.append(
            {
                "path": path,
                "line": line,
                "side": side,
                "severity": sev,
                "body": body[:2000],
            }
        )
        if len(out) >= _MAX_SUGGESTIONS:
            break
    return out


def _filter_known_paths(
    suggestions: list[dict[str, Any]], files: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    known = {
        str(f.get("filename") or f.get("path") or "")
        for f in files
        if f.get("filename") or f.get("path")
    }
    if not known:
        return suggestions
    return [s for s in suggestions if s["path"] in known]


async def suggest_pr_comments(
    *,
    title: str,
    files: list[dict[str, Any]],
    model_id: str | None = None,
    checkout_path: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (suggested comments, checkout paths/tools used). Does not post."""
    blob = _files_to_diff_blob(files)
    if not blob.strip():
        return [], []

    mid = model_id or _DEFAULT_MODEL
    if mid not in AVAILABLE_MODELS:
        mid = _DEFAULT_MODEL

    checkout_note = (
        "A local PR/MR head checkout is available via read_file / search_code. "
        "Use those tools only if you need more context than the diff."
        if checkout_path
        else "No local checkout is available; review from the diff only."
    )
    user_msg = (
        f"PR title: {title or '(untitled)'}\n"
        f"{checkout_note}\n\n"
        f"Diff (changed files only):\n\n{blob}\n\n"
        "Return the JSON array of suggestions now (after any optional tool use)."
    )

    raw, used = await run_with_checkout_tools(
        system=_SYSTEM,
        user_message=user_msg,
        checkout_path=checkout_path,
        model_id=mid,
        max_tokens=4096,
    )
    suggestions = _filter_known_paths(_parse_suggestions(raw), files)
    return suggestions, used
