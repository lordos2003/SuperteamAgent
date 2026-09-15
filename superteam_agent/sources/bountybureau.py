"""Адаптер BountyBureau: ``https://bountybureau.com/api/bounties``.

Bounty Bureau — «certification bureau» для open-source bounty: сервис сам
подтягивает задачи из GitHub и помечает их уровнем доверия (``adj.tier``) и
статусом (``adj.status``: ``open`` / ``taken``), указывая выплату (``adj.payout``)
и первоисточник (``owner/repo`` + ``number``).

Правило проекта соблюдается строго: certified-запись агрегатора — только
ОСНОВАНИЕ для проверки, но не доказательство. Каждый issue проверяется напрямую
через GitHub API (state, assignee, связанные PR, claimed/paid, сумма награды).
"""
from __future__ import annotations

from typing import Any, Final

import httpx

from ..config import (
    BOUNTYBUREAU_API_URL,
    SOURCE_STATUS_EMPTY,
    SOURCE_STATUS_OK,
)
from ..core.models import new_candidate, utc_now_iso
from ..core.verification import github_token, verify_github_issue
from ..secrets import safe
from .base import (
    SourceResult,
    add_source_exclusion,
    error_result,
    fetch_json,
    finalize_candidate,
)

#: Имя источника в отчёте.
SOURCE_NAME: Final[str] = "bountybureau"

#: Уровни сертификации, при которых задачу нельзя считать подтверждённой.
REJECTED_TIERS: Final[tuple[str, ...]] = ("rejected",)
#: Уровни, требующие ручного внимания (не блокируют, но отмечаются).
CAUTION_TIERS: Final[tuple[str, ...]] = ("caution",)


def _payout(item: dict[str, Any]) -> tuple[float | None, bool]:
    """Вернуть ``(сумма_usd, выплата_в_токене)`` из ``adj.payout``."""
    adj = item.get("adj") or {}
    payout = adj.get("payout") or {}
    amount = payout.get("usd")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:
        amount = None
    return (float(amount) if amount is not None else None), bool(payout.get("token"))


def _evidence_text(item: dict[str, Any]) -> list[str]:
    """Собрать доказательства сертификации (good/warn/bad) без домыслов."""
    adj = item.get("adj") or {}
    return [
        f"{entry.get('kind')}: {safe(str(entry.get('text') or ''))[:160]}"
        for entry in adj.get("evidence") or []
        if isinstance(entry, dict)
    ]


def _tier_exclusion(tier: str) -> str:
    """Причина исключения по уровню сертификации (пустая строка — не исключать)."""
    if str(tier).lower() in REJECTED_TIERS:
        return "AGGREGATOR_TIER_REJECTED"
    return ""


async def collect(
    client: httpx.AsyncClient, *, per_source_limit: int = 25, **_: Any
) -> SourceResult:
    """Собрать certified-bounty из BountyBureau и проверить каждый первоисточник."""
    token = github_token()
    result = await fetch_json(client, BOUNTYBUREAU_API_URL)
    diagnostics: dict[str, Any] = {
        "api_url": BOUNTYBUREAU_API_URL,
        "http_status": result.get("http_status"),
        "declared_status": None,
        "generated_at": None,
        "tiers": {},
        "statuses": {},
        "sources": {},
    }
    if not result.get("reachable"):
        return error_result(
            SOURCE_NAME,
            f"BountyBureau API недоступен: {result.get('error') or 'unreachable'}",
        )

    payload = result.get("json")
    if not isinstance(payload, dict):
        return error_result(
            SOURCE_NAME, "BountyBureau API вернул неожиданный формат (объект ожидался)"
        )

    raw_items = [item for item in payload.get("items") or [] if isinstance(item, dict)]
    diagnostics["declared_status"] = payload.get("status")
    diagnostics["generated_at"] = payload.get("generatedAt")
    diagnostics["discovered_total"] = len(raw_items)
    for item in raw_items:
        adj = item.get("adj") or {}
        for bucket, value in (
            ("tiers", adj.get("tier")),
            ("statuses", adj.get("status")),
            ("sources", item.get("source")),
        ):
            key = str(value)
            diagnostics[bucket][key] = diagnostics[bucket].get(key, 0) + 1

    if not raw_items:
        return SourceResult(
            name=SOURCE_NAME,
            source_status=SOURCE_STATUS_EMPTY,
            reason="BountyBureau не вернул ни одной записи",
            diagnostics=diagnostics,
            checked_at=utc_now_iso(),
        )

    # Открытые записи проверяются первыми: они интереснее, и их чаще хватает.
    ordered = sorted(
        raw_items, key=lambda item: 0 if str((item.get("adj") or {}).get("status")) == "open" else 1
    )
    limit = max(per_source_limit, 0)
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    verified_open = 0

    for item in ordered[:limit]:
        owner = str(item.get("owner") or "")
        repo = str(item.get("repo") or "")
        number = item.get("number")
        url = str(item.get("html_url") or "")
        if not owner or not repo or not isinstance(number, int):
            errors.append(f"запись без owner/repo/number пропущена: {url}")
            continue
        verification = await verify_github_issue(client, owner, repo, number, token=token)
        if str(verification.get("verified_status")) == "VERIFIED_OPEN":
            verified_open += 1
        if verification.get("error"):
            errors.append(f"{url}: {verification['error']}")

        adj = item.get("adj") or {}
        tier = str(adj.get("tier") or "")
        aggregator_status = str(adj.get("status") or "")
        amount, token_payout = _payout(item)
        repo_meta = item.get("repoMeta") or {}
        candidate = new_candidate(
            source=SOURCE_NAME,
            primary_source=SOURCE_NAME,
            sources=[SOURCE_NAME],
            source_id=f"{owner}/{repo}#{number}",
            title=str(verification.get("title") or item.get("title") or ""),
            url=str(verification.get("url") or url),
            dashboard_url=str(item.get("html_url") or ""),
            description=str(verification.get("body") or item.get("body") or ""),
            repo=f"{owner}/{repo}",
            language=str(repo_meta.get("language") or ""),
            labels=[f"bountybureau-tier:{tier}", f"bountybureau-status:{aggregator_status}"],
            assignee=str(verification.get("assignee") or item.get("assignee") or ""),
            reward_currency="USDC" if token_payout else ("USD" if amount is not None else ""),
            payment_method=f"BountyBureau certified payout ({item.get('source') or 'GitHub'})",
            raw_status=str(verification.get("state") or item.get("state") or ""),
            freshness=f"aggregator createdAt={item.get('createdAt')}",
            evidence=_evidence_text(item)
            + [
                f"bountybureau tier={tier} score={adj.get('score')} status={aggregator_status}",
                f"racingPR={item.get('racingPR')} contested={adj.get('contested')}",
                f"payout usd={amount} token={token_payout}",
                f"issue state={verification.get('state')}",
            ],
            notes=[str(note) for note in verification.get("reward_evidence") or []],
        )
        # Сумма сертификатора не подменяет данные первоисточника: она лишь fallback.
        if verification.get("reward_amount") is None and amount is not None:
            candidate["reward_amount"] = amount
        entry = finalize_candidate(candidate, verification)

        if aggregator_status == "taken":
            add_source_exclusion(entry, "AGGREGATOR_STATUS_TAKEN", "[EXCLUDED][TAKEN]")
        tier_reason = _tier_exclusion(tier)
        if tier_reason:
            add_source_exclusion(entry, tier_reason, "[EXCLUDED][AGGREGATOR_TIER]")
        if str(tier).lower() in CAUTION_TIERS:
            entry.setdefault("notes", []).append(
                "BountyBureau certification tier is 'caution' — требуется ручная проверка"
            )
        if item.get("racingPR"):
            entry.setdefault("notes", []).append(
                "BountyBureau сообщает о racing PR (конкуренция за bounty)"
            )
        items.append(entry)

    return SourceResult(
        name=SOURCE_NAME,
        source_status=SOURCE_STATUS_OK,
        reason="",
        discovered=len(raw_items),
        verified_open=verified_open,
        items=items,
        diagnostics=diagnostics,
        errors=errors[:10],
        checked_at=utc_now_iso(),
    )