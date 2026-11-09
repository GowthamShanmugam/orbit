"""Thorough AI review of a PR diff → suggested inline comments (not posted yet).

When a PR/MR head checkout exists (usual after Focus / layer add), the reviewer
must open related tests and callers before claiming a break. Diff-only is a
fallback when checkout is missing.
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
_REVIEW_TOOL_ROUNDS = 12

_SYSTEM = """You are a careful code reviewer doing a thorough review, not a skim.

You receive PR/MR diff hunks. When a local head checkout is available, you MUST
use read_file and search_code to verify findings before you comment. Prefer a
few verified comments over many speculative ones. Empty array [] is better than
a wrong comment that wastes the author's time.

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
- Only comment on real issues: bugs, security, broken logic, missing or wrong tests for risky changes.
- Do NOT invent speculative "might break" findings.
- Do NOT claim a test mismatch, missing mock expectation, wrong call order, or broken caller
  unless you opened the relevant test/helper file (or search proved it) in this review.
- If the diff changes production code that has nearby *_test.* / *Test* files, open those
  tests before commenting about tests.
- Do NOT comment on style-only nits unless severe.
- Empty array [] is fine if the PR looks sound after checking.
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


def _changed_paths(files: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for f in files[:_MAX_FILES]:
        path = str(f.get("filename") or f.get("path") or "").strip()
        if path:
            paths.append(path)
    return paths


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

    paths = _changed_paths(files)
    path_hint = "\n".join(f"- {p}" for p in paths[:25])
    if checkout_path:
        checkout_note = (
            "A local PR/MR head checkout is available (the branch tip was already "
            "cloned when this PR was added). You MUST use read_file / search_code "
            "to verify any claim about tests, mocks, callers, or helpers before "
            "including it in the JSON. Start by searching or reading the tests "
            "that cover the changed files below. Do not return comments about "
            "test mismatches until those files are open."
        )
    else:
        checkout_note = (
            "No local checkout is available. Review from the diff only. "
            "Do not invent test or caller failures you cannot verify. "
            "Prefer [] over speculative comments."
        )
    user_msg = (
        f"PR title: {title or '(untitled)'}\n"
        f"{checkout_note}\n\n"
        f"Changed paths:\n{path_hint or '(none listed)'}\n\n"
        f"Diff (changed files only):\n\n{blob}\n\n"
        "After any required tool use, return the JSON array of suggestions."
    )

    raw, used = await run_with_checkout_tools(
        system=_SYSTEM,
        user_message=user_msg,
        checkout_path=checkout_path,
        model_id=mid,
        max_tokens=8192,
        max_rounds=_REVIEW_TOOL_ROUNDS,
    )
    suggestions = _filter_known_paths(_parse_suggestions(raw), files)
    return suggestions, used
