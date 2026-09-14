"""Тесты анализа финансового риска."""
from __future__ import annotations

from superteam_agent.risk import (
    FINANCIAL_RISK_HIGH,
    FINANCIAL_RISK_LOW,
    REAL_ACTIVITY_EXCLUSION,
    analyze_financial_risk,
)


def test_real_mainnet_trades_hard_excluded():
    risk = analyze_financial_risk(
        "You must complete 50 qualifying trades on mainnet to earn the reward."
    )
    assert risk["hard_exclusion"] is True
    assert risk["financial_risk"] == FINANCIAL_RISK_HIGH
    assert risk["exclusion_reason"] == REAL_ACTIVITY_EXCLUSION
    assert risk["requires_real_mainnet_activity"] is True
    assert risk["requires_real_trade"] is True
    assert risk["risk_reasons"]


def test_sponsored_free_lane_does_not_override_trade_exclusion():
    risk = analyze_financial_risk(
        "Complete 100 qualifying trades on mainnet. "
        "Sponsored Free Lane is available for all participants."
    )
    assert risk["hard_exclusion"] is True
    assert risk["financial_risk"] == FINANCIAL_RISK_HIGH
    assert risk["non_overriding_notes"]


def test_testnet_allowed_mode_is_low_risk():
    risk = analyze_financial_risk("Perform 50 simulated trades on testnet.")
    assert risk["hard_exclusion"] is False
    assert risk["financial_risk"] == FINANCIAL_RISK_LOW
    assert risk["requires_real_trade"] is False
    assert risk["requires_own_money"] is False
    assert risk["mitigations"]


def test_gas_covered_by_sponsor_in_same_sentence():
    risk = analyze_financial_risk(
        "Participants need to pay gas (gas fees are covered by the sponsor)."
    )
    assert risk["requires_user_gas"] is False
    assert risk["hard_exclusion"] is False
    assert risk["financial_risk"] == FINANCIAL_RISK_LOW


def test_product_capability_is_not_mandatory():
    """Требование к продукту («app allows users to buy tokens») — не к исполнителю."""
    risk = analyze_financial_risk("The app allows users to buy tokens with their own funds.")
    assert risk["hard_exclusion"] is False
    assert risk["requires_own_money"] is False
    assert risk["requires_token_purchase"] is False
    assert risk["context_notes"]


def test_deposit_in_eligibility_is_excluded():
    risk = analyze_financial_risk(
        description="",
        eligibility="Minimum deposit of 10 USDC is required to participate.",
    )
    assert risk["hard_exclusion"] is True
    assert risk["requires_deposit"] is True
    assert risk["requires_own_money"] is True
    assert risk["financial_risk"] == FINANCIAL_RISK_HIGH


def test_benign_description_is_low_risk():
    risk = analyze_financial_risk(
        "Build a Python web scraper that collects public data into a CSV file."
    )
    assert risk["hard_exclusion"] is False
    assert risk["financial_risk"] == FINANCIAL_RISK_LOW
    assert "no real-money" in risk["risk_reasons"][0]


def test_own_funds_phrase_is_excluded():
    risk = analyze_financial_risk(
        description="Submit your results.",
        requirements="You need to use your own funds for the task.",
    )
    assert risk["requires_own_money"] is True
    assert risk["hard_exclusion"] is True
    assert risk["exclusion_reason"] == REAL_ACTIVITY_EXCLUSION
