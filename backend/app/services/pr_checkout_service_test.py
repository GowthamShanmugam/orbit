"""Lightweight tests for PR checkout helpers (no network / git)."""

from __future__ import annotations

from app.services.pr_checkout_service import _normalize_repo_key, _repo_keys_match
from app.services.session_layer_prompt import _parse_github_pr, _parse_gitlab_mr


def test_parse_github_pr() -> None:
    assert _parse_github_pr("https://github.com/acme/widgets/pull/42") == (
        "acme",
        "widgets",
        42,
    )


def test_parse_gitlab_mr() -> None:
    assert _parse_gitlab_mr(
        "https://gitlab.com/group/sub/project/-/merge_requests/7"
    ) == ("group/sub/project", 7)


def test_repo_keys_match_github() -> None:
    assert _repo_keys_match("https://github.com/acme/widgets.git", "acme/widgets")
    assert _normalize_repo_key("https://github.com/acme/widgets") == "acme/widgets"


def test_repo_keys_match_gitlab_nested() -> None:
    assert _repo_keys_match(
        "https://gitlab.example.com/group/sub/project.git",
        "group/sub/project",
    )
