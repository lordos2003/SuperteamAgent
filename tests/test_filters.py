"""Тесты политики отбора: финансы, регион, закрытые/занятые задачи, награда.

Проверяются именно известные рискованные/неприемлемые случаи из задания:
real mainnet trading, свои средства, депозит, Russia excluded, closed issue,
assigned issue, claimed bounty, «paid bounty» без суммы.
"""
from __future__ import annotations

from superteam_agent.config import (
    BOUNTY_ASSIGNED,
    BOUNTY_CLAIMED,
    BOUNTY_CLOSED,
    BOUNTY_PR_LINKED,
    BOUNTY_VERIFIED_OPEN,
)
from superteam_agent.core.filters import analyze_region, evaluate
from superteam_agent.core.models import (
    REGION_GLOBAL,
    REGION_RESTRICTED,
    REGION_RUSSIA_EXCLUDED,
    REGION_UNKNOWN,
    new_candidate,
)


def make_verification(verified_status: str = BOUNTY_VERIFIED_OPEN, **overrides) -> dict:
    verification = {
        "verified_status": verified_status,
        "verified_at": "2026-09-15T00:00:00Z",
        "state": "open",
        "reward_amount": None,
        "reward_currency": "",
        "reward_evidence": [],
        "aggregator_markers": [],
        "repo_meta": {},
    }
    verification.update(overrides)
    return verification


def make_candidate(**overrides) -> dict:
    candidate = new_candidate(
        source="github",
        title="Fix CSV export bug in the Python scraper",
        url="https://github.com/example/repo/issues/1",
        description=(
            "Small bug fix: the CSV export of our Python scraper writes the wrong column order. "
            "Add a regression test and update the documentation accordingly."
        ),
        repo="example/repo",
        language="Python",
        labels=["bounty"],
        payment_method="GitHub issue bounty",
    )
    candidate.update(overrides)
    return candidate


def test_open_paid_python_task_is_excluded_only_by_unknown_region():
    """Задача проходит финансы и награду, но неизвестный регион уводит её в manual."""
    result = evaluate(make_candidate(), make_verification(reward_amount=25.0, reward_currency="USDC"))
    assert result["financial_risk"] == "LOW"
    assert result["exclusion_reasons"] == []
    assert "REGION_UNKNOWN_MANUAL_CHECK" in result["manual_check_reasons"]
    assert result["agent_compatible"] is False


def test_global_task_with_crypto_reward_is_agent_compatible():
    result = evaluate(
        make_candidate(
            description=make_candidate()["description"] + " This bounty is open worldwide."
        ),
        make_verification(reward_amount=50.0, reward_currency="USDC"),
    )
    assert result["region"] == REGION_GLOBAL
    assert result["exclusion_reasons"] == []
    assert result["manual_check_reasons"] == []
    assert result["agent_compatible"] is True


def test_real_mainnet_trading_is_hard_excluded():
    result = evaluate(
        make_candidate(
            description=(
                "Complete at least 5 qualifying trades through your agent on Solana Mainnet to earn "
                "the reward. This bounty is open worldwide."
            )
        ),
        make_verification(reward_amount=500.0, reward_currency="USDC"),
    )
    assert result["financial_risk"] == "HIGH"
    assert "REAL_FINANCIAL_ACTIVITY_REQUIRED" in result["exclusion_reasons"]
    assert result["exclusion_tag"] == "[EXCLUDED][FINANCIAL RISK]"
    assert result["agent_compatible"] is False


def test_own_money_requirement_is_excluded_even_with_reward():
    result = evaluate(
        make_candidate(
            description=(
                "You need to use your own funds and deposit 10 USDC before starting the task. "
                "The bounty is open worldwide and pays 100 USDC."
            )
        ),
        make_verification(reward_amount=100.0, reward_currency="USDC"),
    )
    assert result["financial_risk"] == "HIGH"
    assert result["exclusion_reasons"]
    assert result["agent_compatible"] is False


def test_testnet_activity_is_allowed():
    result = evaluate(
        make_candidate(
            description=(
                "Perform 50 simulated trades on testnet and collect the metrics into a CSV report. "
                "This bounty is open worldwide."
            )
        ),
        make_verification(reward_amount=75.0, reward_currency="USDC"),
    )
    assert result["financial_risk"] == "LOW"
    assert result["exclusion_reasons"] == []
    assert result["agent_compatible"] is True


def test_closed_assigned_and_claimed_issues_are_excluded():
    for status, tag in (
        (BOUNTY_CLOSED, "[EXCLUDED][CLOSED]"),
        (BOUNTY_ASSIGNED, "[EXCLUDED][ASSIGNED]"),
        (BOUNTY_PR_LINKED, "[EXCLUDED][PR_LINKED]"),
        (BOUNTY_CLAIMED, "[EXCLUDED][CLAIMED]"),
    ):
        result = evaluate(
            make_candidate(),
            make_verification(status, reward_amount=50.0, reward_currency="USDC"),
        )
        assert result["exclusion_tag"] == tag, status
        assert result["agent_compatible"] is False


def test_paid_bounty_without_amount_is_excluded():
    result = evaluate(make_candidate(), make_verification())
    assert "NO_CONFIRMED_REWARD" in result["exclusion_reasons"]
    assert result["exclusion_tag"] == "[EXCLUDED][NO_REWARD]"


def test_russia_excluded_region_blocks_agent_compatibility():
    result = evaluate(
        make_candidate(
            description=(
                "This bounty is not available in Russia. "
                "Fix the CSV export of the Python scraper and add tests."
            )
        ),
        make_verification(reward_amount=50.0, reward_currency="USDC"),
    )
    assert result["region"] == REGION_RUSSIA_EXCLUDED
    assert "REGION_RUSSIA_EXCLUDED" in result["exclusion_reasons"]
    assert result["exclusion_tag"] == "[EXCLUDED][REGION]"


def test_non_technical_task_goes_to_human_only():
    result = evaluate(
        make_candidate(
            title="Design a logo for our DAO",
            description=(
                "Create a logo and a poster for our DAO. Reward is 100 USD. "
                "This bounty is open worldwide."
            ),
        ),
        make_verification(reward_amount=100.0, reward_currency="USD"),
    )
    assert result["human_only"] is True
    assert result["human_only_tag"] == "[EXCLUDED][HUMAN_ONLY]"
    assert result["agent_compatible"] is False
    assert result["exclusion_reasons"] == []


def test_aggregator_post_is_excluded():
    result = evaluate(
        make_candidate(
            title="Bounty Alert: 11 new opportunities found",
            description="Automatically collected list of bounties. Reward $25 USDC worldwide.",
        ),
        make_verification(
            reward_amount=25.0, reward_currency="USDC", aggregator_markers=["bounty alert"]
        ),
    )
    assert "AGGREGATOR_POST_NOT_A_TASK" in result["exclusion_reasons"]
    assert result["exclusion_tag"] == "[EXCLUDED][AGGREGATOR]"


def test_archived_repository_is_excluded():
    result = evaluate(
        make_candidate(
            description=make_candidate()["description"] + " This bounty is open worldwide."
        ),
        make_verification(
            reward_amount=50.0, reward_currency="USDC", repo_meta={"archived": True}
        ),
    )
    assert "REPOSITORY_ARCHIVED" in result["exclusion_reasons"]


def test_agent_access_human_only_from_source_is_respected():
    result = evaluate(
        make_candidate(
            agent_access="HUMAN_ONLY",
            description=make_candidate()["description"] + " Open worldwide.",
        ),
        make_verification(reward_amount=50.0, reward_currency="USDC"),
    )
    assert result["human_only"] is True


def test_short_text_does_not_claim_financial_safety():
    """Короткий текст (только заголовок) — риск UNKNOWN, задача не recommended."""
    result = evaluate(
        make_candidate(description="", region_status_override=REGION_GLOBAL),
        make_verification(reward_amount=30.0, reward_currency="USDC"),
    )
    assert result["financial_risk"] == "UNKNOWN"
    assert "FINANCIAL_RISK_UNKNOWN_MANUAL_CHECK" in result["manual_check_reasons"]
    assert result["agent_compatible"] is False


def test_analyze_region_variants():
    assert analyze_region("This bounty is open worldwide.")["region"] == REGION_GLOBAL
    assert analyze_region("Only available to residents of Canada.")["region"] == REGION_RESTRICTED
    assert analyze_region("Not available in Russia.")["region"] == REGION_RUSSIA_EXCLUDED
    assert analyze_region("Fix the CSV export.")["region"] == REGION_UNKNOWN
    assert analyze_region("")["region"] == REGION_UNKNOWN