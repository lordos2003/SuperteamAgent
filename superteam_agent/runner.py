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
import json
from collections.abc import Sequence
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
    PRE_FILTER_MAX_CANDIDATES,
    REQUEST_MIN_INTERVAL_SECONDS,
    RESULTS_FILE,
    UNKNOWN,
    VERIFIED_CLOSED,
    VERIFIED_EXPIRED,
    VERIFIED_HUMAN_ONLY,
    VERIFIED_OPEN,
    VERIFIED_WINNER_ANNOUNCED,
)
from .cache import cache_stats
from .errors import SuperteamApiError
from .excel_report import write_excel_report
from .httpx_layer import RateLimiter, build_client
from .report import (
    build_sections,
    print_report,
    print_report_details,
    render_markdown,
    save_markdown_report,
    summary_counts,
)
from .output import (
    print_excluded_for_financial_risk,
    print_excluded_section,
    print_hybrid_verification,
    print_listing_summary,
    print_ranked_list,
    print_statistics,
    print_top_opportunities,
    print_unknown_section,
    print_verified_open,
    print_website_diagnostics,
    save_hybrid_results,
    save_verification_report,
)
from .parse import extract_listings, normalize_listing, unwrap_listing
from .risk import FINANCIAL_RISK_LOW, REAL_ACTIVITY_EXCLUSION
from .scoring import score_listing
from .secrets import get_api_key, redact, safe, to_safe_json
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
        # --- что именно подтвердила карточка (verified_*) + диагностика ---
        "verification_url": card.get("verification_url", ""),
        "verification_timestamp": card.get("verification_timestamp", ""),
        "verified_deadline": card.get("verified_deadline", ""),
        "verified_reward": card.get("verified_reward", ""),
        "verified_currency": card.get("verified_currency", ""),
        "verified_agent_access": card.get("verified_agent_access", "UNKNOWN"),
        "verified_region": card.get("verified_region", ""),
        "verified_winners": card.get("verified_winners"),
        "verified_submissions": card.get("verified_submissions"),
        "agent_access_unknown": bool(card.get("agent_access_unknown", True)),
        "verification_skipped": bool(card.get("verification_skipped")),
        "from_cache": bool(card.get("from_cache")),
        "cache_age_seconds": card.get("cache_age_seconds"),
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


def is_agent_compatible(entry: Mapping[str, Any]) -> bool:
    """Проверить, проходит ли запись финальную eligibility-фильтрацию TOP.

    Для попадания в ``top_agent_compatible`` одновременно обязательны:

    * ``verification_status == VERIFIED_OPEN``;
    * ``final_decision == CANDIDATE``;
    * ``agent_access`` в ``{AGENT_ONLY, AGENT_ALLOWED}``;
    * ``eligibility_status == ELIGIBLE``;
    * все флаги ``requires_*`` равны ``false``;
    * ``financial_risk != HIGH``.
    """
    if str(entry.get("verification_status") or "") != VERIFIED_OPEN:
        return False
    if entry.get("final_decision") != "CANDIDATE":
        return False
    if entry.get("agent_access") not in {"AGENT_ONLY", "AGENT_ALLOWED"}:
        return False
    if entry.get("eligibility_status") != "ELIGIBLE":
        return False
    financial_flags = (
        "requires_own_money",
        "requires_real_mainnet_activity",
        "requires_real_trade",
        "requires_deposit",
        "requires_token_purchase",
        "requires_user_gas",
    )
    if any(entry.get(flag) for flag in financial_flags):
        return False
    if entry.get("financial_risk") == "HIGH":
        return False
    return True


def is_verified_open_listing(entry: Mapping[str, Any]) -> bool:
    """Строгий пропуск в ``verified_open_listings`` (см. п.9 задания).

    Требуется ОДНОВРЕМЕННО:

    * ``verification_status == VERIFIED_OPEN`` (карточка подтвердила открытость);
    * deadline подтверждён карточкой и ещё не прошёл;
    * победители не объявлены;
    * agent access определён явно и это не ``HUMAN_ONLY``;
    * финансовый риск допустим (``LOW`` и без флагов ``requires_*``);
    * задача проходит существующую финальную фильтрацию (:func:`is_agent_compatible`).

    Любой ``UNKNOWN`` здесь невозможен: без данных проверки задача не попадает.
    """
    if str(entry.get("verification_status") or "") != VERIFIED_OPEN:
        return False
    if not entry.get("deadline_confirmed") or entry.get("deadline_passed"):
        return False
    if entry.get("has_winners"):
        return False
    if entry.get("agent_access_unknown"):
        return False
    if str(entry.get("agent_access") or "") not in {"AGENT_ONLY", "AGENT_ALLOWED"}:
        return False
    if str(entry.get("financial_risk") or "") != FINANCIAL_RISK_LOW:
        return False
    return is_agent_compatible(entry)


def build_statistics(
    entries: Sequence[Mapping[str, Any]],
    *,
    discovered: int,
    unique: int,
    pre_filtered: int,
) -> dict[str, int]:
    """Итоговая статистика прогона (см. п.20 задания)."""
    def count_status(status: str) -> int:
        return sum(1 for entry in entries if entry.get("verification_status") == status)

    verified = sum(
        1
        for entry in entries
        if entry.get("verification_status") != UNKNOWN and not entry.get("verification_skipped")
    )
    human_only = sum(
        1
        for entry in entries
        if entry.get("verification_status") == VERIFIED_HUMAN_ONLY
        or str(entry.get("agent_access") or "") == "HUMAN_ONLY"
    )
    risk_excluded = sum(
        1
        for entry in entries
        if REAL_ACTIVITY_EXCLUSION in (entry.get("exclusion_reasons") or [])
    )
    return {
        "discovered": discovered,
        "unique": unique,
        "pre_filtered": pre_filtered,
        "verified": verified,
        "verified_open": sum(
            1 for entry in entries if is_verified_open_listing(entry)
        ),
        "expired": count_status(VERIFIED_EXPIRED),
        "closed": count_status(VERIFIED_CLOSED),
        "human_only": human_only,
        "winner_announced": count_status(VERIFIED_WINNER_ANNOUNCED),
        "unknown": count_status(UNKNOWN),
        "risk_excluded": risk_excluded,
    }


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
        only_api = sum(1 for item in merged if item["source_api"] and not item["source_website"])
        only_website = sum(1 for item in merged if item["source_website"] and not item["source_api"])
        both = sum(1 for item in merged if item["source_api"] and item["source_website"])
        print(
            f"Discovery: Agent API {len(api_items)} + website {len(website_items)} "
            f"→ {len(merged)} уникальных заданий"
            f" (agent_api only: {only_api}, website only: {only_website}, both: {both})"
        )
        print()
        if args.debug:
            print(f"Agent API listings: {len(api_items)}")
            print(f"Website listings: {len(website_items)}")
            print(f"Unique listings: {len(merged)}")
            print(f"agent_api only: {only_api} | website only: {only_website} | both: {both}")
            print()
            print_website_diagnostics(website_source)

        if not merged:
            print("Ни один источник не вернул заданий.")
            return 0

        # --- 4-6. Проверка карточек, финансовый риск, приоритеты ---
        if args.debug:
            print("=== CARD VERIFICATION ===")
            print()
        if args.no_verify:
            print("! ВНИМАНИЕ: включён --no-verify: карточки НЕ проверяются.")
            print("! Прогон диагностический: verification_status=UNKNOWN, final_decision=EXCLUDE.")
        else:
            print("Проверка карточек включена: card = источник истины (статус, deadline, reward, agent access).")
        print()

        # PRE-FILTER: ограничить объём проверки (0 = без ограничения).
        candidates_to_verify: list[dict[str, Any]] = merged
        if PRE_FILTER_MAX_CANDIDATES > 0 and len(merged) > PRE_FILTER_MAX_CANDIDATES:
            candidates_to_verify = merged[:PRE_FILTER_MAX_CANDIDATES]
            print(
                f"PRE-FILTER: проверяются первые {len(candidates_to_verify)} "
                f"из {len(merged)} кандидатов."
            )
            print()

        budget = (
            len(candidates_to_verify)
            if args.verify_limit <= 0
            else min(args.verify_limit, len(candidates_to_verify))
        )
        cards = await _verify_cards(
            client, candidates_to_verify, budget, args.no_verify, args.verify_limit
        )

        entries: list[dict[str, Any]] = []
        for position, (item, card) in enumerate(zip(candidates_to_verify, cards), start=1):
            entries.append(build_final_entry(item, card))
            if args.debug:
                print_hybrid_verification(position, item, card)
                print()

        ranked = sorted(entries, key=lambda entry: int(entry.get("score") or 0), reverse=True)
        candidates = [entry for entry in ranked if entry["final_decision"] == "CANDIDATE"]

        # --- 4-7. Финальная eligibility-фильтрация для TOP ---
        agent_compatible: list[dict[str, Any]] = []
        human_only: list[dict[str, Any]] = []
        region_excluded: list[dict[str, Any]] = []
        manual_check: list[dict[str, Any]] = []
        for entry in candidates:
            if entry.get("agent_access") == "HUMAN_ONLY":
                human_only.append(entry)
                continue
            if entry.get("eligibility_status") == "REGION_RESTRICTED":
                entry["decision"] = "EXCLUDE"
                entry["final_decision"] = "EXCLUDE"
                entry["exclusion_reason"] = "REGION_INELIGIBLE"
                # исключённая задача не может иметь приоритет выше EXCLUDED
                entry["priority"] = "EXCLUDED"
                entry["effective_priority"] = "EXCLUDED"
                region_excluded.append(entry)
                continue
            if entry.get("eligibility_status") == "UNKNOWN":
                manual_check.append(entry)
                continue
            if is_agent_compatible(entry):
                agent_compatible.append(entry)

        financial_excluded = [
            entry
            for entry in ranked
            if REAL_ACTIVITY_EXCLUSION in (entry.get("exclusion_reasons") or [])
            and entry.get("verification_status") == VERIFIED_OPEN
        ]

        # --- verified_open_listings: только подтверждённые карточкой и подходящие.
        verified_open_listings = [entry for entry in ranked if is_verified_open_listing(entry)]
        excluded_entries = [entry for entry in ranked if entry["final_decision"] == "EXCLUDE"]
        unknown_entries = [entry for entry in ranked if entry.get("verification_status") == UNKNOWN]
        statistics = build_statistics(
            entries,
            discovered=len(api_items) + len(website_items),
            unique=len(merged),
            pre_filtered=len(entries),
        )

        # --- 8. Технические разделы (только с --debug) ---
        if args.debug:
            print_verified_open(verified_open_listings)
            print_top_opportunities(candidates, limit=3)
            print_ranked_list("=== TOP AGENT-COMPATIBLE ===", agent_compatible, limit=5)
            print_ranked_list("=== TOP HUMAN-ONLY ===", human_only, limit=5)
            print_ranked_list("=== EXCLUDED: REGION ===", region_excluded, limit=5)
            print_excluded_for_financial_risk(financial_excluded)
            print_excluded_section(excluded_entries)
            print_unknown_section(unknown_entries)
            print_statistics(statistics)
            if manual_check:
                print_ranked_list("=== MANUAL ELIGIBILITY CHECK ===", manual_check, limit=5)

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
        if detail_slugs and args.debug:
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
            verified_open_listings=verified_open_listings,
            statistics=statistics,
        )
        verified_path = save_verification_report(cards, len(api_items))

        # --- 9. Отчёты: Excel (основной), Markdown, консоль ---
        sections = build_sections(entries, verified_open_listings)
        summary = summary_counts(sections, statistics)
        excel_path = write_excel_report(sections, summary)
        report_path = save_markdown_report(render_markdown(sections, summary))

        if args.json:
            # Технический JSON в stdout (файл уже сохранён отдельно).
            print(results_path.read_text(encoding="utf-8"))
        else:
            print_report(sections, summary, excel_path=str(excel_path))
            if args.debug:
                print_report_details(sections, summary)
                status_counts = ", ".join(
                    f"{status}={sum(1 for entry in entries if entry.get('verification_status') == status)}"
                    for status in ALL_VERIFICATION_STATUSES
                )
                print(f"DEBUG карточки: {status_counts}")
                print(f"DEBUG кэш: {cache_stats()}")

        print(f"Excel-отчёт:              {excel_path}")
        print(f"Markdown summary:         {report_path}")
        print(f"Результаты (JSON):        {results_path}")
        print(f"Отчёт проверки карточек:  {verified_path}")
        return 0


def run_report_from_json(args: argparse.Namespace) -> int:
    """Показать человекочитаемый отчёт по последнему прогону (флаг ``--report``).

    Сеть не опрашивается: берутся результаты уже сохранённого
    ``superteam_results.json`` (discovery + verification + cache). Подходящие для
    агента записи определяются тем же предикатом, что и в обычном прогоне, —
    критерии отбора не дублируются и не ослабляются.

    :returns: код выхода (``0`` — отчёт выведен, ``1`` — нет данных).
    """
    if not RESULTS_FILE.exists():
        print(f"Нет файла {RESULTS_FILE.name}: сначала выполните обычный прогон.")
        return 1
    try:
        document = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"Не удалось прочитать {RESULTS_FILE.name}: {redact(str(error))}")
        return 1

    entries = [entry for entry in document.get("listings") or [] if isinstance(entry, Mapping)]
    if not entries:
        print(f"В {RESULTS_FILE.name} нет проверенных карточек.")
        return 1

    available = [entry for entry in entries if is_verified_open_listing(entry)]
    sections = build_sections(entries, available)
    summary = summary_counts(sections, document.get("statistics") or {})
    excel_path = write_excel_report(sections, summary)
    report_path = save_markdown_report(render_markdown(sections, summary))

    if getattr(args, "json", False):
        print(RESULTS_FILE.read_text(encoding="utf-8"))
    else:
        print_report(sections, summary, excel_path=str(excel_path))
        if getattr(args, "debug", False):
            print_report_details(sections, summary)
    print(f"Источник: {RESULTS_FILE.name} (без повторного запроса к сайту)")
    print(f"Excel-отчёт:              {excel_path}")
    print(f"Markdown summary:         {report_path}")
    return 0
