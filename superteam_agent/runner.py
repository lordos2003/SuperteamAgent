"""Гибридный поиск: Agent API + публичный сайт + проверка карточек.

Шаги:
  1. Agent API (``/api/agents/listings/live``) — обнаружение заданий,
     в первую очередь скрытых ``AGENT_ONLY`` / ``AGENT_ALLOWED``;
  2. публичный сайт — актуальная лента (страницы + публичный фид);
  3. объединение по slug с флагами ``source_api`` / ``source_website``;
  4. проверка КАЖДОЙ уникальной карточки через :func:`verify_listing_card`
     (карточка — главный источник истины);
  5. фильтр актуальности (только ``VERIFIED_OPEN`` и deadline в будущем);
  6. анализ финансового риска и приоритетов;
  7. сохранение ``superteam_results.json``.

Agent API отдаёт устаревшие данные (status=OPEN у завершённых заданий),
поэтому он используется только как источник ОБНАРУЖЕНИЯ заданий, а источник
истины — карточка.
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Any, Mapping

import httpx
from dotenv import load_dotenv

from .api import (
    card_url,
    get_base_url,
    get_listing_details,
    get_live_listings,
)
from .card import build_unverified_card, verify_listing_card
from .config import (
    API_KEY_ENV,
    CARD_CONCURRENCY,
    ENV_FILE,
    LIVE_LISTINGS_PATH,
    ALL_VERIFICATION_STATUSES,
    REQUEST_MIN_INTERVAL_SECONDS,
    VERIFIED_OPEN,
)
from .errors import SuperteamApiError
from .httpx_layer import RateLimiter, build_client
from .output import (
    print_excluded_for_financial_risk,
    print_hybrid_verification,
    print_listing_summary,
    print_ranked_list,
    print_top_opportunities,
    print_verified_open,
    print_website_diagnostics,
    save_hybrid_results,
    save_verification_report,
)
from .parse import extract_listings, normalize_listing, unwrap_listing
from .risk import REAL_ACTIVITY_EXCLUSION
from .scoring import score_listing
from .secrets import get_api_key, safe, to_safe_json
from .website import collect_website_source, merge_sources


def build_final_entry(merged: Mapping[str, Any], card: Mapping[str, Any]) -> dict[str, Any]:
    """Собрать финальную запись: карточка (истина) + источники + скоринг.

    Карточка — главный источник истины: статус, deadline, reward, region и
    agent access берутся из неё. Значения Agent API и публичного сайта
    сохраняются отдельно (``api_*`` / ``website_*``), чтобы было видно
    расхождение. Скоринг выполняет :func:`score_listing`.

    :param merged: объединённая запись из обоих источников.
    :param card: результат :func:`verify_listing_card`.
    :returns: словарь финальной записи (включая поля скоринга и решение).
    """
    slug = str(merged.get("slug") or "")
    entry: dict[str, Any] = {
        "slug": slug,
        "title": card.get("title") or merged.get("title") or "",
        "card_url": card.get("card_url") or card_url(slug),
        # --- источники ---
        "source_api": bool(merged.get("source_api")),
        "source_website": bool(merged.get("source_website")),
        "sources": list(merged.get("sources") or []),
        "api_status": merged.get("api_status", ""),
        "api_deadline": merged.get("api_deadline", ""),
        "api_reward": merged.get("api_reward", ""),
        "api_agent_access": merged.get("api_agent_access", ""),
        "website_status": merged.get("website_status", ""),
        "website_deadline": merged.get("website_deadline", ""),
        "website_reward": merged.get("website_reward", ""),
        # --- карточка (источник истины) ---
        "status": card.get("status", ""),
        "deadline": card.get("deadline", ""),
        "deadline_utc": card.get("deadline_utc", ""),
        "deadline_confirmed": bool(card.get("deadline_confirmed")),
        "deadline_passed": bool(card.get("deadline_passed")),
        "reward": card.get("reward") or merged.get("reward", ""),
        "rewards": card.get("rewards", ""),
        "token": card.get("token") or merged.get("token") or _token_from_reward(card.get("reward", "")),
        "type": card.get("type") or merged.get("type", ""),
        "agent_access": card.get("agent_access") or merged.get("agent_access", ""),
        "region": card.get("region") or merged.get("region", ""),
        "region_text": card.get("region_text", ""),
        "has_winners": bool(card.get("has_winners")),
        "winner_info": card.get("winner_info", ""),
        "verification_status": str(card.get("verification_status") or "UNKNOWN"),
        "reachable": card.get("reachable"),
        "http_status": card.get("http_status"),
        "description": card.get("description", ""),
        "description_full": card.get("description_full") or card.get("description", ""),
        "requirements_text": card.get("requirements_text", ""),
        "eligibility_text": card.get("eligibility_text", ""),
        "submissions": card.get("submissions"),
        "reward_amount": card.get("reward_amount"),
        "evidence": card.get("evidence", []),
        "error": card.get("error", ""),
    }

    scored = score_listing(entry)
    entry.update(scored)

    entry["priority_score"] = scored["score"]
    entry["priority_reasons"] = scored["why"]
    entry["reason"] = "; ".join(scored["why"][:4])
    entry["financial_risk_reasons"] = scored["risk_reasons"]
    entry["financial_risk_mitigations"] = scored["risk_mitigations"]
    entry["financial_risk_context_notes"] = scored["risk_context_notes"]
    return entry


def _token_from_reward(text: str) -> str:
    from .scoring import token_from_reward

    return token_from_reward(str(text or ""))


async def _verify_cards(
    client: httpx.AsyncClient,
    merged: list[dict[str, Any]],
    budget: int,
    no_verify: bool,
    verify_limit: int,
) -> list[dict[str, Any]]:
    """Проверить карточки параллельно (Semaphore + RateLimiter).

    :returns: результаты в том же порядке, что и ``merged``.
    """
    semaphore = asyncio.Semaphore(CARD_CONCURRENCY)
    limiter = RateLimiter(REQUEST_MIN_INTERVAL_SECONDS)

    async def verify_one(item: Mapping[str, Any], position: int) -> dict[str, Any]:
        slug = str(item.get("slug") or "")
        if no_verify:
            return build_unverified_card(slug, "verification skipped (--no-verify)")
        if position > budget:
            return build_unverified_card(slug, f"not verified (--verify-limit {verify_limit})")
        async with semaphore:
            await limiter.acquire()
            return await verify_listing_card(client, slug)

    return list(
        await asyncio.gather(
            *(verify_one(item, position) for position, item in enumerate(merged, start=1))
        )
    )


async def run_hybrid_search(args: argparse.Namespace) -> int:
    """Гибридный поиск: Agent API + публичный сайт + проверка карточек.

    :param args: разобранные аргументы командной строки.
    :returns: код выхода (``0`` — успех, ``1`` — ошибка ключа/Agent API).
    """
    print("=== SUPERTEAM HYBRID SEARCH ===")
    print()

    load_dotenv(ENV_FILE)
    if not get_api_key():
        print("Agent API: FAILED")
        print(f"{API_KEY_ENV} is not set. Add your key to {ENV_FILE.name} and retry")
        return 1

    async with build_client() as client:
        # --- 1. Agent API: обнаружение заданий (в т.ч. скрытых AGENT_ONLY) ---
        try:
            api_payload = await get_live_listings(client)
        except SuperteamApiError as error:
            print("Agent API: FAILED")
            print(f"Reason: {error}")
            return 1

        api_items = [
            normalize_listing(item, "agent_api", get_base_url() + LIVE_LISTINGS_PATH)
            for item in extract_listings(api_payload)
        ]
        api_items = [item for item in api_items if item["slug"]]

        if args.raw:
            print("--- Raw Agent API response (secrets removed) ---")
            print(to_safe_json(api_payload, limit=None))
            print()

        # --- 2. Публичный сайт: актуальная лента ---
        website_source = await collect_website_source(client, include_diagnostics=not args.no_diagnostics)
        website_items = [item for item in website_source["listings"] if item["slug"]]

        # --- 3. Объединение по slug ---
        merged = merge_sources(api_items, website_items)
        print(f"Agent API listings: {len(api_items)}")
        print(f"Website listings: {len(website_items)}")
        print(f"Unique listings: {len(merged)}")
        only_api = sum(1 for item in merged if item["source_api"] and not item["source_website"])
        only_website = sum(1 for item in merged if item["source_website"] and not item["source_api"])
        both = sum(1 for item in merged if item["source_api"] and item["source_website"])
        print(f"agent_api only: {only_api} | website only: {only_website} | both: {both}")
        print()
        print_website_diagnostics(website_source)

        if not merged:
            print("Ни один источник не вернул заданий.")
            return 0

        # --- 4-6. Проверка карточек, финансовый риск, приоритеты ---
        print("=== CARD VERIFICATION ===")
        print()

        budget = len(merged) if args.verify_limit <= 0 else min(args.verify_limit, len(merged))
        cards = await _verify_cards(client, merged, budget, args.no_verify, args.verify_limit)

        entries: list[dict[str, Any]] = []
        for position, (item, card) in enumerate(zip(merged, cards), start=1):
            entries.append(build_final_entry(item, card))
            print_hybrid_verification(position, item, card)
            print()

        ranked = sorted(entries, key=lambda entry: int(entry.get("score") or 0), reverse=True)
        candidates = [entry for entry in ranked if entry["final_decision"] == "CANDIDATE"]
        agent_compatible = [
            entry
            for entry in candidates
            if entry.get("agent_access") in {"AGENT_ONLY", "AGENT_ALLOWED"}
        ]
        human_only = [entry for entry in candidates if entry.get("agent_access") == "HUMAN_ONLY"]
        financial_excluded = [
            entry
            for entry in ranked
            if REAL_ACTIVITY_EXCLUSION in (entry.get("exclusion_reasons") or [])
            and entry.get("verification_status") == VERIFIED_OPEN
        ]

        # --- 7. Итоги и файлы ---
        print_verified_open(candidates)
        print_top_opportunities(candidates, limit=3)
        print_ranked_list("=== TOP AGENT-COMPATIBLE ===", agent_compatible, limit=5)
        print_ranked_list("=== TOP HUMAN-ONLY ===", human_only, limit=5)
        print_excluded_for_financial_risk(financial_excluded)

        if args.no_verify:
            shown = len(merged) if args.show <= 0 else min(max(args.show, 0), len(merged))
            print(f"Список источников (карточки не проверялись, показано {shown} из {len(merged)}):")
            print()
            for position, item in enumerate(merged[:shown], start=1):
                print_listing_summary(item, index=position)
                print()

        detail_slugs = [str(entry.get("slug") or "") for entry in candidates][: max(args.details, 0)]
        if args.slug:
            detail_slugs = [args.slug.strip()]
        if detail_slugs:
            print(f"Детали Agent API для подтверждённых заданий ({len(detail_slugs)}):")
            print()
            for position, slug in enumerate(detail_slugs, start=1):
                print(f"[{position}] Details: {safe(slug)}")
                try:
                    details_payload = await get_listing_details(client, slug)
                except SuperteamApiError as error:
                    print(f"    FAILED: {error}")
                    print()
                    continue
                if args.raw:
                    print(to_safe_json(details_payload, limit=None))
                else:
                    print_listing_summary(unwrap_listing(details_payload))
                print()

        results_path = save_hybrid_results(
            entries,
            len(api_items),
            len(website_items),
            len(merged),
            website_source,
            top_agent_compatible=agent_compatible,
            top_human_only=human_only,
        )
        verified_path = save_verification_report(cards, len(api_items))

        status_counts = ", ".join(
            f"{status}={sum(1 for entry in entries if entry.get('verification_status') == status)}"
            for status in ALL_VERIFICATION_STATUSES
        )
        excluded = sum(1 for entry in entries if entry["final_decision"] == "EXCLUDE")
        financial_blocks = sum(1 for entry in entries if entry.get("requires_own_money"))
        agent_ready = sum(
            1
            for entry in candidates
            if str(entry.get("agent_access") or "").upper() in {"AGENT_ONLY", "AGENT_ALLOWED"}
        )
        print(f"Статусы карточек: {status_counts}")
        print(
            f"Итого: уникальных {len(merged)}, подтверждено открытых {len(candidates)} "
            f"(agent-compatible: {agent_ready}), исключено {excluded} "
            f"(из них по деньгам исполнителя: {financial_blocks})"
        )
        print(f"Результаты: {results_path}")
        print(f"Отчёт проверки карточек: {verified_path}")
        return 0
