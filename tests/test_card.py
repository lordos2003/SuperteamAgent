"""Тесты e2e-проверки публичной карточки через httpx.MockTransport.

Запросы к живому API не выполняются: transport возвращает фикстурные HTML.
"""
from __future__ import annotations

import asyncio
import json

import httpx

from superteam_agent.card import (
    build_unverified_card,
    result_label,
    short_date,
    verify_listing_card,
)
from superteam_agent.config import (
    CLOSED,
    EXPIRED,
    NOT_FOUND,
    UNKNOWN,
    VERIFIED_OPEN,
    WINNERS_ANNOUNCED,
)

FUTURE = "2030-01-01T00:00:00Z"
PAST = "2020-01-01T00:00:00Z"


def card_html(listing, *, dehydrated: list[dict] | None = None, extra_body: str = "") -> str:
    """Собрать HTML карточки с __NEXT_DATA__ и (опционально) react-query."""
    page_props: dict = {"listing": listing}
    if dehydrated is not None:
        page_props["dehydratedState"] = {"queries": dehydrated}
    payload = {"props": {"pageProps": page_props}}
    return (
        "<html><head><title>fixture</title></head><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        f"{extra_body}</body></html>"
    )


def client_for(status: int, body: str) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(status, text=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def open_listing(**overrides) -> dict:
    listing = {
        "slug": "slug-1",
        "title": "Scrape public data",
        "status": "open",
        "deadline": FUTURE,
        "rewardAmount": 500,
        "token": "USDC",
        "agentAccess": "AGENT_ONLY",
        "region": "Global",
        "type": "bounty",
        "description": "Build a Python scraper.",
    }
    listing.update(overrides)
    return listing


def test_verify_open_listing():
    async def go() -> dict:
        async with client_for(200, card_html(open_listing())) as client:
            return await verify_listing_card(client, "slug-1")

    result = asyncio.run(go())
    assert result["verification_status"] == VERIFIED_OPEN
    assert result["reachable"] is True
    assert result["http_status"] == 200
    assert result["reward"] == "500 USDC"
    assert result["token"] == "USDC"
    assert result["agent_access"] == "AGENT_ONLY"
    assert result["region"] == "Global"
    assert result["deadline_confirmed"] is True
    assert result["deadline_passed"] is False
    assert result["has_winners"] is False
    assert result["slug"] == "slug-1"
    assert result["card_url"].endswith("/earn/listing/slug-1")


def test_verify_winners_announced():
    async def go() -> dict:
        listing = open_listing(isWinnersAnnounced=True)
        async with client_for(200, card_html(listing)) as client:
            return await verify_listing_card(client, "slug-1")

    result = asyncio.run(go())
    assert result["verification_status"] == WINNERS_ANNOUNCED
    assert result["has_winners"] is True


def test_verify_expired_deadline():
    async def go() -> dict:
        listing = open_listing(deadline=PAST)
        async with client_for(200, card_html(listing)) as client:
            return await verify_listing_card(client, "slug-1")

    result = asyncio.run(go())
    assert result["verification_status"] == EXPIRED
    assert result["deadline_passed"] is True


def test_verify_closed_status():
    async def go() -> dict:
        listing = open_listing(status="closed")
        async with client_for(200, card_html(listing)) as client:
            return await verify_listing_card(client, "slug-1")

    result = asyncio.run(go())
    assert result["verification_status"] == CLOSED


def test_verify_not_found_when_listing_null():
    """Сайт отдаёт HTTP 200 для несуществующего slug, но listing = null."""

    async def go() -> dict:
        async with client_for(200, card_html(None)) as client:
            return await verify_listing_card(client, "missing-slug")

    result = asyncio.run(go())
    assert result["verification_status"] == NOT_FOUND


def test_verify_not_found_on_http_404():
    async def go() -> dict:
        async with client_for(404, "<html>not found</html>") as client:
            return await verify_listing_card(client, "missing-slug")

    result = asyncio.run(go())
    assert result["verification_status"] == NOT_FOUND
    assert result["reachable"] is False


def test_verify_unknown_when_site_unavailable():
    """Недоступная карточка НЕ считается закрытой."""

    async def go() -> dict:
        async with client_for(403, "forbidden") as client:
            return await verify_listing_card(client, "slug-1")

    result = asyncio.run(go())
    assert result["verification_status"] == UNKNOWN
    assert result["reachable"] is False


def test_verify_submission_count_from_query():
    async def go() -> dict:
        dehydrated = [
            {"queryKey": ["submissionCount", "slug-1"], "state": {"data": {"count": 7}}},
        ]
        async with client_for(200, card_html(open_listing(), dehydrated=dehydrated)) as client:
            return await verify_listing_card(client, "slug-1")

    result = asyncio.run(go())
    assert result["submissions"] == 7


def test_build_unverified_card():
    card = build_unverified_card("slug-9", "verification skipped (--no-verify)")
    assert card["verification_status"] == UNKNOWN
    assert card["error"] == "verification skipped (--no-verify)"
    assert card["evidence"] == ["verification skipped (--no-verify)"]
    assert card["slug"] == "slug-9"


def test_result_labels():
    assert result_label(VERIFIED_OPEN) == "CANDIDATE"
    assert "MANUAL_CHECK" in result_label(UNKNOWN)
    assert result_label(EXPIRED) == "EXCLUDE"
    assert result_label(WINNERS_ANNOUNCED) == "EXCLUDE"


def test_short_date():
    assert short_date(FUTURE) == "2030-01-01"
    assert short_date("") == "-"
    assert short_date(None) == "-"
