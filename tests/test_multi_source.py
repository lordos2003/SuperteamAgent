"""Тесты дедупликации, классификации и ранжирования multi-source поиска."""
from __future__ import annotations

from typing import Any

from superteam_agent.config import (
    BOUNTY_CLOSED,
    BOUNTY_VERIFIED_OPEN,
    PAYMENT_TYPE_CRYPTO,
    PAYMENT_TYPE_FIAT,
)
from superteam_agent.core.ranking import rank_score, sort_candidates
from superteam_agent.multi_source import build_report, classify, deduplicate
from superteam_agent.sources.base import SourceResult


def make_entry(url: str, source: str, **overrides: Any) -> dict[str, Any]:
    """Запись задачи с полями, которые используют дедупликация и классификация."""
    entry: dict[str, Any] = {
        "source": source,
        "primary_source": source,
        "sources": [source],
        "title": "Fix the CSV export bug",
        "url": url,
        "status": "OPEN",
        "bounty_status": "AVAILABLE",
        "verified_status": BOUNTY_VERIFIED_OPEN,
        "verified_at": "2026-09-15T00:00:00Z",
        "reward_amount": 25.0,
        "reward_currency": "USDC",
        "payment_type": PAYMENT_TYPE_CRYPTO,
        "financial_risk": "LOW",
        "region": "Global",
        "difficulty": "EASY",
        "estimated_time": "1-3 hours",
        "tech_stack": ["python"],
        "tech_priority": 0,
        "beginner_friendly": True,
        "human_only": False,
        "agent_compatible": True,
        "secondary": False,
        "exclusion_reasons": [],
        "exclusion_tag": "",
        "manual_check_reasons": [],
        "evidence": [f"discovered via {source}"],
        "notes": [],
    }
    entry.update(overrides)
    return entry


def test_deduplicate_merges_same_github_issue():
    issue = "https://github.com/example/repo/issues/7"
    merged = deduplicate(
        [
            make_entry(issue, "github"),
            make_entry(issue, "opire", dashboard_url="https://api.opire.dev/rewards"),
            make_entry(issue, "bountybureau", dashboard_url="https://bountybureau.com/api/bounties"),
        ]
    )
    assert len(merged) == 1
    entry = merged[0]
    assert sorted(entry["sources"]) == ["bountybureau", "github", "opire"]
    # Приоритет источников: bountybureau авторитетнее github/opire
    assert entry["primary_source"] == "bountybureau"
    assert entry["evidence"]


def test_deduplicate_keeps_different_issues_separate():
    merged = deduplicate(
        [
            make_entry("https://github.com/example/repo/issues/7", "github"),
            make_entry("https://github.com/example/repo/issues/8", "github"),
            make_entry("https://superteam.fun/earn/listing/some-slug", "superteam"),
        ]
    )
    assert len(merged) == 3


def test_deduplicate_prefers_stricter_verification_status():
    issue = "https://github.com/example/repo/issues/9"
    merged = deduplicate(
        [
            make_entry(issue, "opire"),
            make_entry(
                issue, "github", verified_status=BOUNTY_CLOSED, exclusion_reasons=["CLOSED"]
            ),
        ]
    )
    assert len(merged) == 1
    assert merged[0]["verified_status"] == BOUNTY_CLOSED
    assert "CLOSED" in merged[0]["exclusion_reasons"]
    assert sorted(merged[0]["sources"]) == ["github", "opire"]


def test_classify_places_entries_into_expected_buckets():
    buckets = classify(
        [
            make_entry("https://github.com/a/b/issues/1", "github"),
            make_entry("https://github.com/a/b/issues/2", "github", human_only=True),
            make_entry("https://github.com/a/b/issues/3", "github", exclusion_reasons=["CLOSED"]),
            make_entry(
                "https://github.com/a/b/issues/4",
                "github",
                manual_check_reasons=["REGION_UNKNOWN_MANUAL_CHECK"],
            ),
            make_entry("https://github.com/a/b/issues/5", "github", secondary=True),
            make_entry("https://github.com/a/b/issues/6", "github", agent_compatible=False),
        ]
    )

    def numbers(bucket: str) -> list[str]:
        return [str(item["url"]).rsplit("/", 1)[-1] for item in buckets[bucket]]

    assert numbers("top_agent_compatible") == ["1"]
    assert numbers("top_human_only") == ["2"]
    assert numbers("excluded") == ["3"]
    assert numbers("needs_manual_check") == ["4"]
    assert numbers("secondary_candidates") == ["5"]
    # задача без agent_compatible и без причин никуда не распределяется
    assert all(buckets["top_agent_compatible"][0]["url"] != item["url"] for item in buckets["excluded"])


def test_rank_score_prefers_crypto_no_risk_beginner():
    strong = make_entry("https://github.com/a/b/issues/1", "github")
    weak = make_entry(
        "https://github.com/a/b/issues/2",
        "github",
        payment_type=PAYMENT_TYPE_FIAT,
        reward_currency="USD",
        financial_risk="MEDIUM",
        beginner_friendly=False,
        difficulty="HARD",
        tech_stack=["backend"],
        tech_priority=10,
        region="UNKNOWN",
    )
    assert rank_score(strong) > rank_score(weak)
    ordered = sort_candidates([weak, strong])
    assert ordered[0]["url"] == strong["url"]


def test_build_report_has_required_sections():
    buckets = classify([make_entry("https://github.com/a/b/issues/1", "github")])
    report = build_report(
        [
            SourceResult(
                name="github",
                source_status="OK",
                discovered=10,
                verified_open=3,
                items=buckets["all_verified"],
                diagnostics={"token_present": True},
                checked_at="2026-09-15T00:00:00Z",
            )
        ],
        buckets,
    )
    assert set(report) >= {
        "generated_at",
        "sources",
        "all_verified",
        "top_agent_compatible",
        "top_human_only",
        "excluded",
        "counts",
    }
    assert report["sources"]["github"]["verified_open"] == 3
    assert report["counts"]["top_agent_compatible"] == 1
    assert report["all_verified"][0]["url"] == "https://github.com/a/b/issues/1"