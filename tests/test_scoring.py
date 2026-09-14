"""Тесты deterministic-скоринга."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from superteam_agent.config import UNKNOWN, VERIFIED_OPEN
from superteam_agent.scoring import (
    AGENT_ACCESS_SCORES,
    competition_info,
    estimate_difficulty,
    estimated_fit,
    normalize_agent_access,
    reward_info,
    score_listing,
    time_info,
    token_from_reward,
)


def make_entry(**overrides) -> dict:
    entry = {
        "title": "Scrape public data with Python",
        "description": "Build a Python scraper using requests and pandas.",
        "verification_status": VERIFIED_OPEN,
        "deadline": "2030-01-01T00:00:00Z",
        "has_winners": False,
        "reward": "500 USDC",
        "reward_amount": 500,
        "token": "USDC",
        "agent_access": "AGENT_ONLY",
        "region": "Global",
        "region_text": "",
        "submissions": 5,
    }
    entry.update(overrides)
    return entry


def test_candidate_score_and_decision(monkeypatch):
    monkeypatch.delenv("SUPERTEAM_USER_REGION", raising=False)
    monkeypatch.delenv("SUPERTEAM_USER_COUNTRY", raising=False)

    result = score_listing(make_entry())

    assert result["final_decision"] == "CANDIDATE"
    assert result["decision"] == "CANDIDATE"
    assert result["exclusion_reason"] == ""
    breakdown = result["score_breakdown"]
    assert breakdown["reward_score"] == 35
    assert breakdown["agent_score"] == AGENT_ACCESS_SCORES["AGENT_ONLY"]
    assert breakdown["tech_score"] == 30
    assert breakdown["difficulty_score"] == 5
    assert breakdown["competition_score"] == 10
    assert breakdown["risk_penalty"] == 0
    assert breakdown["region_penalty"] == 0
    assert result["score"] == sum(breakdown.values())
    assert result["priority"] == "HIGH"
    assert result["estimated_fit"] == "EXCELLENT"
    assert result["eligibility_status"] == "ELIGIBLE"
    assert result["agent_access"] == "AGENT_ONLY"
    assert "python" in result["skills"]


def test_closed_card_excluded(monkeypatch):
    monkeypatch.delenv("SUPERTEAM_USER_REGION", raising=False)
    result = score_listing(make_entry(verification_status="CLOSED"))
    assert result["final_decision"] == "EXCLUDE"
    assert "CLOSED" in result["exclusion_reason"]


def test_deadline_not_confirmed_excluded(monkeypatch):
    monkeypatch.delenv("SUPERTEAM_USER_REGION", raising=False)
    result = score_listing(make_entry(deadline=""))
    assert result["final_decision"] == "EXCLUDE"
    assert "deadline" in result["exclusion_reason"].lower()


def test_winners_excluded(monkeypatch):
    monkeypatch.delenv("SUPERTEAM_USER_REGION", raising=False)
    result = score_listing(make_entry(has_winners=True))
    assert result["final_decision"] == "EXCLUDE"
    assert "winners" in result["exclusion_reason"]


def test_human_only_penalized_but_not_excluded(monkeypatch):
    monkeypatch.delenv("SUPERTEAM_USER_REGION", raising=False)
    result = score_listing(make_entry(agent_access="HUMAN_ONLY"))
    assert result["agent_access"] == "HUMAN_ONLY"
    assert result["score_breakdown"]["agent_score"] == -100
    assert result["final_decision"] == "CANDIDATE"
    assert result["estimated_fit"] == "WEAK"


def test_financial_hard_exclusion(monkeypatch):
    monkeypatch.delenv("SUPERTEAM_USER_REGION", raising=False)
    result = score_listing(
        make_entry(
            description_full="You must complete 50 qualifying trades on mainnet to earn the reward."
        )
    )
    assert result["final_decision"] == "EXCLUDE"
    assert "REAL_FINANCIAL_ACTIVITY_REQUIRED" in result["exclusion_reasons"]
    assert result["requires_real_mainnet_activity"] is True


def test_region_restricted_without_user_region(monkeypatch):
    monkeypatch.delenv("SUPERTEAM_USER_REGION", raising=False)
    monkeypatch.delenv("SUPERTEAM_USER_COUNTRY", raising=False)
    result = score_listing(make_entry(region="Thailand"))
    assert result["eligibility_status"] == "REGION_RESTRICTED"
    assert result["score_breakdown"]["region_penalty"] == -15
    assert result["final_decision"] == "CANDIDATE"


def test_region_incompatible_with_user_region(monkeypatch):
    monkeypatch.setenv("SUPERTEAM_USER_REGION", "Ukraine")
    result = score_listing(make_entry(region="Thailand"))
    assert result["final_decision"] == "EXCLUDE"
    assert "region" in result["exclusion_reason"]


def test_region_match_with_user_region(monkeypatch):
    monkeypatch.setenv("SUPERTEAM_USER_REGION", "Thailand")
    result = score_listing(make_entry(region="Thailand"))
    assert result["eligibility_status"] == "ELIGIBLE"
    assert result["score_breakdown"]["region_penalty"] == 0


def test_normalize_agent_access():
    assert normalize_agent_access("") == "UNKNOWN"
    assert normalize_agent_access("agent only") == "AGENT_ONLY"
    assert normalize_agent_access("Agent-Allowed") == "AGENT_ALLOWED"
    assert normalize_agent_access("agent_eligible") == "AGENT_ALLOWED"
    assert normalize_agent_access("Human") == "HUMAN_ONLY"
    assert normalize_agent_access(None) == "UNKNOWN"


def test_token_from_reward():
    assert token_from_reward("3 500 USDG") == "USDG"
    assert token_from_reward("") == ""
    assert token_from_reward("500 USDC") == "USDC"


def test_reward_info():
    usdc = reward_info({"token": "USDC", "reward_amount": 500, "reward": "500 USDC"})
    assert usdc["reward_score"] == 35
    assert usdc["reward_type"] == "crypto"

    fiat = reward_info({"token": "USD", "reward_amount": 100, "reward": "100 USD"})
    assert fiat["reward_score"] == 0
    assert fiat["reward_type"] == "fiat"

    unknown = reward_info({"token": "", "reward_amount": None, "reward": "500"})
    assert unknown["reward_type"] == "UNKNOWN"


def test_competition_info():
    assert competition_info(None)["competition_score"] == 0
    assert competition_info(5)["competition_score"] == 10
    assert competition_info(20)["competition_score"] == 5
    assert competition_info(50)["competition_score"] == 0
    assert competition_info(150)["competition_score"] == -10


def test_time_info():
    now = datetime.now(timezone.utc)
    assert time_info(now + timedelta(days=10), now)["time_score"] == 0
    assert time_info(now + timedelta(days=4), now)["time_score"] == -5
    assert time_info(now + timedelta(days=1), now)["time_score"] == -10
    assert time_info(now + timedelta(hours=12), now)["time_score"] == -20
    assert time_info(None, now)["time_score"] == 0


def test_estimate_difficulty():
    assert estimate_difficulty("Quick and easy bug fix.")["difficulty"] == "EASY"
    assert estimate_difficulty("Rust smart contract on Solana.")["difficulty"] == "HARD"
    assert estimate_difficulty("Implement the backend service.")["difficulty"] == "MEDIUM"
    assert estimate_difficulty("")["difficulty"] == "UNKNOWN"


def test_estimated_fit():
    assert estimated_fit(80) == "EXCELLENT"
    assert estimated_fit(50) == "GOOD"
    assert estimated_fit(25) == "FAIR"
    assert estimated_fit(10) == "WEAK"
    assert estimated_fit(-20) == "WEAK"


def test_unknown_verification_excluded(monkeypatch):
    monkeypatch.delenv("SUPERTEAM_USER_REGION", raising=False)
    result = score_listing(make_entry(verification_status=UNKNOWN))
    assert result["final_decision"] == "EXCLUDE"
