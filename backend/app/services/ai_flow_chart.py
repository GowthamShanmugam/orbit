"""Build a small Mermaid flowchart for a changed function / file region."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.services.ai_checkout_tools import run_with_checkout_tools
from app.services.ai_service import AVAILABLE_MODELS

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_MAX_SNIPPET_CHARS = 12_000
_MAX_PATCH_CHARS = 6_000

_NO_FLOW_MSG = "No control flow in this region — mostly declarations."

_FUNC_START = re.compile(
    r"^("
    r"export\s+(?:default\s+)?(?:async\s+)?function\s+\w+"
    r"|export\s+(?:default\s+)?(?:async\s+)?(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?(?:function|\()"
    r"|(?:export\s+)?(?:async\s+)?function\s+\w+"
    r"|(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+\w+"
    r"|func\s+(?:\([^)]*\)\s*)?\w+"
    r"|def\s+\w+"
    r"|class\s+\w+"
    r"|impl(?:\s*<[^>]*>)?\s+\w+"
    r")",
    re.MULTILINE,
)

_CONTROL_FLOW = re.compile(
    r"(?m)^\s*(?:"
    r"if\b|else\b|elif\b|for\b|while\b|switch\b|select\b|case\b|default\s*:"
    r"|match\b|try\b|catch\b|except\b|finally\b|return\b|throw\b|raise\b"
    r"|go\b|defer\b|break\b|continue\b|when\b|loop\b|yield\b"
    r")"
)

_DECL_LINE = re.compile(
    r"(?m)^\s*(?:"
    r"package\b|import\b|from\b|export\s+(?:type|const|enum|interface|type)\b|"
    r"const\b|var\b|type\b|typedef\b|interface\b|enum\b|struct\b|"
    r"#include\b|using\b|pub\s+use\b|use\b"
    r")"
)

# Go/typed const entries inside const ( ... ): Name Type = "value"
_TYPED_ASSIGN = re.compile(
    r"^[A-Za-z_][\w.]*\s+"
    r"(?:\*+)?(?:\[\]|\*+|map\[|chan\s+|func\(|string|int\d*|uint\d*|bool|byte|rune|float\d*|error|any|complex\d*)"
)

_SYSTEM = """You draw a compact control-flow diagram for a code review.

Return ONLY a Mermaid flowchart (no markdown fences, no prose before/after).
Use flowchart TD. Keep it small: about 6–16 nodes.
Focus on branches (if/else/switch/match), loops, early returns, and errors.
Node labels: short plain words, no quotes, no parentheses, no HTML.
If the diff patch is provided, mark changed steps with a trailing * in the label.
Do not invent callers, init functions, regex compilation, or any logic that is not
literally in the snippet.
If the snippet has no meaningful control flow (only constants, types, imports, or
data declarations), reply with exactly: NO_FLOW
Do not include style/classDef blocks.
"""


def _code_lines(snippet: str) -> list[str]:
    out: list[str] = []
    for line in snippet.splitlines():
        s = line.strip()
        if not s or s.startswith("//") or s.startswith("#") or s.startswith("/*") or s.startswith("*"):
            continue
        if s in ("(", ")", "{", "}", "};", "),", "const (", "var (", "type ("):
            continue
        out.append(s)
    return out


def _control_flow_hits(snippet: str) -> int:
    return sum(1 for line in _code_lines(snippet) if _CONTROL_FLOW.match(line))


def _is_mostly_declarations(snippet: str) -> bool:
    """True when the region is consts/types/imports with little/no branching."""
    lines = _code_lines(snippet)
    if not lines:
        return True
    hits = _control_flow_hits(snippet)
    if hits >= 2:
        return False
    if hits == 1 and len(lines) <= 12:
        # Small function with a single branch — still useful.
        return False

    decl = 0
    for line in lines:
        if _DECL_LINE.match(line) or _TYPED_ASSIGN.match(line):
            decl += 1
            continue
        # Plain assignments / string consts: NAME = "x" or NAME = 1
        if re.match(r"^[A-Za-z_][\w.]*\s*=\s*", line):
            decl += 1
            continue
        # export const FOO = ... without function
        if re.match(r"^export\s+const\s+\w+\s*=", line) and "=>" not in line and "function" not in line:
            decl += 1
    if hits == 0 and decl >= max(2, int(0.6 * len(lines))):
        return True
    if hits == 0 and decl >= 3 and decl >= len(lines) - 2:
        return True
    return hits == 0 and len(lines) <= 4 and decl >= 1


def _extract_snippet(
    content: str,
    *,
    focus_line: int | None,
) -> tuple[str, int, int, str]:
    """Return (snippet, start_line, end_line, label). Lines are 1-based inclusive."""
    if not content.strip():
        return "", 1, 1, "empty"

    lines = content.splitlines()
    n = len(lines)
    focus = focus_line if focus_line and 1 <= focus_line <= n else None

    starts: list[int] = []
    for m in _FUNC_START.finditer(content):
        line_no = content.count("\n", 0, m.start()) + 1
        starts.append(line_no)

    chosen_start = 1
    chosen_end = n
    label = "file"

    if starts:
        if focus is not None:
            before = [s for s in starts if s <= focus]
            chosen_start = before[-1] if before else starts[0]
        else:
            chosen_start = starts[0]
        after = [s for s in starts if s > chosen_start]
        chosen_end = (after[0] - 1) if after else n
        header = lines[chosen_start - 1].strip()
        label = header[:80] if header else f"lines {chosen_start}-{chosen_end}"
    elif focus is not None:
        # No function boundary — stay tight around the change.
        chosen_start = max(1, focus - 12)
        chosen_end = min(n, focus + 12)
        label = f"lines {chosen_start}-{chosen_end}"
    else:
        chosen_end = min(n, 80)
        label = f"lines 1-{chosen_end}"

    snippet = "\n".join(lines[chosen_start - 1 : chosen_end])
    if len(snippet) > _MAX_SNIPPET_CHARS:
        snippet = snippet[:_MAX_SNIPPET_CHARS] + "\n…(truncated)"
    return snippet, chosen_start, chosen_end, label


def _parse_mermaid(raw: str) -> str | None:
    """Return Mermaid source, empty string for NO_FLOW, or None if unusable."""
    text = (raw or "").strip()
    if re.fullmatch(r"NO_FLOW", text, flags=re.IGNORECASE):
        return ""
    if text.startswith("```"):
        text = re.sub(r"^```(?:mermaid)?\s*", "", text)
    if re.match(r"(?i)^NO_FLOW\b", text.strip()):
        return ""
    m = re.search(r"(?im)^\s*(flowchart|graph)\b", text)
    if m:
        text = text[m.start() :].lstrip()
    text = re.sub(r"\n?```[\s\S]*$", "", text).strip()
    if re.fullmatch(r"NO_FLOW", text, flags=re.IGNORECASE):
        return ""
    if not re.match(r"(?i)^(flowchart|graph)\b", text):
        return None
    text = re.sub(r"\n\s*classDef\b.*", "", text)
    text = re.sub(r"\n\s*class\s+\w+.*", "", text)
    return text.strip()


async def build_flow_chart(
    *,
    path: str,
    file_content: str,
    patch: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    focus = start_line
    if focus is None and end_line is not None:
        focus = end_line
    snippet, s_line, e_line, label = _extract_snippet(file_content, focus_line=focus)
    if not snippet.strip():
        return {
            "path": path,
            "label": label,
            "start_line": s_line,
            "end_line": e_line,
            "mermaid": "",
            "error": "No code available for this file.",
        }

    if _is_mostly_declarations(snippet):
        return {
            "path": path,
            "label": label,
            "start_line": s_line,
            "end_line": e_line,
            "mermaid": "",
            "error": _NO_FLOW_MSG,
        }

    mid = _DEFAULT_MODEL if _DEFAULT_MODEL in AVAILABLE_MODELS else next(
        iter(AVAILABLE_MODELS), _DEFAULT_MODEL
    )
    patch_clip = (patch or "").strip()
    if len(patch_clip) > _MAX_PATCH_CHARS:
        patch_clip = patch_clip[:_MAX_PATCH_CHARS] + "\n…(truncated)"

    user_msg = (
        f"File: {path}\n"
        f"Region: lines {s_line}-{e_line} ({label})\n\n"
        f"--- Code ---\n{snippet}\n"
    )
    if patch_clip:
        user_msg += f"\n--- Diff patch for this file ---\n{patch_clip}\n"
    user_msg += (
        "\nReturn only the Mermaid flowchart for control flow that appears in the "
        "snippet, or NO_FLOW if there is none."
    )

    raw, _used = await run_with_checkout_tools(
        system=_SYSTEM,
        user_message=user_msg,
        checkout_path=None,
        model_id=mid,
        max_tokens=2048,
        max_rounds=0,
    )
    mermaid = _parse_mermaid(raw)
    if mermaid is None:
        logger.warning("Flow chart model returned unusable Mermaid for %s", path)
        return {
            "path": path,
            "label": label,
            "start_line": s_line,
            "end_line": e_line,
            "mermaid": "",
            "error": "Could not build a flowchart for this region.",
        }
    if mermaid == "":
        return {
            "path": path,
            "label": label,
            "start_line": s_line,
            "end_line": e_line,
            "mermaid": "",
            "error": _NO_FLOW_MSG,
        }
    return {
        "path": path,
        "label": label,
        "start_line": s_line,
        "end_line": e_line,
        "mermaid": mermaid,
        "error": None,
    }
