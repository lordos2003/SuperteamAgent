"""Тесты верификации первоисточника GitHub issue через httpx.MockTransport.

Живой API не используется: transport возвращает фикстурные ответы. Проверяются
именно правила задания: closed/assigned/merged PR/claimed-paid, отсутствие
награды и rate limit.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from superteam_agent.config import (
    BOUNTY_ASSIGNED,
    BOUNTY_CLAIMED,
    BOUNTY_CLOSED,
    BOUNTY_NOT_FOUND,
    BOUNTY_PR_LINKED,
    BOUNTY_RATE_LIMITED,
    BOUNTY_VERIFIED_OPEN,
    GITHUB_API_BASE,
)
from superteam_agent.core.verification import parse_github_url, verify_github_issue


def issue_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "state": "open",
        "state_reason": None,
        "title": "Bug bounty $25 for the CSV export fix",
        "body": "Fix the CSV export of the Python scraper and add a regression test.",
        "locked": False,
        "comments": 0,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-10T00:00:00Z",
        "closed_at": None,
        "labels": [{"name": "bounty"}],
        "assignees": [],
        "assignee": None,
    }
    payload.update(overrides)
    return payload


def client_with(
    routes: dict[str, tuple[int, Any]], *, headers: dict[str, str] | None = None
) -> httpx.AsyncClient:
    """Клиент с фикстурными ответами по путям (query-строка игнорируется)."""

    def handler(request: httpx.Request) -> httpx.Response:
        status, payload = routes.get(request.url.path, (404, {"message": "Not Found"}))
        if isinstance(payload, (dict, list)):
            return httpx.Response(status, json=payload, headers=headers or {})
        return httpx.Response(status, text=str(payload), headers=headers or {})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def verify(routes: dict[str, tuple[int, Any]], **kwargs: Any) -> dict[str, Any]:
    """Прогнать верификацию issue example/repo#1 на фикстурах."""
    called = dict(kwargs)

    async def run() -> dict[str, Any]:
        headers = called.pop("headers", None)
        async with client_with(routes, headers=headers) as client:
            return await verify_github_issue(client, "example", "repo", 1, **called)

    return asyncio.run(run())


def repo_route() -> tuple[int, Any]:
    return (200, {"stargazers_count": 100, "language": "Python", "archived": False})


def test_parse_github_url():
    assert parse_github_url("https://github.com/owner/repo/issues/12") == ("owner", "repo", 12)
    assert parse_github_url("https://github.com/owner/repo/pull/7") == ("owner", "repo", 7)
    assert parse_github_url("https://gitlab.com/owner/repo/issues/1") is None
    assert parse_github_url("") is None


def test_open_issue_with_reward_is_verified_open():
    routes = {
        "/repos/example/repo/issues/1": (200, issue_payload()),
        "/repos/example/repo/issues/1/comments": (200, []),
        "/repos/example/repo/issues/1/timeline": (200, []),
        "/repos/example/repo": repo_route(),
    }
    result = verify(routes)
    assert result["verified_status"] == BOUNTY_VERIFIED_OPEN
    assert result["reward_amount"] == 25.0
    assert result["reward_currency"] == "USD"
    assert result["assignees"] == []


def test_closed_issue_is_excluded():
    routes = {
        "/repos/example/repo/issues/1": (
            200,
            issue_payload(state="closed", state_reason="completed"),
        ),
        "/repos/example/repo/issues/1/comments": (200, []),
        "/repos/example/repo/issues/1/timeline": (200, []),
        "/repos/example/repo": repo_route(),
    }
    assert verify(routes)["verified_status"] == BOUNTY_CLOSED


def test_assigned_issue_is_excluded():
    routes = {
        "/repos/example/repo/issues/1": (200, issue_payload(assignees=[{"login": "somebody"}])),
        "/repos/example/repo/issues/1/comments": (200, []),
        "/repos/example/repo/issues/1/timeline": (200, []),
        "/repos/example/repo": repo_route(),
    }
    result = verify(routes)
    assert result["verified_status"] == BOUNTY_ASSIGNED
    assert result["assignee"] == "somebody"


def test_merged_pull_request_marks_bounty_as_taken():
    routes = {
        "/repos/example/repo/issues/1": (200, issue_payload()),
        "/repos/example/repo/issues/1/comments": (200, []),
        "/repos/example/repo/issues/1/timeline": (
            200,
            [
                {
                    "event": "cross-referenced",
                    "source": {"issue": {"number": 42, "pull_request": {"url": "x"}}},
                }
            ],
        ),
        "/repos/example/repo/pulls/42": (
            200,
            {
                "number": 42,
                "state": "closed",
                "merged": True,
                "html_url": "https://github.com/example/repo/pull/42",
            },
        ),
        "/repos/example/repo": repo_route(),
    }
    result = verify(routes)
    assert result["verified_status"] == BOUNTY_PR_LINKED
    assert result["linked_prs"][0]["merged"] is True


def test_paid_marker_in_comments_marks_bounty_claimed():
    routes = {
        "/repos/example/repo/issues/1": (200, issue_payload()),
        "/repos/example/repo/issues/1/comments": (
            200,
            [{"body": "Good news: this bounty has been paid to the contributor."}],
        ),
        "/repos/example/repo/issues/1/timeline": (200, []),
        "/repos/example/repo": repo_route(),
    }
    result = verify(routes)
    assert result["verified_status"] == BOUNTY_CLAIMED
    assert result["paid_markers"]


def test_reward_from_bounty_platform_comment():
    routes = {
        "/repos/example/repo/issues/1": (200, issue_payload(title="Implement the CSV export fix")),
        "/repos/example/repo/issues/1/comments": (
            200,
            [
                {
                    "body": (
                        "### Bounty Alert!\n\nA bounty of $5000.00 has been created by someone on "
                        "BountyHub for this issue."
                    )
                }
            ],
        ),
        "/repos/example/repo/issues/1/timeline": (200, []),
        "/repos/example/repo": repo_route(),
    }
    result = verify(routes)
    assert result["verified_status"] == BOUNTY_VERIFIED_OPEN
    assert result["reward_amount"] == 5000.0
    assert result["reward_currency"] == "USD"


def test_missing_issue_returns_not_found():
    routes = {"/repos/example/repo": repo_route()}
    assert verify(routes)["verified_status"] == BOUNTY_NOT_FOUND


def test_rate_limit_is_reported_honestly():
    routes = {"/repos/example/repo/issues/1": (403, {"message": "API rate limit exceeded"})}
    result = verify(routes, headers={"x-ratelimit-remaining": "0"})
    assert result["verified_status"] == BOUNTY_RATE_LIMITED
    assert "rate limit" in result["error"].lower()


def test_aggregator_post_markers_are_detected():
    routes = {
        "/repos/example/repo/issues/1": (
            200,
            issue_payload(title="[radar] SN open bounty 2026-09-14"),
        ),
        "/repos/example/repo/issues/1/comments": (200, []),
        "/repos/example/repo/issues/1/timeline": (200, []),
        "/repos/example/repo": repo_route(),
    }
    assert verify(routes)["aggregator_markers"]


def test_no_reward_amount_is_reported_as_none():
    routes = {
        "/repos/example/repo/issues/1": (200, issue_payload(title="Improve the docs")),
        "/repos/example/repo/issues/1/comments": (200, []),
        "/repos/example/repo/issues/1/timeline": (200, []),
        "/repos/example/repo": repo_route(),
    }
    result = verify(routes)
    assert result["reward_amount"] is None
    assert result["reward_currency"] == ""