"""Человекочитаемый отчёт: консольный блок и Markdown-файл.

Слой отчёта ничего не пересчитывает и не «улучшает»: он только представляет
результаты существующего пайплайна (discovery → dedup → pre-filter → card
verification → eligibility → risk → scoring). Источник истины по статусу —
карточка, поэтому:

* в ``AVAILABLE FOR AGENT`` попадают только записи, подтверждённые
  предикатом :func:`superteam_agent.runner.is_verified_open_listing`;
* ``UNKNOWN`` никогда не показывается как доступное;
* причина исключения всегда показывается;
* ``card_url`` берётся из данных проверки и не генерируется заново.

Причины «почему подходит» строятся ТОЛЬКО из фактических полей записи
(verification_status, deadline_confirmed, agent_access, financial_risk,
payment_type, region), без домыслов.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Mapping

from .card import parse_utc
from .config import (
    NO_HYPERLINKS_ENV,
    REPORT_DESCRIPTION_LIMIT,
    REPORT_FILE,
    REPORT_RULE_WIDTH,
    UNKNOWN,
    VERIFIED_CLOSED,
    VERIFIED_EXPIRED,
    VERIFIED_HUMAN_ONLY,
    VERIFIED_OPEN,
    VERIFIED_WINNER_ANNOUNCED,
)
from .risk import FINANCIAL_RISK_HIGH, FINANCIAL_RISK_LOW, REAL_ACTIVITY_EXCLUSION
from .secrets import safe

#: Приоритеты в порядке вывода (сначала самые интересные).
PRIORITY_ORDER: Final[tuple[str, ...]] = ("HIGH", "MEDIUM", "LOW")
#: Человеческие причины исключения по коду из пайплайна.
EXCLUSION_REASONS_HUMAN: Final[dict[str, str]] = {
    REAL_ACTIVITY_EXCLUSION: "Requires own funds / financial risk.",
    "REGION_INELIGIBLE": "Region restriction: you are not eligible for this bounty.",
    "REGION_RUSSIA_EXCLUDED": "Region restriction: Russia is excluded.",
    "REGION_RESTRICTED": "Region restriction: limited to specific countries.",
    "REGION_UNKNOWN": "Region is not stated on the card.",
    "NO_CONFIRMED_REWARD": "No confirmed reward on the card.",
    "AGGREGATOR_POST_NOT_A_TASK": "Aggregator post, not a real task.",
    "AGGREGATOR_STATUS_TAKEN": "Already taken (marked by the aggregator).",
    "AGGREGATOR_TIER_REJECTED": "Rejected by the certification bureau.",
    "SELF_PROMOTION_OR_FOR_HIRE": "Self-promotion / for-hire post, not a bounty.",
    "UNPAID_OR_VOLUNTEER": "Unpaid / volunteer task.",
    "REPOSITORY_ARCHIVED": "Repository is archived.",
    "BOUNTY_CLAIMED": "The bounty has already been claimed.",
    "ASSIGNED": "The task is already assigned.",
    "PR_LINKED": "A pull request already solves it.",
    "NOT_FOUND": "The card was not found.",
    "RATE_LIMITED": "Verification was rate limited.",
    "UNVERIFIED": "The card could not be verified.",
    "CLOSED": "The bounty is closed.",
    "EXPIRED": "Deadline has passed.",
    "deadline not confirmed on card": "Deadline is not confirmed on the card.",
    "card deadline already passed": "Deadline has passed.",
    "winners already announced": "Winners have already been announced.",
}
#: Человеческие формулировки статуса карточки.
STATUS_REASONS_HUMAN: Final[dict[str, str]] = {
    VERIFIED_WINNER_ANNOUNCED: "Winners have already been announced.",
    VERIFIED_EXPIRED: "Deadline has passed (confirmed on the card).",
    VERIFIED_CLOSED: "The bounty is closed.",
    VERIFIED_HUMAN_ONLY: "AI agents are not eligible (human-only bounty).",
    UNKNOWN: "The card could not be verified.",
}
#: Короткие формулировки для таблиц Excel/Markdown (п.7 задания).
SHORT_REASONS: Final[dict[str, str]] = {
    "Winners have already been announced.": "Winners already announced",
    "Deadline has passed (confirmed on the card).": "Deadline has passed",
    "Deadline has passed.": "Deadline has passed",
    "The bounty is closed.": "Bounty closed",
    "AI agents are not eligible (human-only bounty).": "Human-only bounty",
    "The card could not be verified.": "Card could not be verified",
    "Requires own funds / financial risk.": "Requires own funds",
    "Region restriction: you are not eligible for this bounty.": "Region restriction",
    "Region restriction: Russia is excluded.": "Region restriction (Russia)",
    "Region restriction: limited to specific countries.": "Region restriction",
    "Region is not stated on the card.": "Region unknown",
    "No confirmed reward on the card.": "No confirmed reward",
    "Deadline is not confirmed on the card.": "Deadline not confirmed",
    "Agent access is not stated on the card.": "Agent access unknown",
    "Aggregator post, not a real task.": "Aggregator post",
    "Already taken (marked by the aggregator).": "Already taken",
    "Rejected by the certification bureau.": "Rejected by certification",
    "Self-promotion / for-hire post, not a bounty.": "Self-promotion post",
    "Unpaid / volunteer task.": "Unpaid task",
    "Repository is archived.": "Repository archived",
    "The bounty has already been claimed.": "Bounty already claimed",
    "The task is already assigned.": "Already assigned",
    "A pull request already solves it.": "PR already solves it",
    "The card was not found.": "Card not found",
    "Verification was rate limited.": "Verification rate limited",
    "The card could not be verified.": "Card could not be verified",
    REAL_ACTIVITY_EXCLUSION: "Requires own funds",
    "REGION_INELIGIBLE": "Region restriction",
}


def human_deadline(raw: Any, *, confirmed: bool = True) -> str:
    """Дата дедлайна для человека: ``20 Sep 2026, 21:59 UTC``.

    Внутри логики и JSON остаются timezone-aware datetime; здесь только формат.
    """
    moment: datetime | None = parse_utc(raw)
    if moment is None:
        return "unknown" if confirmed else "not confirmed"
    return moment.strftime("%d %b %Y, %H:%M UTC")


def _short_description(entry: Mapping[str, Any]) -> str:
    """Краткое описание карточки (2-4 строки, без полного текста)."""
    text = " ".join(str(entry.get("description") or "").split())
    if not text:
        return ""
    if len(text) <= REPORT_DESCRIPTION_LIMIT:
        return text
    cut = text[:REPORT_DESCRIPTION_LIMIT].rsplit(" ", 1)[0]
    return f"{cut}…"


def hyperlink(url: str, *, enabled: bool) -> str:
    """ANSI OSC 8 hyperlink, где видимый текст — сам URL (fallback бесплатный).

    Если терминал не поддерживает OSC 8, он просто покажет URL. Дополнительно
    hyperlinks можно отключить переменной ``SUPERTEAM_NO_HYPERLINKS=1``.
    """
    if not enabled or not url:
        return url
    return f"\x1b]8;;{url}\x1b\\{url}\x1b]8;;\x1b\\"


def hyperlinks_enabled() -> bool:
    """Показывать ли OSC 8 ссылки: только в интерактивном терминале и без запрета."""
    if os.getenv(NO_HYPERLINKS_ENV, "").strip() not in ("", "0", "false", "False"):
        return False
    import sys

    stream = sys.stdout
    isatty = getattr(stream, "isatty", None)
    return bool(callable(isatty) and isatty())


def markdown_link(url: str, title: str = "Open card") -> str:
    """Markdown-ссылка на карточку (использует реальный ``card_url``)."""
    if not url:
        return "_(card URL missing)_"
    return f"[{title}]({url})"


@dataclass
class ReportItem:
    """Нормализованная запись для отчёта (поля уже существуют в пайплайне)."""

    title: str
    card_url: str
    slug: str
    reward: str
    currency: str
    deadline: str
    deadline_moment: datetime | None
    agent_access: str
    region: str
    priority: str
    score: Any
    verification_status: str
    risk_status: str
    decision: str
    exclusion_reasons: tuple[str, ...] = ()
    why_suitable: tuple[str, ...] = ()
    description_short: str = ""
    listing_type: str = ""
    submissions: Any = None
    difficulty: str = ""
    eligibility: str = ""
    evidence: tuple[str, ...] = ()
    error: str = ""
    is_unknown: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class ReportSections:
    """Разделы отчёта: доступное для агента, исключённое, непроверяемое."""

    available: list[ReportItem] = field(default_factory=list)
    excluded: list[ReportItem] = field(default_factory=list)
    unknown: list[ReportItem] = field(default_factory=list)

    def all_items(self) -> list[ReportItem]:
        """Все записи отчёта (для сводки)."""
        return [*self.available, *self.excluded, *self.unknown]


def why_suitable(entry: Mapping[str, Any]) -> list[str]:
    """Список причин «почему подходит» — только из фактических данных записи."""
    reasons: list[str] = []
    access = str(entry.get("agent_access") or "").upper()
    if access in ("AGENT_ONLY", "AGENT_ALLOWED"):
        reasons.append(f"AI agents allowed ({access})")
    if str(entry.get("verification_status")) == VERIFIED_OPEN:
        reasons.append("Card verified as open")
    if entry.get("deadline_confirmed"):
        reasons.append("Deadline confirmed on card")
    if entry.get("deadline_confirmed") and not entry.get("deadline_passed"):
        reasons.append("Deadline is in the future")
    if entry.get("has_winners") is False:
        reasons.append("Winners not announced yet")
    currency = str(entry.get("reward_currency") or entry.get("token") or "").upper()
    payment_type = str(entry.get("payment_type") or entry.get("reward_type") or "").upper()
    if currency and payment_type == "CRYPTO":
        reasons.append(f"Reward is paid in {currency} (crypto)")
    elif currency and payment_type == "FIAT":
        reasons.append(f"Reward is paid in {currency} (fiat)")
    elif currency:
        reasons.append(f"Reward is paid in {currency}")
    if str(entry.get("financial_risk") or "") == FINANCIAL_RISK_LOW:
        state = str(entry.get("financial_risk_state") or "")
        note = " (text checked on card)" if state == "confirmed_safe" else ""
        reasons.append(f"No own-money requirement detected{note}")
    region = str(entry.get("region") or "")
    if region:
        reasons.append(f"Region: {region}")
    submissions = entry.get("submissions")
    if isinstance(submissions, int) and not isinstance(submissions, bool) and submissions >= 0:
        reasons.append(f"Submissions so far: {submissions}")
    return reasons


def exclusion_reasons_human(entry: Mapping[str, Any]) -> list[str]:
    """Человеческие причины исключения (по кодам пайплайна и флагам записи)."""
    reasons: list[str] = []

    def add(text: str) -> None:
        if text and text not in reasons:
            reasons.append(text)

    for code in entry.get("exclusion_reasons") or []:
        code_text = str(code)
        if code_text.startswith("card verification:"):
            status = code_text.split(":", 1)[1].strip()
            add(STATUS_REASONS_HUMAN.get(status, f"Card status: {status}"))
            continue
        add(EXCLUSION_REASONS_HUMAN.get(code_text, code_text))

    access = str(entry.get("agent_access") or "").upper()
    if access == "HUMAN_ONLY" or str(entry.get("verification_status")) == VERIFIED_HUMAN_ONLY:
        add("AI agents are not eligible (human-only bounty).")
    elif entry.get("agent_access_unknown"):
        add("Agent access is not stated on the card.")
    if entry.get("has_winners"):
        add("Winners have already been announced.")
    if entry.get("deadline_passed"):
        add("Deadline has passed.")
    if str(entry.get("financial_risk") or "") == FINANCIAL_RISK_HIGH:
        add("Requires own funds / financial risk.")
    if str(entry.get("eligibility_status") or "") == "REGION_RESTRICTED":
        add("Region restriction: you are not eligible for this bounty.")
    if str(entry.get("verification_status")) == UNKNOWN:
        add("The card could not be verified.")
    return reasons


#: Сколько исключённых/непроверяемых записей печатать в консоли (остальные — в .md).
CONSOLE_EXCLUDED_LIMIT: Final[int] = 25


def _rule() -> str:
    return "=" * REPORT_RULE_WIDTH


def _thin_rule() -> str:
    return "-" * REPORT_RULE_WIDTH


def print_available_item(item: ReportItem, position: int, *, hyperlinks: bool) -> None:
    """Напечатать одно доступное задание (см. п.6 задания)."""
    print(f"{_thin_rule()}")
    print()
    print(f"[{position}] {item.priority} PRIORITY — Score: {item.score}")
    print(safe(item.title))
    print()
    print(f"  Reward:   {safe(item.reward) or 'UNKNOWN'}")
    if item.currency:
        print(f"  Currency: {safe(item.currency)}")
    print(f"  Deadline: {item.deadline}")
    print(f"  Agent:    {item.agent_access}")
    print(f"  Region:   {safe(item.region)}")
    if item.listing_type:
        print(f"  Type:     {safe(item.listing_type)}")
    if isinstance(item.submissions, int) and not isinstance(item.submissions, bool):
        print(f"  Subs:     {item.submissions}")
    if item.risk_status:
        print(f"  Risk:     {item.risk_status}")
    print()
    print("  Card:")
    print(f"  {hyperlink(item.card_url, enabled=hyperlinks)}")
    if item.why_suitable:
        print()
        print("  Why suitable:")
        for reason in item.why_suitable:
            print(f"  - {safe(reason)}")
    if item.description_short:
        print()
        print(f"  About: {safe(item.description_short)}")
    print()


def print_excluded_item(item: ReportItem) -> None:
    """Напечатать одно исключённое задание с короткой причиной (п.4)."""
    print(f"{_thin_rule()}")
    print()
    print(f"[EXCLUDED] {safe(item.title)}")
    print()
    print(f"  Reward:   {safe(item.reward) or 'UNKNOWN'}")
    print(f"  Deadline: {item.deadline}")
    print(f"  Agent:    {item.agent_access}")
    print(f"  Card:     {safe(item.card_url)}")
    print()
    if not item.exclusion_reasons:
        print("  Reason: excluded by pipeline filters.")
    elif len(item.exclusion_reasons) == 1:
        print(f"  Reason: {safe(item.exclusion_reasons[0])}")
    else:
        print("  Reasons:")
        for reason in item.exclusion_reasons:
            print(f"  - {safe(reason)}")
    print()


def print_unknown_item(item: ReportItem) -> None:
    """Напечатать непроверяемое задание (п.5): причина + ошибка верификации."""
    print(f"{_thin_rule()}")
    print()
    print(f"[UNKNOWN] {safe(item.title)}")
    print()
    print("  Card:")
    print(f"  {safe(item.card_url)}")
    print()
    print("  Reason:")
    print("  Card could not be verified.")
    if item.error:
        print()
        print("  Verification error:")
        print(f"  {safe(item.error)}")
    if item.exclusion_reasons:
        print()
        print("  Details:")
        for reason in item.exclusion_reasons:
            print(f"  - {safe(reason)}")
    print()


def print_report(
    sections: ReportSections,
    summary: Mapping[str, int],
    *,
    hyperlinks: bool | None = None,
    excel_path: str = "",
) -> None:
    """Напечатать компактный итог прогона (п.16/§17 задания).

    Console output is intentionally short: only counters and — when something is
    available — a one-line list without URLs. Details live in the Excel report.
    """
    if hyperlinks is None:
        hyperlinks = hyperlinks_enabled()

    print()
    print(_rule())
    print("SUPERTEAM AGENT")
    print(_rule())
    print()
    print(f"  Discovery:        {summary.get('discovered', 0)}")
    print(f"  Unique:           {summary.get('unique', summary.get('verified', 0))}")
    print(f"  Verified:         {summary.get('verified', 0)}")
    print()
    print(f"  AVAILABLE:        {summary.get('available', 0)}")
    print(f"  EXCLUDED:         {summary.get('excluded', 0)}")
    print(f"  UNKNOWN:          {summary.get('unknown', 0)}")
    print()
    if sections.available:
        print("AVAILABLE FOR AGENT:")
        print()
        for position, item in enumerate(sections.available, start=1):
            reward = safe(item.reward) or "reward unknown"
            print(f"  {position}. {safe(item.title)} — {reward} — {item.priority}")
        print()
    else:
        print("No bounty passed all filters.")
        print()
    if excel_path:
        print("Excel report:")
        print(f"  {excel_path}")
        print()
    print(_rule())


def print_report_details(sections: ReportSections, summary: Mapping[str, int]) -> None:
    """Подробный текстовый отчёт со ссылками (только с ``--debug``)."""
    print()
    print(_rule())
    print("DETAILED REPORT (debug)")
    print(_rule())
    print()
    print(f"AVAILABLE ({len(sections.available)})")
    print()
    for position, item in enumerate(sections.available, start=1):
        print_available_item(item, position, hyperlinks=hyperlinks_enabled())
    print(f"EXCLUDED ({len(sections.excluded)})")
    print()
    for item in sections.excluded[:CONSOLE_EXCLUDED_LIMIT]:
        print_excluded_item(item)
    print(f"UNKNOWN ({len(sections.unknown)})")
    print()
    for item in sections.unknown[:CONSOLE_EXCLUDED_LIMIT]:
        print_unknown_item(item)
    print_statistics_lines(summary)


def print_statistics_lines(summary: Mapping[str, int]) -> None:
    """Счётчики отчёта (используются в debug-режиме)."""
    print("SUMMARY")
    print()
    print(f"  Discovered:        {summary.get('discovered', 0)}")
    print(f"  Verified:          {summary.get('verified', 0)}")
    print()
    print(f"  Available for agent: {summary.get('available', 0)}")
    print(f"  Excluded:            {summary.get('excluded', 0)}")
    print(f"  Unknown:             {summary.get('unknown', 0)}")
    print()
    print(f"  Agent allowed:     {summary.get('agent_allowed', 0)}")
    print(f"  Human only:        {summary.get('human_only', 0)}")
    print(f"  Winner announced:  {summary.get('winner_announced', 0)}")
    print(f"  Expired:           {summary.get('expired', 0)}")
    print()


def generated_timestamp() -> str:
    """Метка времени отчёта (UTC, человекочитаемо)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def render_markdown(
    sections: ReportSections, summary: Mapping[str, int], *, generated_at: str = ""
) -> str:
    """Собрать Markdown-отчёт (п.11 задания)."""
    lines: list[str] = [
        "# Superteam Agent Report",
        "",
        f"Generated: {generated_at or generated_timestamp()}",
        "",
        "## Available for Agent",
        "",
    ]
    if not sections.available:
        lines += [
            "_Нет подтверждённых карточкой открытых задач, подходящих AI-агенту._",
            "",
        ]
    for index, item in enumerate(sections.available, start=1):
        lines += [f"### {index}. {item.title}", ""]
        lines.append(f"**Priority:** {item.priority}  ")
        lines.append(f"**Score:** {item.score}  ")
        lines.append(f"**Reward:** {item.reward or 'UNKNOWN'}  ")
        if item.currency:
            lines.append(f"**Currency:** {item.currency}  ")
        lines.append(f"**Deadline:** {item.deadline}  ")
        lines.append(f"**Agent access:** {item.agent_access}  ")
        lines.append(f"**Region:** {item.region}  ")
        if item.listing_type:
            lines.append(f"**Type:** {item.listing_type}  ")
        if isinstance(item.submissions, int) and not isinstance(item.submissions, bool):
            lines.append(f"**Submissions:** {item.submissions}  ")
        if item.risk_status:
            lines.append(f"**Risk:** {item.risk_status}  ")
        lines += ["", markdown_link(item.card_url), ""]
        if item.why_suitable:
            lines += ["#### Why suitable", ""]
            lines += [f"- {reason}" for reason in item.why_suitable]
            lines.append("")
        if item.description_short:
            lines += ["#### About", "", item.description_short, ""]
        lines += ["---", ""]

    lines += [
        "## Other findings",
        "",
        f"- Excluded: **{summary.get('excluded', 0)}**",
        f"- Unknown (verification failed): **{summary.get('unknown', 0)}**",
        "",
        "Полный список исключённых и непроверяемых задач — в Excel-отчёте "
        "`superteam_report.xlsx` (листы `EXCLUDED` / `UNKNOWN`) и в `superteam_results.json`.",
        "",
    ]

    lines += [
        "## Summary",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Discovered | {summary.get('discovered', 0)} |",
        f"| Verified | {summary.get('verified', 0)} |",
        f"| Available | {summary.get('available', 0)} |",
        f"| Excluded | {summary.get('excluded', 0)} |",
        f"| Unknown | {summary.get('unknown', 0)} |",
        f"| Agent allowed | {summary.get('agent_allowed', 0)} |",
        f"| Human only | {summary.get('human_only', 0)} |",
        f"| Winner announced | {summary.get('winner_announced', 0)} |",
        f"| Expired | {summary.get('expired', 0)} |",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def save_markdown_report(text: str) -> Path:
    """Сохранить человекочитаемый отчёт в ``superteam_report.md``."""
    REPORT_FILE.write_text(text, encoding="utf-8")
    return REPORT_FILE
    for code in entry.get("exclusion_reasons") or []:
        code_text = str(code)
        if code_text.startswith("card verification:"):
            status = code_text.split(":", 1)[1].strip()
            add(STATUS_REASONS_HUMAN.get(status, f"Card status: {status}"))
            continue
        add(EXCLUSION_REASONS_HUMAN.get(code_text, code_text))

    access = str(entry.get("agent_access") or "").upper()
    if access == "HUMAN_ONLY" or str(entry.get("verification_status")) == VERIFIED_HUMAN_ONLY:
        add("AI agents are not eligible (human-only bounty).")
    elif entry.get("agent_access_unknown"):
        add("Agent access is not stated on the card.")
    if entry.get("has_winners"):
        add("Winners have already been announced.")
    if entry.get("deadline_passed"):
        add("Deadline has passed.")
    if str(entry.get("financial_risk") or "") == FINANCIAL_RISK_HIGH:
        add("Requires own funds / financial risk.")
    if str(entry.get("eligibility_status") or "") == "REGION_RESTRICTED":
        add("Region restriction: you are not eligible for this bounty.")
    if str(entry.get("verification_status")) == UNKNOWN:
        add("The card could not be verified.")
    return reasons


def short_reason_text(long_reason: str) -> str:
    """Короткая человеческая причина для таблиц (``Winners already announced``).

    Технические формулировки остаются в JSON; здесь только сжатый вид.
    """
    return SHORT_REASONS.get(long_reason, long_reason.rstrip("."))


def exclusion_reason_short(reasons: Sequence[str]) -> str:
    """Одна строка причин исключения: короткие формулировки через ``; ``."""
    short = [short_reason_text(reason) for reason in reasons]
    unique: list[str] = []
    for text in short:
        if text and text not in unique:
            unique.append(text)
    return "; ".join(unique[:3])


def build_item(entry: Mapping[str, Any]) -> ReportItem:
    """Привести запись пайплайна к нормализованной структуре отчёта."""
    status = str(entry.get("verification_status") or UNKNOWN)
    return ReportItem(
        title=" ".join(str(entry.get("title") or "(no title)").split()),
        card_url=str(entry.get("card_url") or ""),
        slug=str(entry.get("slug") or ""),
        reward=str(entry.get("reward") or ""),
        currency=str(entry.get("reward_currency") or entry.get("token") or ""),
        deadline=human_deadline(
            entry.get("deadline"), confirmed=bool(entry.get("deadline_confirmed"))
        ),
        deadline_moment=parse_utc(entry.get("deadline")),
        agent_access=str(entry.get("agent_access") or "UNKNOWN"),
        region=str(entry.get("region") or entry.get("verified_region") or "UNKNOWN"),
        priority=str(entry.get("priority") or entry.get("effective_priority") or "LOW"),
        score=entry.get("score"),
        verification_status=status,
        risk_status=str(entry.get("financial_risk_state") or entry.get("financial_risk") or ""),
        decision=str(entry.get("final_decision") or entry.get("decision") or ""),
        exclusion_reasons=tuple(exclusion_reasons_human(entry)),
        why_suitable=tuple(why_suitable(entry)),
        description_short=_short_description(entry),
        listing_type=str(entry.get("type") or ""),
        submissions=entry.get("submissions"),
        difficulty=str(entry.get("difficulty") or ""),
        eligibility=str(entry.get("eligibility_status") or ""),
        evidence=tuple(str(line) for line in (entry.get("evidence") or [])[:6]),
        error=str(entry.get("error") or ""),
        is_unknown=status == UNKNOWN,
        raw=dict(entry),
    )


def sort_available(items: Sequence[ReportItem]) -> list[ReportItem]:
    """Сортировка доступных заданий: priority → score ↓ → ближайший deadline."""

    def priority_rank(item: ReportItem) -> int:
        try:
            return PRIORITY_ORDER.index(item.priority.upper())
        except ValueError:
            return len(PRIORITY_ORDER)

    def score_value(item: ReportItem) -> float:
        try:
            return -float(item.score or 0)
        except (TypeError, ValueError):
            return 0.0

    def deadline_key(item: ReportItem) -> datetime:
        if item.deadline_moment is None:
            return datetime.max
        return item.deadline_moment

    return sorted(
        items, key=lambda item: (priority_rank(item), score_value(item), deadline_key(item))
    )


def build_sections(
    entries: Sequence[Mapping[str, Any]], available: Sequence[Mapping[str, Any]]
) -> ReportSections:
    """Разложить записи по разделам: available / excluded / unknown.

    :param entries: все записи прогона.
    :param available: записи, подтверждённые как подходящие для агента
        (результат :func:`superteam_agent.runner.is_verified_open_listing`).
    """
    available_keys = {
        str(item.get("url") or "") or str(item.get("card_url") or "") for item in available
    }
    sections = ReportSections()
    for entry in entries:
        item = build_item(entry)
        keys = {str(entry.get("url") or ""), item.card_url, item.slug}
        if keys & available_keys and item.card_url:
            sections.available.append(item)
        elif item.is_unknown:
            sections.unknown.append(item)
        else:
            sections.excluded.append(item)
    sections.available = sort_available(sections.available)
    return sections


def summary_counts(sections: ReportSections, statistics: Mapping[str, Any]) -> dict[str, int]:
    """Сводные счётчики отчёта (считаются динамически из фактических данных)."""
    items = sections.all_items()
    return {
        "discovered": int(statistics.get("discovered") or 0),
        "verified": int(statistics.get("verified") or 0),
        "unique": int(statistics.get("unique") or statistics.get("verified") or 0),
        "available": len(sections.available),
        "excluded": len(sections.excluded),
        "unknown": len(sections.unknown),
        "risk_excluded": int(statistics.get("risk_excluded") or 0),
        "agent_allowed": sum(
            1 for item in items if item.agent_access.upper() in ("AGENT_ONLY", "AGENT_ALLOWED")
        ),
        "human_only": sum(1 for item in items if item.agent_access.upper() == "HUMAN_ONLY"),
        "winner_announced": sum(
            1 for item in items if item.verification_status == VERIFIED_WINNER_ANNOUNCED
        ),
        "expired": sum(1 for item in items if item.verification_status == VERIFIED_EXPIRED),
    }