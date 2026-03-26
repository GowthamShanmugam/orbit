"""Auto-detect secrets and sensitive data in user prompts.

Scans text for known token patterns (GitHub PATs, AWS keys, JWTs, etc.)
and high-entropy strings that are likely secrets.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ScanMatch:
    pattern_name: str
    matched_text: str
    start: int
    end: int
    severity: str  # "high" | "medium" | "low"
    suggestion: str


_PATTERNS: list[tuple[str, re.Pattern[str], str, str]] = [
    (
        "GitHub Personal Access Token",
        re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}"),
        "high",
        "Store this GitHub token in the Secret Vault.",
    ),
    (
        "AWS Access Key",
        re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}"),
        "high",
        "Store this AWS key in the Secret Vault.",
    ),
    (
        "AWS Secret Key",
        re.compile(r"(?:aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*[=:]\s*[A-Za-z0-9/+=]{40}"),
        "high",
        "Store this AWS secret key in the Secret Vault.",
    ),
    (
        "Anthropic API Key",
        re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}"),
        "high",
        "Store this Anthropic API key in the Secret Vault.",
    ),
    (
        "OpenAI API Key",
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
        "high",
        "Store this API key in the Secret Vault.",
    ),
    (
        "Generic API Key assignment",
        re.compile(r"(?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token|bearer)\s*[=:]\s*['\"]?[A-Za-z0-9\-_.]{20,}['\"]?", re.IGNORECASE),
        "medium",
        "This looks like an API key or token. Consider storing it in the Secret Vault.",
    ),
    (
        "JWT Token",
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        "medium",
        "This looks like a JWT. Consider storing it in the Secret Vault.",
    ),
    (
        "Private Key Header",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
        "high",
        "Never paste private keys. Store this in the Secret Vault.",
    ),
    (
        "Connection String",
        re.compile(r"(?:postgres|mysql|mongodb|redis|amqp)(?:ql)?://[^\s]{10,}"),
        "medium",
        "This looks like a connection string with credentials.",
    ),
    (
        "Bearer token in header",
        re.compile(r"[Bb]earer\s+[A-Za-z0-9\-_.~+/]{20,}"),
        "medium",
        "This looks like a bearer token.",
    ),
]

SENSITIVE_FILE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\.env(?:\.[a-z]+)?$", re.IGNORECASE),
    re.compile(r"\.pem$", re.IGNORECASE),
    re.compile(r"\.key$", re.IGNORECASE),
    re.compile(r"credentials\.json$", re.IGNORECASE),
    re.compile(r"service[_-]?account.*\.json$", re.IGNORECASE),
    re.compile(r"\.ssh/", re.IGNORECASE),
    re.compile(r"id_rsa", re.IGNORECASE),
    re.compile(r"\.keystore$", re.IGNORECASE),
    re.compile(r"\.jks$", re.IGNORECASE),
    re.compile(r"\.p12$", re.IGNORECASE),
]

_MIN_ENTROPY = 4.0
_MIN_LENGTH_FOR_ENTROPY = 16


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    length = len(s)
    return -sum((count / length) * math.log2(count / length) for count in freq.values())


def scan_text(text: str) -> list[ScanMatch]:
    """Scan *text* for potential secrets. Returns a list of matches."""
    matches: list[ScanMatch] = []
    seen_spans: set[tuple[int, int]] = set()

    for name, pattern, severity, suggestion in _PATTERNS:
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            if span in seen_spans:
                continue
            seen_spans.add(span)
            matches.append(ScanMatch(
                pattern_name=name,
                matched_text=_mask(m.group()),
                start=m.start(),
                end=m.end(),
                severity=severity,
                suggestion=suggestion,
            ))

    for m in re.finditer(r"[A-Za-z0-9+/=\-_]{16,}", text):
        span = (m.start(), m.end())
        if any(s[0] <= span[0] and span[1] <= s[1] for s in seen_spans):
            continue
        token = m.group()
        if len(token) >= _MIN_LENGTH_FOR_ENTROPY and _shannon_entropy(token) >= _MIN_ENTROPY:
            if not _is_common_word(token):
                matches.append(ScanMatch(
                    pattern_name="High-entropy string",
                    matched_text=_mask(token),
                    start=m.start(),
                    end=m.end(),
                    severity="low",
                    suggestion="This looks like it could be a secret or token.",
                ))

    return matches


def is_sensitive_file(path: str) -> bool:
    """Return True if *path* matches a known sensitive file pattern."""
    return any(p.search(path) for p in SENSITIVE_FILE_PATTERNS)


def _mask(value: str, visible: int = 6) -> str:
    """Partially mask a secret value for display."""
    if len(value) <= visible:
        return "*" * len(value)
    return value[:visible] + "*" * min(len(value) - visible, 20)


def _is_common_word(s: str) -> bool:
    """Heuristic to skip common non-secret base64-ish strings."""
    lower = s.lower()
    return lower in {
        "authorization", "authentication", "content-type",
        "application", "multipart", "undefined",
    }
