"""AI diagnosis of a failed CI job from log (+ optional test report / artifacts).

May optionally read/search the PR/MR head checkout when more code context is needed.
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
_MAX_LOG_CHARS = 80_000

_SYSTEM = """You diagnose CI / pipeline job failures.
Primary evidence: job log, optional test-report text, optional job artifact excerpts.
You MAY call read_file or search_code on the PR/MR head checkout only when that
evidence is not enough (e.g. open a failing e2e test or the code under test).
Do not browse the whole repo. Prefer log/junit/artifacts first.
Return ONLY a JSON object (no markdown fences):
{
  "root_cause": "one clear sentence",
  "where": "file:line or test name, or empty string",
  "evidence": "short quote from the log, artifact, or code (1-3 lines)",
  "severity": "high" | "medium" | "low",
  "summary": "2-4 sentences explaining what failed and why",
  "suggested_comment": "optional review comment for the PR author, or empty string",
  "comment_path": "repo-relative path if the failure maps to a source file, else empty",
  "comment_line": number or null
}

Rules:
- Prefer the first real failure (assertion, compile error, panic), not setup noise.
- Prefer evidence from junit / test-result artifacts when they exist.
- Do not invent files or tests not present in the log/report/artifacts/checkout reads.
- If the log is incomplete, say what is known and what is missing.
- Keep suggested_comment actionable and polite; empty if nothing useful to post.
"""


def _parse_diagnosis(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {
            "root_cause": "Could not parse AI diagnosis",
            "where": "",
            "evidence": text[:500],
            "severity": "medium",
            "summary": text[:1500],
            "suggested_comment": "",
            "comment_path": "",
            "comment_line": None,
        }
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {
            "root_cause": "Could not parse AI diagnosis",
            "where": "",
            "evidence": "",
            "severity": "medium",
            "summary": text[:1500],
            "suggested_comment": "",
            "comment_path": "",
            "comment_line": None,
        }
    if not isinstance(data, dict):
        data = {}

    line_raw = data.get("comment_line")
    comment_line: int | None
    try:
        comment_line = int(line_raw) if line_raw is not None and str(line_raw).strip() != "" else None
        if comment_line is not None and comment_line < 1:
            comment_line = None
    except (TypeError, ValueError):
        comment_line = None

    sev = str(data.get("severity") or "medium").lower()
    if sev not in ("high", "medium", "low"):
        sev = "medium"

    return {
        "root_cause": str(data.get("root_cause") or "").strip()[:500] or "Unknown failure",
        "where": str(data.get("where") or "").strip()[:300],
        "evidence": str(data.get("evidence") or "").strip()[:1200],
        "severity": sev,
        "summary": str(data.get("summary") or "").strip()[:2500],
        "suggested_comment": str(data.get("suggested_comment") or "").strip()[:2000],
        "comment_path": str(data.get("comment_path") or "").strip()[:500],
        "comment_line": comment_line,
    }


async def diagnose_ci_failure(
    *,
    job_name: str,
    job_status: str,
    log_text: str,
    test_report_text: str = "",
    artifacts_text: str = "",
    web_url: str = "",
    checkout_path: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Return (diagnosis, checkout paths/tools used)."""
    log = (log_text or "").strip()
    if len(log) > _MAX_LOG_CHARS:
        log = "…(truncated)\n" + log[-_MAX_LOG_CHARS:]
    report = (test_report_text or "").strip()[:20_000]
    artifacts = (artifacts_text or "").strip()[:40_000]

    if not log and not report and not artifacts:
        return (
            {
                "root_cause": "No job log, test report, or artifacts available",
                "where": "",
                "evidence": "",
                "severity": "medium",
                "summary": "Orbit could not fetch a log or artifacts for this job.",
                "suggested_comment": "",
                "comment_path": "",
                "comment_line": None,
            },
            [],
        )

    mid = _DEFAULT_MODEL
    if mid not in AVAILABLE_MODELS:
        mid = next(iter(AVAILABLE_MODELS), _DEFAULT_MODEL)

    checkout_note = (
        "A local PR/MR head checkout is available via read_file / search_code. "
        "Use those tools only if log/artifacts are not enough."
        if checkout_path
        else "No local checkout is available; diagnose from log/report/artifacts only."
    )
    user_msg = (
        f"Job name: {job_name}\n"
        f"Status: {job_status}\n"
        f"URL: {web_url or '(none)'}\n"
        f"{checkout_note}\n\n"
        f"--- Job log (tail) ---\n{log or '(empty)'}\n\n"
        f"--- Test report excerpt ---\n{report or '(none)'}\n\n"
        f"--- Job artifact excerpts ---\n{artifacts or '(none)'}\n\n"
        "Return the JSON diagnosis now (after any optional tool use)."
    )

    raw, used = await run_with_checkout_tools(
        system=_SYSTEM,
        user_message=user_msg,
        checkout_path=checkout_path,
        model_id=mid,
        max_tokens=4096,
    )
    return _parse_diagnosis(raw), used
