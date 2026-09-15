"""Тесты единой модели задачи: разбор награды, валюты и ключей дедупликации."""
from __future__ import annotations

import pytest

from superteam_agent.config import PAYMENT_TYPE_CRYPTO, PAYMENT_TYPE_FIAT, PAYMENT_TYPE_UNKNOWN
from superteam_agent.core.models import (
    canonical_key,
    new_candidate,
    normalize_currency,
    parse_estimated_time,
    parse_money,
    payment_type_for,
)


def test_parse_money_common_forms():
    assert parse_money("Bug bounty $25 for a quick fix") == (25.0, "USD")
    assert parse_money("Reward: 500 USD for the fix") == (500.0, "USD")
    assert parse_money("We pay 250 USDC") == (250.0, "USDC")
    assert parse_money("Bounty: $10,000") == (10000.0, "USD")
    assert parse_money("Amount 1 200 USDT") == (1200.0, "USDT")


def test_parse_money_ignores_non_currency_numbers():
    """«11 support»/«8 hours» — это не награда."""
    assert parse_money("Add support for Windows 11 support") == (None, "")
    assert parse_money("Estimated 8 hours of work") == (None, "")
    assert parse_money("") == (None, "")


def test_parse_money_currency_case_rule():
    """Известные коды валют распознаются в любом регистре, случайные слова — нет."""
    assert parse_money("pay 300 EUR") == (300.0, "EUR")
    assert parse_money("pay 300 eur") == (300.0, "EUR")
    assert parse_money("pay 300 bananas") == (None, "")


def test_parse_money_ignores_time_and_unit_words():
    """«5 MINUTES»/«10 ISSUES» — это не награда (защита от ложных срабатываний)."""
    assert parse_money("This should take 5 MINUTES to fix") == (None, "")
    assert parse_money("We have 10 ISSUES in the backlog") == (None, "")
    assert parse_money("[Bounty][$0][Lessons] intake #1618") == (None, "")


def test_payment_type_for():
    assert payment_type_for("USDC") == PAYMENT_TYPE_CRYPTO
    assert payment_type_for("SOL") == PAYMENT_TYPE_CRYPTO
    assert payment_type_for("USD") == PAYMENT_TYPE_FIAT
    assert payment_type_for("") == PAYMENT_TYPE_UNKNOWN


def test_normalize_currency():
    assert normalize_currency("$") == "USD"
    assert normalize_currency("usdc") == "USDC"
    assert normalize_currency("") == ""


def test_parse_estimated_time():
    assert parse_estimated_time("This is a 1-3 hours task") == "1-3 hours"
    assert parse_estimated_time("takes 4 hours") == "4 hours"
    assert parse_estimated_time("2-3 days of work") == "2-3 days"
    assert parse_estimated_time("no estimate") == "UNKNOWN"


def test_canonical_key_deduplicates_issue_and_pr():
    assert canonical_key("https://github.com/Owner/Repo/issues/12") == "gh:owner/repo#12"
    assert canonical_key("https://github.com/Owner/Repo/pull/12") == "gh:owner/repo#12"
    assert canonical_key("https://EXAMPLE.com/path/?x=1") == "https://example.com/path"


def test_new_candidate_defaults_and_unknown_field():
    candidate = new_candidate(source="github", url="https://github.com/a/b/issues/1")
    assert candidate["status"] == "UNKNOWN"
    assert candidate["financial_risk"] == "UNKNOWN"
    assert candidate["region"] == "UNKNOWN"
    assert candidate["agent_compatible"] is False
    assert candidate["reward_amount"] is None
    assert candidate["primary_source"] == "github"
    assert candidate["sources"] == ["github"]

    with pytest.raises(KeyError):
        new_candidate(source="github", totally_unknown_field=1)
