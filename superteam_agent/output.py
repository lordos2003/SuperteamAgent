"""Вывод результатов и сохранение отчётов (без секретов).

Все строки прогоняются через :func:`safe`/:func:`redact`, поэтому API key,
claimCode и заголовок Authorization в консоль и файлы не попадают.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .card import result_label, short_date
from .config import (
    ALL_VERIFICATION_STATUSES,
    PLACEHOLDER,
    RESULTS_FILE,
    UNKNOWN,
    VERIFIED_LISTINGS_FILE,
    VERIFIED_OPEN,
)
from .parse import (
    DEADLINE_KEYS,
    SKILL_KEYS,
    SLUG_KEYS,
    STATUS_KEYS,
    TITLE_KEYS,
    TYPE_KEYS,
    extract_agent_eligibility,
    extract_reward,
    format_deadline,
    format_skills,
    format_status,
    lookup,
)
from .risk import REAL_ACTIVITY_EXCLUSION
from .secrets import redact, safe


def print_excluded_section(entries: Sequence[Mapping[str, Any]]) -> None:
    """Секция ``=== EXCLUDED ===``: Title / Status / Reason (см. п.20 задания)."""
    print("=== EXCLUDED ===")
    print()
    print(len(entries))
    print()
    for position, entry in enumerate(entries, start=1):
        print(f"[{position}] {safe(entry.get('title') or '(no title)')}")
        print(f"    Status: {entry.get('verification_status')}")
        print(f"    Reason: {safe(entry.get('exclusion_reason') or '-')}")
        print(f"    URL:    {safe(entry.get('card_url') or '')}")
        print()


def print_unknown_section(entries: Sequence[Mapping[str, Any]]) -> None:
    """Секция ``=== UNKNOWN / VERIFICATION FAILED ===`` с причиной и evidence."""
    print("=== UNKNOWN / VERIFICATION FAILED ===")
    print()
    print(len(entries))
    print()
    for position, entry in enumerate(entries, start=1):
        print(f"[{position}] {safe(entry.get('title') or '(no title)')}")
        print(f"    Reason: {safe(entry.get('error') or entry.get('exclusion_reason') or 'status cannot be determined')}")
        print(f"    URL:    {safe(entry.get('card_url') or '')}")
        for line in list(entry.get("evidence") or [])[:2]:
            print(f"    evidence: {safe(line)}")
        print()


#: Подписи для секции статистики (порядок как в задании).
STATISTICS_LABELS: tuple[tuple[str, str], ...] = (
    ("discovered", "Discovered"),
    ("unique", "Unique"),
    ("pre_filtered", "Pre-filtered"),
    ("verified", "Verified"),
    ("verified_open", "Verified Open"),
    ("expired", "Expired"),
    ("closed", "Closed"),
    ("human_only", "Human Only"),
    ("winner_announced", "Winner Announced"),
    ("unknown", "Unknown"),
    ("risk_excluded", "Risk Excluded"),
)


def print_statistics(statistics: Mapping[str, Any]) -> None:
    """Секция ``=== STATISTICS ===`` из counters прогона."""
    print("=== STATISTICS ===")
    print()
    for key, label in STATISTICS_LABELS:
        print(f"    {label}: {statistics.get(key, 0)}")
    print()


def source_label(entry: Mapping[str, Any]) -> str:
    """Человеко-читаемая метка источников: agent_api, website или оба."""
    api = bool(entry.get("source_api"))
    website = bool(entry.get("source_website"))
    if api and website:
        return "agent_api+website"
    if api:
        return "agent_api"
    if website:
        return "website"
    return "unknown"


def print_listing_summary(listing: Mapping[str, Any], index: int | None = None) -> None:
    """Напечатать безопасную сводку по одному заданию.

    Выводятся только: title, slug, type, status, reward, deadline, skills и
    agent eligibility. API key, claimCode и заголовок Authorization не
    печатаются никогда.

    :param listing: объект задания из ответа API.
    :param index: необязательный номер задания для строки-заголовка.
    """
    if not isinstance(listing, Mapping):
        print("    (listing has unexpected format, skipped)")
        return

    title = lookup(listing, TITLE_KEYS) or "(no title in API response)"
    slug = lookup(listing, SLUG_KEYS) or PLACEHOLDER
    listing_type = lookup(listing, TYPE_KEYS) or PLACEHOLDER
    status = format_status(lookup(listing, STATUS_KEYS))
    reward = extract_reward(listing)
    deadline = format_deadline(lookup(listing, DEADLINE_KEYS))
    skills = format_skills(lookup(listing, SKILL_KEYS))
    agent_info = extract_agent_eligibility(listing)

    prefix = f"[{index}] " if index is not None else ""
    print(f"{prefix}{safe(title)}")
    print(f"    Slug:     {safe(slug)}")
    print(f"    Type:     {safe(listing_type)}")
    print(f"    Status:   {status}")
    print(f"    Reward:   {reward}")
    print(f"    Deadline: {deadline}")
    print(f"    Skills:   {skills}")
    print(f"    Agent:    {agent_info}")


def print_website_diagnostics(source: Mapping[str, Any]) -> None:
    """Напечатать фактическую диагностику публичного источника (без секретов)."""
    print("=== WEBSITE SOURCE DIAGNOSTICS ===")
    print()
    for entry in source.get("diagnostics", []):
        print(f"{entry['url']}")
        print(
            f"    HTTP: {entry['http_status']} | content-type: {entry['content_type']} "
            f"| bytes: {entry['bytes']} | reachable: {entry['reachable']}"
        )
        print(
            f"    __NEXT_DATA__: {'yes' if entry['next_data_found'] else 'no'}"
            f" | embedded listing objects: {entry['embedded_listings_found']}"
            f" | /earn/listing/ links: {entry['listing_links_found']}"
        )
        if entry.get("error"):
            print(f"    error: {entry['error']}")
    feed = source.get("feed", {})
    if feed:
        print(f"{feed.get('url')} (public feed used by the site frontend)")
        print(
            f"    HTTP: {feed.get('http_status')} | reachable: {feed.get('reachable')} "
            f"| listings from feed: {feed.get('items')}"
        )
        if feed.get("error"):
            print(f"    error: {feed['error']}")
    print(
        f"    итого: HTML/embedded JSON дал {source.get('html_listings_found', 0)} заданий, "
        f"ссылок /earn/listing/ в HTML: {len(source.get('html_links') or [])}"
    )
    print()


def print_hybrid_verification(index: int, entry: Mapping[str, Any], card: Mapping[str, Any]) -> None:
    """Напечатать компактный результат проверки одной карточки.

    Показываются данные обоих источников и вердикт карточки (главный источник
    истины). Секреты не печатаются.
    """
    title = entry.get("title") or card.get("title") or "(no title)"
    card_status = str(card.get("verification_status") or UNKNOWN)
    api_part = (
        f"API: {entry.get('api_status') or PLACEHOLDER} / {short_date(entry.get('api_deadline'))}"
        if entry.get("source_api")
        else "API: -"
    )
    website_part = (
        f"WEBSITE: {entry.get('website_status') or PLACEHOLDER} / "
        f"{short_date(entry.get('website_deadline'))}"
        if entry.get("source_website")
        else "WEBSITE: -"
    )

    print(f"[{index}] {safe(title)}")
    print(f"    Sources: {source_label(entry)}")
    print(f"    {api_part} | {website_part}")
    print(f"    CARD: {card_status}")

    extra_parts: list[str] = []
    if card.get("deadline_utc"):
        extra_parts.append(
            f"card deadline: {card['deadline_utc']} "
            f"(passed: {'yes' if card.get('deadline_passed') else 'no'})"
        )
    if card.get("has_winners"):
        extra_parts.append(f"winners: {safe(str(card.get('winner_info'))[:80])}")
    if extra_parts:
        print(f"    Card info: {' | '.join(extra_parts)}")
    print(f"    Result: {result_label(card_status)}")
    if card.get("error"):
        print(f"    Card error: {card['error']}")


def print_verified_open(entries: Sequence[Mapping[str, Any]]) -> None:
    """Напечатать финальный список подтверждённых открытых заданий."""
    print("=== VERIFIED OPEN ===")
    print()
    print(len(entries))
    print()
    for position, entry in enumerate(entries, start=1):
        print(f"[{position}] {safe(entry.get('title') or '(no title)')}")
        print(f"    Slug: {safe(entry.get('slug'))}")
        print(f"    Reward: {entry.get('reward') or PLACEHOLDER}")
        print(f"    Deadline: {entry.get('deadline_utc') or PLACEHOLDER}")
        print(f"    Type: {entry.get('type') or PLACEHOLDER}")
        print(f"    Agent access: {entry.get('agent_access') or 'UNKNOWN'}")
        print(f"    Region: {entry.get('region') or 'UNKNOWN'} ({entry.get('eligibility_status')})")
        print(f"    Source: {source_label(entry)}")
        print(f"    Financial risk: {entry.get('financial_risk') or PLACEHOLDER}")
        print(f"    Own money required: {'yes' if entry.get('requires_own_money') else 'no'}")
        print(f"    Difficulty: {entry.get('difficulty') or 'UNKNOWN'}")
        print(
            f"    Priority: {entry.get('priority') or PLACEHOLDER} "
            f"(score {entry.get('score')}, fit {entry.get('estimated_fit')})"
        )
        print(f"    Reason: {safe(entry.get('reason') or '')}")
        print(f"    Card: {safe(entry.get('card_url'))}")
        print()


def print_top_opportunities(entries: Sequence[Mapping[str, Any]], limit: int = 3) -> None:
    """Напечатать раздел ``=== TOP OPPORTUNITIES ===``.

    Показываются до ``limit`` заданий с положительным ``score`` (задания с
    отрицательным score остаются в списке ``=== VERIFIED OPEN ===`` и в
    разделах AGENT-COMPATIBLE / HUMAN-ONLY).
    """
    positive = [entry for entry in entries if int(entry.get("score") or 0) > 0]
    shown = positive[:limit]

    print("=== TOP OPPORTUNITIES ===")
    print()
    print(len(shown))
    if len(positive) > len(shown):
        print(f"(shown {len(shown)} of {len(positive)} tasks with positive score)")
    if not shown:
        print("(нет заданий с положительным score — смотрите разделы ниже)")
    print()
    for position, entry in enumerate(shown, start=1):
        print(f"[{position}] {safe(entry.get('title') or '(no title)')}")
        print()
        print(f"Reward: {entry.get('reward') or 'UNKNOWN'}")
        print(f"Deadline: {entry.get('deadline_utc') or 'UNKNOWN'}")
        print(f"Agent access: {entry.get('agent_access') or 'UNKNOWN'}")
        print(f"Region: {entry.get('region') or 'UNKNOWN'}")
        print(f"Difficulty: {entry.get('difficulty') or 'UNKNOWN'}")
        print(f"Financial risk: {entry.get('financial_risk') or 'UNKNOWN'}")
        print(f"Own money: {'yes' if entry.get('requires_own_money') else 'no'}")
        print(f"Estimated fit: {entry.get('estimated_fit') or 'UNKNOWN'}")
        print(f"Score: {entry.get('score')}")
        print("Why:")
        for reason in list(entry.get("why") or [])[:3]:
            print(f"- {safe(reason)}")
        print(f"Card: {safe(entry.get('card_url') or '')}")
        print()


def print_ranked_list(title: str, entries: Sequence[Mapping[str, Any]], limit: int = 5) -> None:
    """Напечатать компактный рейтинг (для агентских и human-only задач)."""
    print(title)
    print()
    print(min(limit, len(entries)))
    print()
    if not entries:
        print("(нет подходящих заданий)")
        print()
        return
    for position, entry in enumerate(entries[:limit], start=1):
        print(f"[{position}] {safe(entry.get('title') or '(no title)')}")
        print(f"    Slug: {safe(entry.get('slug'))}")
        print(
            f"    Score: {entry.get('score')} | Fit: {entry.get('estimated_fit')} "
            f"| Priority: {entry.get('priority')}"
        )
        print(
            f"    Reward: {entry.get('reward') or 'UNKNOWN'} | Deadline: "
            f"{entry.get('deadline_utc') or 'UNKNOWN'} ({entry.get('hours_until_deadline')}h)"
        )
        print(
            f"    Agent access: {entry.get('agent_access') or 'UNKNOWN'} | Region: "
            f"{entry.get('region') or 'UNKNOWN'} ({entry.get('eligibility_status')})"
        )
        print(
            f"    Difficulty: {entry.get('difficulty') or 'UNKNOWN'} | Financial risk: "
            f"{entry.get('financial_risk') or 'UNKNOWN'} | Own money: "
            f"{'yes' if entry.get('requires_own_money') else 'no'}"
        )
        print(f"    Decision: {entry.get('decision') or entry.get('final_decision') or 'UNKNOWN'}")
        print(f"    Exclusion reason: {entry.get('exclusion_reason') or '-'}")
        print(f"    Card: {safe(entry.get('card_url') or '')}")
        print()


def print_excluded_for_financial_risk(entries: Sequence[Mapping[str, Any]]) -> None:
    """Напечатать задания, жёстко исключённые по финансовому риску.

    Показываются все записи с ``exclusion_reason == REAL_FINANCIAL_ACTIVITY_REQUIRED``,
    включая те, где ``requires_own_money = false`` (например sponsored free lane).
    """
    print("=== EXCLUDED: FINANCIAL RISK ===")
    print()
    print(len(entries))
    print()
    if not entries:
        print("(нет заданий, исключённых по финансовому риску)")
        print()
        return
    for position, entry in enumerate(entries, start=1):
        print(f"[{position}] {safe(entry.get('title') or '(no title)')}")
        print(f"    Slug: {safe(entry.get('slug'))}")
        print(f"    Reward: {entry.get('reward') or 'UNKNOWN'} | Agent access: {entry.get('agent_access')}")
        print(f"    Debug risk flags:")
        print(
            f"        requires_real_mainnet_activity={entry.get('requires_real_mainnet_activity')}"
            f" | requires_real_trade={entry.get('requires_real_trade')}"
        )
        print(
            f"        requires_deposit={entry.get('requires_deposit')}"
            f" | requires_token_purchase={entry.get('requires_token_purchase')}"
            f" | requires_user_gas={entry.get('requires_user_gas')}"
            f" | requires_own_money={entry.get('requires_own_money')}"
        )
        print(f"        financial_risk={entry.get('financial_risk')}")
        print(f"    Decision: {entry.get('decision') or entry.get('final_decision')}")
        print(f"    Exclusion reason: {entry.get('exclusion_reason')}")
        for reason in list(entry.get("risk_reasons") or [])[:3]:
            print(f"        - {safe(reason)}")
        for note in list(entry.get("risk_non_overriding_notes") or [])[:1]:
            print(f"    Note (does NOT override exclusion): {safe(note)}")
        print(f"    Card: {safe(entry.get('card_url') or '')}")
        print()


def save_verification_report(cards: Sequence[Mapping[str, Any]], api_count: int) -> Path:
    """Сохранить подробный отчёт проверки в ``verified_listings.json``.

    Файл не содержит секретов: перед записью весь JSON прогоняется через
    :func:`redact`.

    :param cards: результаты :func:`verify_listing_card`.
    :param api_count: сколько заданий вернул Agent API.
    :returns: путь к записанному файлу.
    """
    verified_count = sum(1 for card in cards if card.get("verification_status") == VERIFIED_OPEN)
    summary = {
        status: sum(1 for card in cards if card.get("verification_status") == status)
        for status in ALL_VERIFICATION_STATUSES
    }
    report = {
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "api_count": api_count,
        "verified_count": verified_count,
        "verification_summary": summary,
        "listings": list(cards),
    }
    text = redact(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    VERIFIED_LISTINGS_FILE.write_text(text + "\n", encoding="utf-8")
    return VERIFIED_LISTINGS_FILE


def save_hybrid_results(
    entries: Sequence[Mapping[str, Any]],
    agent_api_count: int,
    website_count: int,
    unique_count: int,
    website_source: Mapping[str, Any],
    top_agent_compatible: Sequence[Mapping[str, Any]] | None = None,
    top_human_only: Sequence[Mapping[str, Any]] | None = None,
    verified_open_listings: Sequence[Mapping[str, Any]] | None = None,
    statistics: Mapping[str, Any] | None = None,
) -> Path:
    """Сохранить результаты гибридного поиска в ``superteam_results.json``.

    API key в файл не попадает: JSON прогоняется через :func:`redact`.

    :param entries: финальные записи (проверенные карточки + скоринг).
    :param agent_api_count: сколько заданий вернул Agent API.
    :param website_count: сколько заданий найдено на публичном сайте.
    :param unique_count: сколько уникальных slug после объединения.
    :param website_source: результат :func:`collect_website_source` (диагностика).
    :param top_agent_compatible: топ агентских заданий (AGENT_ONLY / AGENT_ALLOWED).
    :param top_human_only: топ human-only заданий.
    :returns: путь к записанному файлу.
    """

    def compact(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "slug": item.get("slug"),
                "title": item.get("title"),
                "score": item.get("score"),
                "estimated_fit": item.get("estimated_fit"),
                "agent_access": item.get("agent_access"),
                "reward": item.get("reward"),
                "deadline_utc": item.get("deadline_utc"),
                "difficulty": item.get("difficulty"),
                "financial_risk": item.get("financial_risk"),
                "eligibility_status": item.get("eligibility_status"),
                "card_url": item.get("card_url"),
            }
            for item in items
        ]

    report = {
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agent_api_count": agent_api_count,
        "website_count": website_count,
        "unique_count": unique_count,
        "discovered_count": agent_api_count + website_count,
        "pre_filtered_count": len(entries),
        # Только реально подтверждённые карточкой открытые и подходящие листинги.
        "verified_open_count": len(verified_open_listings or []),
        "statistics": dict(statistics or {}),
        "website_diagnostics": website_source.get("diagnostics", []),
        "website_feed": website_source.get("feed", {}),
        "top_agent_compatible": compact(top_agent_compatible or []),
        "top_human_only": compact(top_human_only or []),
        "verified_open_listings": compact(verified_open_listings or []),
        "listings": list(entries),
    }
    text = redact(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    RESULTS_FILE.write_text(text + "\n", encoding="utf-8")
    return RESULTS_FILE
