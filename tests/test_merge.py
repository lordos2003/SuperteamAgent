"""Тесты объединения источников Agent API и публичного сайта."""
from __future__ import annotations

from superteam_agent.website import merge_sources


def api_item(slug: str, **overrides) -> dict:
    item = {
        "slug": slug,
        "title": "API title",
        "type": "bounty",
        "reward": "500 USDC",
        "reward_amount": 500,
        "token": "USDC",
        "status": "OPEN",
        "deadline": "2030-01-01T00:00:00Z",
        "agent_access": "AGENT_ONLY",
        "region": "",
        "winners_flagged": False,
        "winners_announced_at": "",
        "source": "agent_api",
        "source_url": "https://superteam.fun/api/agents/listings/live",
    }
    item.update(overrides)
    return item


def website_item(slug: str, **overrides) -> dict:
    return api_item(
        slug,
        source="website",
        source_url="https://superteam.fun/api/listings/",
        **overrides,
    )


def test_merge_same_slug_sets_both_flags():
    merged = merge_sources([api_item("s1")], [website_item("s1", title="Website title")])
    assert len(merged) == 1
    entry = merged[0]
    assert entry["source_api"] is True
    assert entry["source_website"] is True
    assert entry["sources"] == ["agent_api", "website"]
    assert entry["api_status"] == "OPEN"
    assert entry["website_status"] == "OPEN"


def test_merge_keeps_api_order_first():
    merged = merge_sources([api_item("api-only")], [website_item("web-only")])
    assert [item["slug"] for item in merged] == ["api-only", "web-only"]
    assert merged[0]["source_api"] is True and merged[0]["source_website"] is False
    assert merged[1]["source_api"] is False and merged[1]["source_website"] is True


def test_merge_fills_empty_fields_from_website():
    merged = merge_sources(
        [api_item("s1", title="", reward="", region="")],
        [website_item("s1", title="Real title", reward="200 SOL", region="Global")],
    )
    entry = merged[0]
    assert entry["title"] == "Real title"
    assert entry["reward"] == "200 SOL"
    assert entry["region"] == "Global"


def test_merge_does_not_overwrite_existing_api_values():
    merged = merge_sources(
        [api_item("s1", title="API wins")],
        [website_item("s1", title="Website loses")],
    )
    assert merged[0]["title"] == "API wins"
    assert merged[0]["website_reward"] == "500 USDC"


def test_merge_skips_empty_slugs():
    merged = merge_sources(
        [api_item("", title="no slug"), api_item("ok")],
        [website_item("", title="no slug")],
    )
    assert [item["slug"] for item in merged] == ["ok"]


def test_merge_keeps_api_agent_access_and_extra_fields():
    merged = merge_sources([api_item("s1")], [website_item("s1")])
    entry = merged[0]
    assert entry["agent_access"] == "AGENT_ONLY"
    assert entry["api_agent_access"] == "AGENT_ONLY"
    assert entry["api_deadline"] == "2030-01-01T00:00:00Z"
    assert entry["website_deadline"] == "2030-01-01T00:00:00Z"
