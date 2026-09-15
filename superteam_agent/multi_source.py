"""Multi-source поиск оплачиваемых задач: оркестратор и отчёт.

Пайплайн:

1. каждый источник-адаптер (``superteam``, ``github``, ``bountybureau``, ``opire``,
   ``warpspeed``, ``openbounty``) обнаруживает кандидатов и проверяет КАЖДУЮ задачу
   по первоисточнику;
2. результаты объединяются (дедупликация по каноническому ключу URL: одна и та же
   задача из GitHub/BountyBureau/Opire становится одной записью);
3. применяется общая политика (финансы, регион, оплата, тип задачи);
4. формируются ``all_verified``, ``top_agent_compatible``, ``top_human_only``,
   ``excluded`` (+ ``needs_manual_check`` и ``secondary_candidates`` для аудита);
5. отчёт сохраняется в ``bounty_results.json`` (секреты вырезаются).

Никакие задачи не выдумываются: если источник недоступен, это фиксируется как
``source_status = ERROR``/``NOT_FOUND`` с причиной.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any, Final, Mapping, Sequence

from dotenv import load_dotenv

from .config import (
    BOUNTY_CLOSED,
    BOUNTY_CLAIMED,
    BOUNTY_NOT_FOUND,
    BOUNTY_PR_LINKED,
    BOUNTY_RATE_LIMITED,
    BOUNTY_UNKNOWN,
    BOUNTY_VERIFIED_OPEN,
    BOUNTY_ASSIGNED,
    DEFAULT_PER_SOURCE_LIMIT,
    ENV_FILE,
    MULTI_SOURCE_RESULTS_FILE,
    SOURCE_STATUS_ERROR,
    SOURCE_STATUS_NOT_FOUND,
)
from .core.models import (
    canonical_key,
    source_priority,
    utc_now_iso,
)
from .core.ranking import sort_candidates
from .httpx_layer import build_client
from .secrets import redact, safe
from .sources import available_sources, resolve_sources, run_all_sources
from .sources.base import SourceResult

#: Насколько «строгим» является статус проверки: чем больше, тем хуже для задачи.
#: При дедупликации выбирается наиболее строгая находка — задача никогда не
#: «улучшается» до открытой за счёт более слабого источника.
VERIFICATION_SEVERITY: Final[dict[str, int]] = {
    BOUNTY_VERIFIED_OPEN: 0,
    BOUNTY_UNKNOWN: 1,
    BOUNTY_RATE_LIMITED: 2,
    BOUNTY_NOT_FOUND: 3,
    BOUNTY_PR_LINKED: 4,
    BOUNTY_ASSIGNED: 5,
    BOUNTY_CLAIMED: 6,
    BOUNTY_CLOSED: 7,
}

#: Заголовки разделов отчёта (в порядке вывода).
SECTION_TOP_AGENT: Final[str] = "=== TOP AGENT-COMPATIBLE (multi-source) ==="
SECTION_TOP_HUMAN: Final[str] = "=== TOP HUMAN-ONLY (multi-source) ==="
SECTION_SECONDARY: Final[str] = "=== SECONDARY CANDIDATES (hard tasks) ==="
SECTION_MANUAL: Final[str] = "=== NEEDS MANUAL CHECK ==="
SECTION_EXCLUDED: Final[str] = "=== EXCLUDED (причины) ==="
SECTION_SOURCES: Final[str] = "=== SOURCES STATUS ==="


def _merge_metadata(target: dict[str, Any], other: Mapping[str, Any]) -> None:
    """Дополнить запись данными другого источника (без перетирания значений)."""
    target["sources"] = list(
        dict.fromkeys([*(target.get("sources") or []), *(other.get("sources") or [])])
    )
    for field_name in ("evidence", "notes"):
        merged = list(
            dict.fromkeys([*(target.get(field_name) or []), *(other.get(field_name) or [])])
        )
        target[field_name] = merged[:25]
    for field_name in ("dashboard_url", "language", "repo"):
        if not target.get(field_name) and other.get(field_name):
            target[field_name] = other[field_name]


def deduplicate(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Объединить одну и ту же задачу из разных источников.

    Ключ — канонический URL (``gh:owner/repo#123`` для GitHub). Основой берётся
    запись с наиболее строгим статусом проверки: если один источник утверждает,
    что задача занята/закрыта, объединённая запись тоже не станет «открытой».
    """
    merged: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = canonical_key(str(entry.get("url") or "")) or (
            f"{entry.get('source')}:{entry.get('source_id')}"
        )
        if not key:
            continue
        item = dict(entry)
        existing = merged.get(key)
        if existing is None:
            merged[key] = item
            continue

        current_severity = VERIFICATION_SEVERITY.get(str(existing.get("verified_status")), 1)
        new_severity = VERIFICATION_SEVERITY.get(str(item.get("verified_status")), 1)
        # Основой остаётся запись с более строгим статусом проверки.
        base, other = (item, existing) if new_severity > current_severity else (existing, item)
        _merge_metadata(base, other)
        # Primary source — самый авторитетный из объединившихся источников.
        priority_candidates = [
            str(base.get("primary_source") or base.get("source") or ""),
            str(other.get("primary_source") or other.get("source") or ""),
        ]
        base["primary_source"] = min(priority_candidates, key=source_priority)
        merged[key] = base
    return list(merged.values())


def classify(entries: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Разложить задачи по спискам отчёта.

    * ``all_verified`` — задачи, открытость которых подтверждена первоисточником;
    * ``top_agent_compatible`` — прошли все жёсткие фильтры и посильны агенту;
    * ``top_human_only`` — открытые и оплачиваемые, но не для агентского исполнения;
    * ``needs_manual_check`` — неизвестен финансовый риск/регион/стек;
    * ``secondary_candidates`` — сложные (HARD), но потенциально стоящие задачи;
    * ``excluded`` — всё, что не прошло фильтры (с причиной).
    """
    buckets: dict[str, list[dict[str, Any]]] = {
        "all_verified": [],
        "top_agent_compatible": [],
        "top_human_only": [],
        "needs_manual_check": [],
        "secondary_candidates": [],
        "excluded": [],
    }
    for entry in entries:
        item = dict(entry)
        if not item.get("verified_at"):
            item["verified_at"] = utc_now_iso()
        verified_open = str(item.get("verified_status") or "") == BOUNTY_VERIFIED_OPEN
        if verified_open:
            buckets["all_verified"].append(item)
        if item.get("exclusion_reasons"):
            buckets["excluded"].append(item)
            continue
        if not verified_open:
            continue
        if item.get("human_only"):
            buckets["top_human_only"].append(item)
            continue
        if item.get("manual_check_reasons"):
            buckets["needs_manual_check"].append(item)
            continue
        if item.get("agent_compatible") and item.get("secondary"):
            buckets["secondary_candidates"].append(item)
            continue
        if item.get("agent_compatible"):
            buckets["top_agent_compatible"].append(item)
    for name, items in list(buckets.items()):
        buckets[name] = [dict(sort_item) for sort_item in sort_candidates(items)]
    return buckets


def _report_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Проекция записи для JSON-отчёта (полный контракт + ключевая диагностика)."""
    description = str(entry.get("description") or "")
    return {
        "source": entry.get("source"),
        "primary_source": entry.get("primary_source"),
        "sources": list(entry.get("sources") or []),
        "title": entry.get("title"),
        "url": entry.get("url"),
        "dashboard_url": entry.get("dashboard_url"),
        "status": entry.get("status"),
        "bounty_status": entry.get("bounty_status"),
        "reward_amount": entry.get("reward_amount"),
        "reward_currency": entry.get("reward_currency"),
        "payment_method": entry.get("payment_method"),
        "payment_type": entry.get("payment_type"),
        "financial_risk": entry.get("financial_risk"),
        "region": entry.get("region"),
        "difficulty": entry.get("difficulty"),
        "estimated_time": entry.get("estimated_time"),
        "tech_stack": list(entry.get("tech_stack") or []),
        "tech_priority": entry.get("tech_priority"),
        "beginner_friendly": entry.get("beginner_friendly"),
        "agent_compatible": entry.get("agent_compatible"),
        "exclusion_reason": entry.get("exclusion_reason"),
        "exclusion_reasons": list(entry.get("exclusion_reasons") or []),
        "exclusion_tag": entry.get("exclusion_tag"),
        "manual_check_reasons": list(entry.get("manual_check_reasons") or []),
        "verified_status": entry.get("verified_status"),
        "verified_at": entry.get("verified_at"),
        "rank_score": entry.get("rank_score"),
        "ranking_factors": list(entry.get("ranking_factors") or []),
        "repo": entry.get("repo"),
        "language": entry.get("language"),
        "labels": list(entry.get("labels") or []),
        "assignee": entry.get("assignee"),
        "deadline": entry.get("deadline"),
        "freshness": entry.get("freshness"),
        "evidence": list(entry.get("evidence") or [])[:12],
        "notes": list(entry.get("notes") or [])[:12],
        "financial_risk_reasons": list(entry.get("financial_risk_reasons") or [])[:6],
        "region_reasons": list(entry.get("region_reasons") or [])[:4],
        "description": description[:1200],
    }


def _compact_excluded(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Компактная форма исключённой задачи (обязательные поля из задания)."""
    return {
        "title": entry.get("title"),
        "url": entry.get("url"),
        "source": entry.get("source"),
        "sources": list(entry.get("sources") or []),
        "exclusion_reason": entry.get("exclusion_reason"),
        "exclusion_reasons": list(entry.get("exclusion_reasons") or []),
        "financial_risk": entry.get("financial_risk"),
        "region": entry.get("region"),
        "verified_status": entry.get("verified_status"),
        "verified_at": entry.get("verified_at"),
        "bounty_status": entry.get("bounty_status"),
        "reward_amount": entry.get("reward_amount"),
        "reward_currency": entry.get("reward_currency"),
    }


def build_report(
    source_results: Sequence[SourceResult], buckets: Mapping[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """Собрать итоговый JSON-отчёт по всем источникам."""
    return {
        "generated_at": utc_now_iso(),
        "sources": {result.name: result.to_dict() for result in source_results},
        "counts": {
            "all_verified": len(buckets.get("all_verified") or []),
            "top_agent_compatible": len(buckets.get("top_agent_compatible") or []),
            "top_human_only": len(buckets.get("top_human_only") or []),
            "secondary_candidates": len(buckets.get("secondary_candidates") or []),
            "needs_manual_check": len(buckets.get("needs_manual_check") or []),
            "excluded": len(buckets.get("excluded") or []),
        },
        "all_verified": [_report_entry(item) for item in buckets.get("all_verified") or []],
        "top_agent_compatible": [
            _report_entry(item) for item in buckets.get("top_agent_compatible") or []
        ],
        "top_human_only": [_report_entry(item) for item in buckets.get("top_human_only") or []],
        "secondary_candidates": [
            _report_entry(item) for item in buckets.get("secondary_candidates") or []
        ],
        "needs_manual_check": [
            _report_entry(item) for item in buckets.get("needs_manual_check") or []
        ],
        "excluded": [_compact_excluded(item) for item in buckets.get("excluded") or []],
    }


def save_multi_source_report(report: Mapping[str, Any]) -> Any:
    """Сохранить отчёт в ``bounty_results.json`` (секреты вырезаются)."""
    text = redact(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    MULTI_SOURCE_RESULTS_FILE.write_text(text + "\n", encoding="utf-8")
    return MULTI_SOURCE_RESULTS_FILE


def print_sources_status(results: Sequence[SourceResult]) -> None:
    """[DISCOVERED]/[VERIFYING] и статусы источников."""
    print(SECTION_SOURCES)
    print()
    for result in results:
        print(
            f"[DISCOVERED] {result.name}: найдено {result.discovered}, "
            f"подтверждено открытыми {result.verified_open}"
        )
        print(
            f"[VERIFYING]  {result.name}: проверено по первоисточнику {len(result.items)} "
            f"записей (source_status={result.source_status})"
        )
        if result.reason:
            print(f"             причина: {result.reason}")
        for error in result.errors[:3]:
            print(f"             error: {safe(error)[:160]}")
    print()


def log_tag(entry: Mapping[str, Any]) -> str:
    """Тег записи для лога: [RECOMMENDED] / [VERIFIED OPEN] / [EXCLUDED][…]."""
    if entry.get("exclusion_tag"):
        return str(entry["exclusion_tag"])
    if entry.get("human_only_tag"):
        return str(entry["human_only_tag"])
    if str(entry.get("verified_status") or "") == BOUNTY_VERIFIED_OPEN:
        return "[VERIFIED OPEN]"
    return "[EXCLUDED][UNVERIFIED]"


def print_entry_log(entries: Sequence[Mapping[str, Any]], recommended: set[str]) -> None:
    """Построчный лог по задачам с требованиями-тегами."""
    for entry in entries:
        tag = "[RECOMMENDED]" if str(entry.get("url")) in recommended else log_tag(entry)
        reason = str(entry.get("exclusion_reason") or "")
        reason_part = f" — {reason}" if reason and tag.startswith("[EXCLUDED]") else ""
        print(f"{tag} {safe(entry.get('url'))}{reason_part}")
        if entry.get("manual_check_reasons"):
            print(f"    manual: {', '.join(str(item) for item in entry['manual_check_reasons'])}")
    print()


def print_shortlist(title: str, entries: Sequence[Mapping[str, Any]], limit: int = 5) -> None:
    """Напечатать короткий список задач (агентские / human-only / manual)."""
    print(title)
    print()
    print(min(limit, len(entries)))
    print()
    if not entries:
        print("(нет подходящих задач)")
        print()
        return
    for position, entry in enumerate(entries[:limit], start=1):
        print(f"[{position}] {safe(entry.get('title'))}")
        print(f"    Source: {entry.get('source')} | primary: {entry.get('primary_source')}")
        print(f"    URL: {safe(entry.get('url'))}")
        print(
            f"    Reward: {entry.get('reward_amount')} {entry.get('reward_currency') or 'UNKNOWN'}"
            f" ({entry.get('payment_type')}) | payment: {safe(entry.get('payment_method'))}"
        )
        print(
            f"    Status: {entry.get('status')}/{entry.get('bounty_status')} | verified:"
            f" {entry.get('verified_status')} at {entry.get('verified_at')}"
        )
        print(
            f"    Financial risk: {entry.get('financial_risk')} | Region: {entry.get('region')}"
            f" | Difficulty: {entry.get('difficulty')} | Time: {entry.get('estimated_time')}"
        )
        print(
            f"    Tech: {', '.join(str(item) for item in entry.get('tech_stack') or []) or 'UNKNOWN'}"
            f" | beginner-friendly: {'yes' if entry.get('beginner_friendly') else 'no'}"
        )
        print(f"    Rank: {entry.get('rank_score')}")
        for factor in list(entry.get("ranking_factors") or [])[:4]:
            print(f"        - {safe(factor)}")
        if entry.get("exclusion_reasons"):
            print(f"    Exclusion: {', '.join(str(item) for item in entry['exclusion_reasons'])}")
        if entry.get("manual_check_reasons"):
            print(f"    Manual check: {', '.join(str(item) for item in entry['manual_check_reasons'])}")
        print()


def print_exclusion_summary(buckets: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    """Сводка причин исключения (сколько задач по каждой причине)."""
    counts: dict[str, int] = {}
    for entry in buckets.get("excluded") or []:
        for reason in entry.get("exclusion_reasons") or ["UNKNOWN"]:
            counts[str(reason)] = counts.get(str(reason), 0) + 1
    print(SECTION_EXCLUDED)
    print()
    if not counts:
        print("(исключённых задач нет)")
        print()
        return
    for reason, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])):
        print(f"    {reason}: {count}")
    print()


async def run_multi_source_search(args: argparse.Namespace) -> int:
    """Выполнить multi-source поиск оплачиваемых задач.

    :param args: аргументы CLI (``--sources``, ``--per-source-limit``).
    :returns: код выхода (``0`` — успех, ``1`` — ошибка конфигурации).
    """
    load_dotenv(ENV_FILE)
    per_source_limit = int(getattr(args, "per_source_limit", 0) or DEFAULT_PER_SOURCE_LIMIT)
    try:
        selected = resolve_sources(getattr(args, "sources", None))
    except ValueError as error:
        print(f"Ошибка выбора источников: {error}")
        return 1

    print("=== MULTI-SOURCE BOUNTY SEARCH ===")
    print()
    print(f"Источники ({len(selected)}): {', '.join(selected)}")
    print(f"Доступные источники: {', '.join(available_sources())}")
    print(f"Лимит записей на источник: {per_source_limit}")
    print()

    async with build_client() as client:
        results = await run_all_sources(
            client, sources=selected, per_source_limit=per_source_limit
        )

    print_sources_status(results)

    gathered = [entry for result in results for entry in result.items]
    unique = deduplicate(gathered)
    buckets = classify(unique)
    print(f"Собрано записей: {len(gathered)}, уникальных задач после дедупликации: {len(unique)}")
    print()

    recommended_urls = {str(item.get("url")) for item in buckets["top_agent_compatible"]}
    print_entry_log(unique, recommended_urls)

    print_shortlist(SECTION_TOP_AGENT, buckets["top_agent_compatible"], limit=10)
    print_shortlist(SECTION_TOP_HUMAN, buckets["top_human_only"], limit=10)
    print_shortlist(SECTION_SECONDARY, buckets["secondary_candidates"], limit=5)
    print_shortlist(SECTION_MANUAL, buckets["needs_manual_check"], limit=5)
    print_exclusion_summary(buckets)

    report = build_report(results, buckets)
    path = save_multi_source_report(report)
    print(f"counts: {report['counts']}")
    print(f"Отчёт: {path}")
    print()

    failed = [
        result
        for result in results
        if result.source_status in (SOURCE_STATUS_ERROR, SOURCE_STATUS_NOT_FOUND)
    ]
    if failed:
        print("Источники, которые не удалось использовать:")
        for result in failed:
            print(f"    {result.name}: {result.source_status} — {result.reason}")
        print()
    return 0