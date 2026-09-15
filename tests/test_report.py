"""Тесты человекочитаемого отчёта (п.20 задания).

Проверяются разделы (available/excluded/unknown), человеческие причины, ссылка
на карточку (консоль + Markdown), сортировка, сводка и приоритет карточки над API.
"""
from __future__ import annotations

import asyncio
import json

import httpx

from superteam_agent import report
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

CARD_URL = "https://superteam.fun/earn/listing/slug-1"
FUTURE = "2030-01-01T00:00:00.000Z"
PAST = "2020-01-01T00:00:00.000Z"
DESCRIPTION = (
    "Build a small Python utility that exports the report data to CSV and add a regression "
    "test for the new column order. The task is fully local and uses only open-source libraries."
)


def make_entry(**overrides) -> dict:
    """Запись пайплайна (как в superteam_results.json)."""
    entry = {
        "slug": "slug-1",
        "title": "Fix the CSV export bug",
        "card_url": CARD_URL,
        "url": CARD_URL,
        "reward": "500 USDC",
        "reward_currency": "USDC",
        "token": "USDC",
        "deadline": FUTURE,
        "deadline_utc": "01 Jan 2030 00:00 UTC",
        "deadline_confirmed": True,
        "deadline_passed": False,
        "has_winners": False,
        "agent_access": "AGENT_ALLOWED",
        "agent_access_unknown": False,
        "region": "Global",
        "eligibility_status": "ELIGIBLE",
        "priority": "HIGH",
        "score": 82,
        "verification_status": VERIFIED_OPEN,
        "financial_risk": "LOW",
        "financial_risk_state": "confirmed_safe",
        "final_decision": "CANDIDATE",
        "exclusion_reasons": [],
        "description": DESCRIPTION,
        "type": "bounty",
        "submissions": 21,
        "payment_type": "CRYPTO",
        "evidence": ["card status=open and deadline 2030-01-01T00:00:00.000Z > now"],
    }
    entry.update(overrides)
    return entry


def sections_for(entry: dict) -> report.ReportSections:
    """Разделы отчёта так, как их строит runner: доступность — тем же предикатом."""
    available = [entry] if is_verified_open_listing(entry) else []
    return report.build_sections([entry], available)


def summary_for(entry: dict, *, discovered: int = 1, verified: int = 1) -> dict:
    return report.summary_counts(
        sections_for(entry), {"discovered": discovered, "verified": verified}
    )


# --- 1, 6, 7: доступные задания ------------------------------------------------


def test_1_verified_open_goes_to_available():
    entry = make_entry()
    sections = sections_for(entry)
    assert is_verified_open_listing(entry) is True
    assert [item.title for item in sections.available] == ["Fix the CSV export bug"]
    assert sections.excluded == []
    assert sections.unknown == []


def test_6_agent_only_can_be_available():
    sections = sections_for(make_entry(agent_access="AGENT_ONLY"))
    assert len(sections.available) == 1


def test_7_agent_allowed_can_be_available():
    sections = sections_for(make_entry(agent_access="AGENT_ALLOWED"))
    assert len(sections.available) == 1


# --- 2, 3, 4, 5, 8: исключения и UNKNOWN ---------------------------------------


def test_2_winner_announced_goes_to_excluded():
    entry = make_entry(
        verification_status=VERIFIED_WINNER_ANNOUNCED,
        has_winners=True,
        final_decision="EXCLUDE",
        exclusion_reasons=["card verification: VERIFIED_WINNER_ANNOUNCED"],
    )
    sections = sections_for(entry)
    assert sections.available == []
    assert len(sections.excluded) == 1
    assert "Winners have already been announced." in sections.excluded[0].exclusion_reasons


def test_3_human_only_goes_to_excluded():
    entry = make_entry(
        verification_status=VERIFIED_HUMAN_ONLY,
        agent_access="HUMAN_ONLY",
        final_decision="CANDIDATE",
    )
    sections = sections_for(entry)
    assert sections.available == []
    assert sections.excluded
    assert "AI agents are not eligible (human-only bounty)." in sections.excluded[0].exclusion_reasons


def test_4_deadline_passed_goes_to_excluded():
    entry = make_entry(
        verification_status=VERIFIED_EXPIRED,
        deadline=PAST,
        deadline_passed=True,
        final_decision="EXCLUDE",
        exclusion_reasons=["card verification: VERIFIED_EXPIRED", "card deadline already passed"],
    )
    sections = sections_for(entry)
    assert sections.available == []
    assert "Deadline has passed." in sections.excluded[0].exclusion_reasons
    assert "Deadline has passed (confirmed on the card)." in sections.excluded[0].exclusion_reasons


def test_5_unknown_never_available():
    entry = make_entry(
        verification_status=UNKNOWN,
        deadline_confirmed=False,
        final_decision="EXCLUDE",
        exclusion_reasons=["card verification: UNKNOWN"],
        error="timeout after 20s",
    )
    sections = sections_for(entry)
    assert sections.available == []
    assert len(sections.unknown) == 1
    assert sections.unknown[0].is_unknown is True
    assert sections.excluded == []


def test_8_risk_exclusion_goes_to_excluded():
    entry = make_entry(
        financial_risk="HIGH",
        financial_risk_state="risk_detected",
        final_decision="EXCLUDE",
        exclusion_reasons=["REAL_FINANCIAL_ACTIVITY_REQUIRED"],
    )
    sections = sections_for(entry)
    assert sections.available == []
    assert "Requires own funds / financial risk." in sections.excluded[0].exclusion_reasons


# --- 9, 10: ссылка на карточку -------------------------------------------------


def test_9_card_url_in_markdown_and_console_has_no_url(capsys):
    """В консоли — только короткий список без URL; ссылка живёт в Excel/Markdown."""
    entry = make_entry()
    sections = sections_for(entry)
    report.print_report(
        sections,
        summary_for(entry),
        hyperlinks=False,
        excel_path="superteam_report.xlsx",
    )
    output = capsys.readouterr().out

    assert "SUPERTEAM AGENT" in output
    assert "AVAILABLE:        1" in output
    assert "1. Fix the CSV export bug — 500 USDC — HIGH" in output
    assert "superteam_report.xlsx" in output
    assert CARD_URL not in output  # длинный URL в консоль не выводится

    markdown = report.render_markdown(
        sections, summary_for(entry), generated_at="2026-09-15 08:00 UTC"
    )
    assert CARD_URL in markdown
    assert "## Available for Agent" in markdown


def test_9b_console_when_nothing_available(capsys):
    """Если ничего не прошло фильтры — одна короткая строка, без списка."""
    entry = make_entry(agent_access="HUMAN_ONLY", verification_status=VERIFIED_HUMAN_ONLY)
    sections = sections_for(entry)
    report.print_report(sections, summary_for(entry), excel_path="superteam_report.xlsx")
    output = capsys.readouterr().out

    assert "No bounty passed all filters." in output
    assert "AVAILABLE:        0" in output
    assert CARD_URL not in output


def test_10_markdown_link_and_hyperlink():
    assert report.markdown_link(CARD_URL) == f"[Open card]({CARD_URL})"
    assert report.markdown_link("") == "_(card URL missing)_"

    markdown = report.render_markdown(sections_for(make_entry()), summary_for(make_entry()))
    assert f"[Open card]({CARD_URL})" in markdown

    hyperlinked = report.hyperlink(CARD_URL, enabled=True)
    assert hyperlinked.startswith("\x1b]8;;")
    assert CARD_URL in hyperlinked
    assert report.hyperlink(CARD_URL, enabled=False) == CARD_URL


# --- 11: сортировка ------------------------------------------------------------


def test_11_sorting_priority_score_and_deadline():
    low_priority = make_entry(
        slug="a", title="A", card_url="https://x/a", url="https://x/a", priority="MEDIUM", score=95
    )
    high_low_score = make_entry(
        slug="b", title="B", card_url="https://x/b", url="https://x/b", priority="HIGH", score=50
    )
    high_high_score = make_entry(
        slug="c", title="C", card_url="https://x/c", url="https://x/c", priority="HIGH", score=90
    )
    entries = [low_priority, high_low_score, high_high_score]
    sections = report.build_sections(entries, entries)
    assert [item.title for item in sections.available] == ["C", "B", "A"]

    sooner = make_entry(
        slug="d",
        title="D",
        card_url="https://x/d",
        url="https://x/d",
        priority="HIGH",
        score=60,
        deadline="2030-02-01T00:00:00.000Z",
    )
    later = make_entry(
        slug="e",
        title="E",
        card_url="https://x/e",
        url="https://x/e",
        priority="HIGH",
        score=60,
        deadline="2030-03-01T00:00:00.000Z",
    )
    sections = report.build_sections([later, sooner], [later, sooner])
    assert [item.title for item in sections.available] == ["D", "E"]


# --- 12: сводка ----------------------------------------------------------------


def test_12_summary_counts_are_dynamic():
    available = make_entry()
    expired = make_entry(
        slug="x",
        title="X",
        card_url="https://x/x",
        url="https://x/x",
        verification_status=VERIFIED_EXPIRED,
        deadline=PAST,
        deadline_passed=True,
        final_decision="EXCLUDE",
        exclusion_reasons=["card verification: VERIFIED_EXPIRED"],
    )
    unknown = make_entry(
        slug="u",
        title="U",
        card_url="https://x/u",
        url="https://x/u",
        verification_status=UNKNOWN,
        deadline_confirmed=False,
        final_decision="EXCLUDE",
        exclusion_reasons=["card verification: UNKNOWN"],
    )
    human_only = make_entry(
        slug="h",
        title="H",
        card_url="https://x/h",
        url="https://x/h",
        verification_status=VERIFIED_HUMAN_ONLY,
        agent_access="HUMAN_ONLY",
    )
    winner = make_entry(
        slug="w",
        title="W",
        card_url="https://x/w",
        url="https://x/w",
        verification_status=VERIFIED_WINNER_ANNOUNCED,
        has_winners=True,
        agent_access="AGENT_ONLY",
        final_decision="EXCLUDE",
        exclusion_reasons=["card verification: VERIFIED_WINNER_ANNOUNCED"],
    )
    entries = [available, expired, unknown, human_only, winner]
    sections = report.build_sections(entries, [available])
    counts = report.summary_counts(sections, {"discovered": 33, "verified": 32})

    assert counts["available"] == 1
    assert counts["excluded"] == 3
    assert counts["unknown"] == 1
    assert counts["discovered"] == 33
    assert counts["verified"] == 32
    assert counts["agent_allowed"] == 4
    assert counts["human_only"] == 1
    assert counts["winner_announced"] == 1
    assert counts["expired"] == 1


# --- 13, 14: приоритет карточки над API ----------------------------------------


def card_html(listing: dict | None) -> str:
    payload = {"props": {"pageProps": {"listing": listing}}}
    return (
        "<html><head><title>fixture</title></head><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}</script></body></html>"
    )


def card_listing(**overrides) -> dict:
    listing = {
        "slug": "slug-1",
        "title": "Fix the CSV export bug",
        "status": "open",
        "deadline": FUTURE,
        "rewardAmount": 500,
        "token": "USDC",
        "agentAccess": "AGENT_ALLOWED",
        "isWinnersAnnounced": False,
        "description": DESCRIPTION,
        "type": "bounty",
    }
    listing.update(overrides)
    return listing


def card_result(status: int, body: str) -> dict:
    """Результат card verification на фикстуре (без сети)."""

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(status, text=body)

    async def run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await verify_listing_card(client, "slug-1")

    return asyncio.run(run())


def merged_item(**overrides) -> dict:
    """Discovery-данные API+website (устаревший deadline, статус OPEN)."""
    item = {
        "slug": "slug-1",
        "title": "Fix the CSV export bug",
        "type": "bounty",
        "reward": "500 USDC",
        "reward_amount": 500,
        "token": "USDC",
        "status": "OPEN",
        "deadline": PAST,
        "agent_access": "AGENT_ALLOWED",
        "region": "Global",
        "winners_flagged": False,
        "winners_announced_at": "",
        "source": "website",
        "source_url": "https://superteam.fun/api/listings/?status=open",
        "source_api": True,
        "source_website": True,
        "sources": ["agent_api", "website"],
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


def test_13_api_open_but_card_closed_is_excluded(monkeypatch):
    monkeypatch.delenv("SUPERTEAM_USER_REGION", raising=False)
    card = card_result(200, card_html(card_listing(status="closed")))
    entry = build_final_entry(merged_item(), card)

    assert entry["api_status"] == "OPEN"  # API по-прежнему утверждает OPEN
    assert entry["verification_status"] == VERIFIED_CLOSED

    sections = report.build_sections([entry], [])
    assert sections.available == []
    assert sections.excluded
    assert "The bounty is closed." in sections.excluded[0].exclusion_reasons


def test_14_card_deadline_wins_over_api_deadline(monkeypatch):
    monkeypatch.delenv("SUPERTEAM_USER_REGION", raising=False)
    monkeypatch.delenv("SUPERTEAM_USER_COUNTRY", raising=False)
    card = card_result(200, card_html(card_listing(deadline="2031-05-05T12:00:00.000Z")))
    entry = build_final_entry(merged_item(), card)

    assert entry["api_deadline"] == PAST
    assert entry["website_deadline"] == PAST
    assert entry["deadline_utc"] == "2031-05-05 12:00 UTC"

    sections = report.build_sections([entry], [entry])
    assert len(sections.available) == 1
    # пользователю показывается подтверждённый карточкой deadline в человеческом виде
    assert sections.available[0].deadline == "05 May 2031, 12:00 UTC"