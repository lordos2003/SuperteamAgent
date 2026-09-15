"""Тесты двухэтапного пайплайна: discovery → card verification (п.17 задания).

Реальные запросы не выполняются: карточка отдаётся через ``httpx.MockTransport``,
API/website-данные подставляются вручную. Проверяются девять обязательных
сценариев: expired/closed/winners/human-only/unknown и приоритет карточки.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from superteam_agent.card import verify_listing_card
from superteam_agent.config import (
    UNKNOWN,
    VERIFIED_CLOSED,
    VERIFIED_EXPIRED,
    VERIFIED_HUMAN_ONLY,
    VERIFIED_OPEN,
    VERIFIED_WINNER_ANNOUNCED,
)
from superteam_agent.runner import build_final_entry, is_verified_open_listing

FUTURE = "2030-01-01T00:00:00.000Z"
PAST = "2020-01-01T00:00:00.000Z"
BENIGN_DESCRIPTION = (
    "Build a small Python utility that exports the report data to CSV and add a regression test "
    "for the new column order. The task is fully local and uses only open-source libraries."
)


def card_html(listing: dict[str, Any] | None, extra_body: str = "") -> str:
    """HTML карточки с ``__NEXT_DATA__`` (как отдаёт сам сайт)."""
    payload = {"props": {"pageProps": {"listing": listing}}}
    return (
        "<html><head><title>fixture</title></head><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        f"{extra_body}</body></html>"
    )


def card_listing(**overrides: Any) -> dict[str, Any]:
    """Объект listing внутри карточки (то, что «видит» verification)."""
    listing = {
        "slug": "slug-1",
        "title": "Fix the CSV export bug",
        "status": "open",
        "deadline": FUTURE,
        "rewardAmount": 500,
        "token": "USDC",
        "agentAccess": "AGENT_ALLOWED",
        "isWinnersAnnounced": False,
        "description": BENIGN_DESCRIPTION,
        "type": "bounty",
    }
    listing.update(overrides)
    return listing


def verify(status: int, body: str, slug: str = "slug-1") -> dict[str, Any]:
    """Прогнать card verification на фикстуре."""

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(status, text=body)

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await verify_listing_card(client, slug)

    return asyncio.run(run())


def merged_item(**overrides: Any) -> dict[str, Any]:
    """Объединённая запись API+website (discovery-данные, НЕ доказательство)."""
    item = {
        "slug": "slug-1",
        "title": "Fix the CSV export bug",
        "type": "bounty",
        "reward": "500 USDC",
        "reward_amount": 500,
        "token": "USDC",
        "status": "OPEN",
        "deadline": PAST,  # API/website могут отдавать устаревший deadline
        "agent_access": "AGENT_ALLOWED",
        "region": "Global",
        "winners_flagged": False,
        "winners_announced_at": "",
        "source": "website",
        "source_url": "https://superteam.fun/api/listings/?status=open",
        "source_api": False,
        "source_website": True,
        "sources": ["website"],
        "api_status": "OPEN",
        "api_deadline": PAST,
        "api_reward": "500 USDC",
        "api_agent_access": "AGENT_ALLOWED",
        "website_status": "OPEN",
        "website_deadline": PAST,
        "website_reward": "500 USDC",
    }
    item.update(overrides)
    return item


def final_entry(card: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Собрать финальную запись: discovery-данные + результат проверки карточки."""
    return build_final_entry(merged_item(**overrides), card)


def clear_region_env(monkeypatch) -> None:
    """Убрать пользовательский регион, чтобы eligibility зависела только от карточки."""
    monkeypatch.delenv("SUPERTEAM_USER_REGION", raising=False)
    monkeypatch.delenv("SUPERTEAM_USER_COUNTRY", raising=False)


def test_1_api_open_with_old_deadline_card_expired(monkeypatch):
    """TEST 1: API=OPEN (старый deadline), карточка подтверждает EXPIRED."""
    clear_region_env(monkeypatch)
    card = verify(200, card_html(card_listing(deadline=PAST)))
    entry = final_entry(card)

    assert card["verification_status"] == VERIFIED_EXPIRED
    assert card["deadline_passed"] is True
    assert entry["verification_status"] == VERIFIED_EXPIRED
    assert entry["final_decision"] == "EXCLUDE"
    assert entry["priority"] == "EXCLUDED"
    # расхождение API/website/verified сохраняется для аудита
    assert entry["api_status"] == "OPEN"
    assert entry["website_status"] == "OPEN"
    assert is_verified_open_listing(entry) is False


def test_2_api_open_card_open_future_deadline(monkeypatch):
    """TEST 2: API=OPEN, карточка=OPEN, deadline в будущем → VERIFIED_OPEN."""
    clear_region_env(monkeypatch)
    card = verify(200, card_html(card_listing()))
    entry = final_entry(card)

    assert card["verification_status"] == VERIFIED_OPEN
    assert card["deadline_confirmed"] is True
    assert entry["final_decision"] == "CANDIDATE"
    assert entry["verified_deadline"] == "2030-01-01 00:00 UTC"
    assert entry["verification_url"].endswith("/earn/listing/slug-1")


def test_3_card_human_only(monkeypatch):
    """TEST 3: карточка говорит HUMAN_ONLY → VERIFIED_HUMAN_ONLY (не для агента)."""
    clear_region_env(monkeypatch)
    card = verify(200, card_html(card_listing(agentAccess="HUMAN_ONLY")))
    entry = final_entry(card)

    assert card["verification_status"] == VERIFIED_HUMAN_ONLY
    assert entry["agent_access"] == "HUMAN_ONLY"
    assert entry["human_only"] is True
    assert entry["verification_status"] != VERIFIED_OPEN
    assert is_verified_open_listing(entry) is False


def test_4_card_unavailable_is_unknown(monkeypatch):
    """TEST 4: карточка недоступна (403) → UNKNOWN, не CLOSED и не OPEN."""
    clear_region_env(monkeypatch)
    card = verify(403, "<html>forbidden</html>")
    entry = final_entry(card)

    assert card["verification_status"] == UNKNOWN
    assert card["reachable"] is False
    assert entry["final_decision"] == "EXCLUDE"
    assert is_verified_open_listing(entry) is False


def test_5_deadline_missing_on_card_is_unknown(monkeypatch):
    """TEST 5: на карточке нет deadline → UNKNOWN (deadline не подтверждён)."""
    clear_region_env(monkeypatch)
    listing = card_listing()
    listing.pop("deadline")
    card = verify(200, card_html(listing))
    entry = final_entry(card)

    assert card["verification_status"] == UNKNOWN
    assert card["deadline_confirmed"] is False
    assert entry["final_decision"] == "EXCLUDE"
    assert "deadline not confirmed on card" in (entry["exclusion_reasons"] or [])


def test_6_winners_announced(monkeypatch):
    """TEST 6: объявлены победители → VERIFIED_WINNER_ANNOUNCED."""
    clear_region_env(monkeypatch)
    card = verify(200, card_html(card_listing(isWinnersAnnounced=True)))
    entry = final_entry(card)

    assert card["verification_status"] == VERIFIED_WINNER_ANNOUNCED
    assert entry["has_winners"] is True
    assert entry["final_decision"] == "EXCLUDE"
    assert "WINNER" in (entry["exclusion_reason"] or "").upper()


def test_7_card_deadline_wins_over_api_deadline(monkeypatch):
    """TEST 7: deadline карточки приоритетнее API/website deadline."""
    clear_region_env(monkeypatch)
    card = verify(200, card_html(card_listing(deadline="2031-05-05T12:00:00.000Z")))
    entry = final_entry(card)

    assert entry["api_deadline"] == PAST
    assert entry["website_deadline"] == PAST
    assert entry["deadline_utc"] == "2031-05-05 12:00 UTC"
    assert entry["verified_deadline"] == "2031-05-05 12:00 UTC"
    assert entry["verification_status"] == VERIFIED_OPEN


def test_8_api_says_open_card_is_closed(monkeypatch):
    """TEST 8: API=OPEN, но карточка закрыта → VERIFIED_CLOSED."""
    clear_region_env(monkeypatch)
    card = verify(200, card_html(card_listing(status="closed")))
    entry = final_entry(card)

    assert card["verification_status"] == VERIFIED_CLOSED
    assert entry["final_decision"] == "EXCLUDE"
    assert entry["verification_status"] == VERIFIED_CLOSED
    assert is_verified_open_listing(entry) is False


def test_9_agent_allowed_future_deadline_low_risk_is_eligible(monkeypatch):
    """TEST 9: AGENT_ALLOWED + будущий deadline + низкий риск → подходящий кандидат."""
    clear_region_env(monkeypatch)
    card = verify(200, card_html(card_listing()))
    entry = final_entry(card)

    assert entry["verification_status"] == VERIFIED_OPEN
    assert entry["agent_access"] == "AGENT_ALLOWED"
    assert entry["agent_access_unknown"] is False
    assert entry["eligibility_status"] == "ELIGIBLE"
    assert entry["financial_risk"] == "LOW"
    assert entry["financial_risk_state"] == "confirmed_safe"
    assert entry["final_decision"] == "CANDIDATE"
    assert is_verified_open_listing(entry) is True


def test_agent_access_missing_is_marked_unknown(monkeypatch):
    """Информации об agent access нет → UNKNOWN + agent_access_unknown = true."""
    clear_region_env(monkeypatch)
    listing = card_listing()
    listing.pop("agentAccess")
    card = verify(200, card_html(listing))
    entry = final_entry(card, agent_access="")

    assert card["agent_access"] == "UNKNOWN"
    assert card["agent_access_unknown"] is True
    assert entry["agent_access_unknown"] is True
    # UNKNOWN не считается подходящим для агента
    assert is_verified_open_listing(entry) is False


def test_cache_reuses_fresh_card_and_expires(monkeypatch):
    """TTL-кэш: свежая запись переиспользуется, просроченная — нет."""
    from superteam_agent import cache as cache_module

    clear_region_env(monkeypatch)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        calls["count"] += 1
        return httpx.Response(200, text=card_html(card_listing()))

    async def run() -> tuple[dict[str, Any], dict[str, Any]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await verify_listing_card(client, "slug-1")
            second = await verify_listing_card(client, "slug-1")
            return first, second

    monkeypatch.setenv("SUPERTEAM_VERIFICATION_CACHE_TTL", "600")
    first, second = asyncio.run(run())
    assert calls["count"] == 1
    assert second["from_cache"] is True
    assert second["verification_status"] == first["verification_status"]

    # TTL = 0 (кэш выключен) → карточка скачивается снова
    monkeypatch.setenv("SUPERTEAM_VERIFICATION_CACHE_TTL", "0")
    cache_module.clear_cache()
    calls["count"] = 0
    asyncio.run(run())
    assert calls["count"] == 2