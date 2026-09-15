"""Адаптер Superteam: существующая гибридная логика в едином формате.

ВАЖНО: логика Superteam НЕ переписывается. Адаптер вызывает уже работающие модули
проекта в том же порядке, что и :func:`superteam_agent.runner.run_hybrid_search`:

1. Agent API (``/api/agents/listings/live``) — обнаружение заданий;
2. публичная лента сайта — актуальные задания;
3. объединение по ``slug`` (:func:`merge_sources`);
4. проверка каждой карточки (:func:`verify_listing_card` — источник истины);
5. приведение результата к единой модели, чтобы Superteam-задачи участвовали в
   общем отчёте, дедупликации и ранжировании multi-source поиска.

Скоринг и фильтры Superteam (``score_listing``) остаются прежними: они дают
``eligibility_status``/``agent_access``, которые адаптер передаёт в общую политику.
"""
from __future__ import annotations

from typing import Any, Final, Mapping

import httpx

from ..api import card_url, get_base_url, get_live_listings
from ..card import verify_listing_card
from ..config import (
    BOUNTY_CLOSED,
    BOUNTY_UNKNOWN,
    BOUNTY_VERIFIED_OPEN,
    CARD_CONCURRENCY,
    LIVE_LISTINGS_PATH,
    REQUEST_MIN_INTERVAL_SECONDS,
    SOURCE_STATUS_EMPTY,
    SOURCE_STATUS_OK,
    SOURCE_STATUS_PARTIAL,
    VERIFIED_CLOSED,
    VERIFIED_EXPIRED,
    VERIFIED_HUMAN_ONLY,
    VERIFIED_OPEN,
    VERIFIED_WINNER_ANNOUNCED,
)
from ..core.models import (
    REGION_GLOBAL,
    REGION_RESTRICTED,
    REGION_UNKNOWN,
    new_candidate,
    utc_now_iso,
)
from ..errors import SuperteamApiError
from ..httpx_layer import RateLimiter
from ..parse import extract_listings, normalize_listing
from ..runner import build_final_entry
from ..website import collect_website_source, merge_sources
from .base import SourceResult, finalize_candidate

#: Имя источника в отчёте.
SOURCE_NAME: Final[str] = "superteam"

#: Соответствие статуса карточки Superteam статусу верификации bounty
#: (multi-source модель): human-only карточка остаётся «открытой», а ограничение
#: для агентов передаётся полем ``agent_access``.
CARD_TO_BOUNTY_STATUS: Final[dict[str, str]] = {
    VERIFIED_OPEN: BOUNTY_VERIFIED_OPEN,
    VERIFIED_HUMAN_ONLY: BOUNTY_VERIFIED_OPEN,
}
#: Статусы карточки, означающие «задание закрыто/недоступно».
CLOSED_CARD_STATUSES: Final[tuple[str, ...]] = (
    VERIFIED_CLOSED,
    VERIFIED_EXPIRED,
    VERIFIED_WINNER_ANNOUNCED,
)


def _bounty_status(card_status: str) -> str:
    """Перевести статус карточки Superteam в статус верификации bounty."""
    if card_status in CARD_TO_BOUNTY_STATUS:
        return CARD_TO_BOUNTY_STATUS[card_status]
    if card_status in CLOSED_CARD_STATUSES:
        return BOUNTY_CLOSED
    return BOUNTY_UNKNOWN


def _region_override(eligibility_status: str) -> str:
    """Регион по существующей логике Superteam (``eligibility_status``)."""
    if eligibility_status == "ELIGIBLE":
        return REGION_GLOBAL
    if eligibility_status == "REGION_RESTRICTED":
        return REGION_RESTRICTED
    return REGION_UNKNOWN


def _verification_from_card(entry: Mapping[str, Any], card: Mapping[str, Any]) -> dict[str, Any]:
    """Результат проверки карточки, приведённый к формату верификации bounty."""
    return {
        "verified_status": _bounty_status(str(card.get("verification_status") or "")),
        "verified_at": str(card.get("checked_at") or "") or utc_now_iso(),
        "url": str(entry.get("card_url") or card.get("card_url") or ""),
        "state": str(entry.get("status") or card.get("status") or ""),
        "title": str(entry.get("title") or card.get("title") or ""),
        "body": str(entry.get("description_full") or ""),
        "assignee": "",
        "assignees": [],
        "labels": [],
        "linked_prs": [],
        "claimed_markers": [],
        "paid_markers": [],
        "aggregator_markers": [],
        "reward_amount": entry.get("reward_amount"),
        "reward_currency": str(entry.get("token") or ""),
        "reward_evidence": [str(item) for item in card.get("evidence") or []][:5],
        "repo_meta": {},
        "error": str(card.get("error") or ""),
        "deadline_utc": str(entry.get("deadline_utc") or ""),
        "deadline_passed": bool(entry.get("deadline_passed")),
    }


async def collect(
    client: httpx.AsyncClient, *, per_source_limit: int = 25, **_: Any
) -> SourceResult:
    """Собрать задания Superteam, не изменяя существующую логику поиска."""
    import asyncio

    diagnostics: dict[str, Any] = {
        "agent_api_path": LIVE_LISTINGS_PATH,
        "api_errors": [],
        "website_feed": {},
        "api_items": 0,
        "website_items": 0,
        "merged": 0,
        "verified_cards": 0,
    }

    api_items: list[dict[str, Any]] = []
    try:
        payload = await get_live_listings(client)
    except SuperteamApiError as error:
        diagnostics["api_errors"].append(str(error))
    else:
        api_items = [
            normalized
            for normalized in (
                normalize_listing(raw, "agent_api", get_base_url() + LIVE_LISTINGS_PATH)
                for raw in extract_listings(payload)
            )
            if normalized["slug"]
        ]

    website_source = await collect_website_source(client, include_diagnostics=False)
    website_items = [item for item in website_source["listings"] if item["slug"]]
    diagnostics["website_feed"] = website_source.get("feed", {})

    merged = merge_sources(api_items, website_items)
    diagnostics["api_items"] = len(api_items)
    diagnostics["website_items"] = len(website_items)
    diagnostics["merged"] = len(merged)

    if not merged:
        return SourceResult(
            name=SOURCE_NAME,
            source_status=SOURCE_STATUS_EMPTY,
            reason="Superteam не вернул заданий (проверьте SUPERTEAM_API_KEY и публичный фид)",
            diagnostics=diagnostics,
            errors=diagnostics["api_errors"][:3],
            checked_at=utc_now_iso(),
        )

    limit = max(per_source_limit, 0) or len(merged)
    subset = merged[:limit]
    semaphore = asyncio.Semaphore(CARD_CONCURRENCY)
    limiter = RateLimiter(REQUEST_MIN_INTERVAL_SECONDS)

    async def verify_one(item: Mapping[str, Any]) -> dict[str, Any]:
        async with semaphore:
            await limiter.acquire()
            return await verify_listing_card(client, str(item.get("slug") or ""))

    cards = list(await asyncio.gather(*(verify_one(item) for item in subset)))

    items: list[dict[str, Any]] = []
    verified_open = 0
    errors: list[str] = []
    for item, card in zip(subset, cards):
        slug = str(item.get("slug") or "")
        entry = build_final_entry(item, card)
        verification = _verification_from_card(entry, card)
        if verification["verified_status"] == BOUNTY_VERIFIED_OPEN:
            verified_open += 1
        if card.get("error"):
            errors.append(f"{slug}: {card['error']}")
        candidate = new_candidate(
            source=SOURCE_NAME,
            primary_source=SOURCE_NAME,
            sources=["superteam"],
            source_id=slug,
            title=str(entry.get("title") or ""),
            url=str(entry.get("card_url") or card_url(slug)),
            dashboard_url=card_url(slug),
            description=str(entry.get("description_full") or entry.get("description") or ""),
            requirements_text=str(entry.get("requirements_text") or ""),
            eligibility_text=str(entry.get("eligibility_text") or ""),
            repo="",
            labels=[
                f"agent_access:{entry.get('agent_access')}",
                f"superteam_sources:{','.join(str(name) for name in entry.get('sources') or [])}",
            ],
            agent_access=str(entry.get("agent_access") or "UNKNOWN"),
            region_status_override=_region_override(str(entry.get("eligibility_status") or "")),
            reward_amount=entry.get("reward_amount"),
            reward_currency=str(entry.get("token") or ""),
            payment_method="Superteam Earn reward (Agent API / public listing)",
            raw_status=str(entry.get("status") or ""),
            deadline=str(entry.get("deadline_utc") or ""),
            freshness=f"card verification: {card.get('verification_status')}",
            evidence=[
                f"sources={entry.get('sources')}",
                f"agent_access={entry.get('agent_access')}",
                f"eligibility={entry.get('eligibility_status')}",
                f"decision={entry.get('decision')} reason={entry.get('exclusion_reason')}",
            ],
            notes=[
                f"superteam score={entry.get('score')} fit={entry.get('estimated_fit')}",
                f"deadline passed={entry.get('deadline_passed')}",
            ],
        )
        items.append(finalize_candidate(candidate, verification))

    diagnostics["verified_cards"] = verified_open
    status = SOURCE_STATUS_OK
    reason = ""
    if diagnostics["api_errors"] and not api_items:
        status = SOURCE_STATUS_PARTIAL
        reason = "Agent API недоступен, использована только публичная лента сайта"
    return SourceResult(
        name=SOURCE_NAME,
        source_status=status,
        reason=reason,
        discovered=len(merged),
        verified_open=verified_open,
        items=items,
        diagnostics=diagnostics,
        errors=errors[:10],
        checked_at=utc_now_iso(),
    )