"""Тесты вспомогательных функций парсинга и карточки."""
from __future__ import annotations

from superteam_agent.card import (
    card_submission_count,
    html_to_text,
    parse_meta_tags,
    parse_next_data,
    parse_utc,
)
from superteam_agent.parse import (
    DEADLINE_KEYS,
    SLUG_KEYS,
    STATUS_KEYS,
    TITLE_KEYS,
    extract_listings,
    format_deadline,
    format_number,
    format_reward,
    format_status,
    lookup,
    unwrap_listing,
)


def test_format_number():
    assert format_number(1234567) == "1 234 567"
    assert format_number(1.5) == "1.5"
    assert format_number("abc") == "abc"


def test_format_deadline():
    assert format_deadline("2030-01-02T03:04:05Z") == "2030-01-02 03:04 UTC"
    assert format_deadline(1577934245000) == "2020-01-02 03:04 UTC"
    assert format_deadline("") == "-"
    assert format_deadline(None) == "-"
    assert format_deadline(True) == "True"


def test_format_status():
    assert format_status(True) == "OPEN"
    assert format_status(False) == "NOT OPEN"
    assert format_status("open") == "OPEN"
    assert format_status(None) == "-"


def test_lookup_case_insensitive_and_skips_empty():
    mapping = {"TITLE": "x", "Slug": "s-1", "status": "open"}
    assert lookup(mapping, TITLE_KEYS) == "x"
    assert lookup(mapping, SLUG_KEYS) == "s-1"
    assert lookup(mapping, STATUS_KEYS) == "open"
    assert lookup(mapping, ("missing",)) is None
    assert lookup({"name": ""}, TITLE_KEYS) is None


def test_format_reward():
    assert format_reward(100) == "100"
    assert format_reward({"amount": 50, "token": "USDC"}) == "50 USDC"
    assert format_reward([1, 2]) == "1 / 2"
    assert format_reward("1000") == "1000"


def test_extract_listings_various_wrappers():
    listing = {"slug": "s1", "title": "t"}
    assert extract_listings([listing]) == [listing]
    assert extract_listings({"data": [listing]}) == [listing]
    assert extract_listings({"nested": {"listings": [listing]}}) == [listing]
    assert extract_listings({}) == []
    assert extract_listings(None) == []


def test_unwrap_listing():
    assert unwrap_listing({"data": {"slug": "s1"}}) == {"slug": "s1"}
    assert unwrap_listing({"slug": "s1"}) == {"slug": "s1"}
    assert unwrap_listing([{"slug": "s1"}]) == {"slug": "s1"}
    assert unwrap_listing(None) == {}


def test_parse_utc():
    moment = parse_utc("2030-01-01T00:00:00Z")
    assert moment is not None and moment.year == 2030 and moment.tzinfo is not None
    assert parse_utc(1577934245).year == 2020
    assert parse_utc("garbage") is None
    assert parse_utc("") is None
    assert parse_utc(None) is None
    assert parse_utc(True) is None


def test_html_to_text_strips_scripts_and_decodes_entities():
    html = '<script>var x = 1;</script><p>Hello &amp; world</p>'
    assert html_to_text(html) == "Hello & world"


def test_parse_meta_tags_both_attribute_orders():
    html = (
        '<meta property="og:title" content="First">'
        '<meta content="Second" name="og:description">'
    )
    metas = parse_meta_tags(html)
    assert metas["og:title"] == "First"
    assert metas["og:description"] == "Second"


def test_parse_next_data_missing_returns_none():
    assert parse_next_data("<html><body>no next data</body></html>") is None


def test_card_submission_count_from_text():
    assert card_submission_count(None, "30 SUBMISSIONS") == 30
    assert card_submission_count(None, "no count here") is None
