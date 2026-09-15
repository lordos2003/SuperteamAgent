"""Адаптер Opire: публичный API ``https://api.opire.dev/rewards``.

Opire — платформа bounty поверх GitHub Issues: каждая запись содержит ссылку на
конкретный issue (``url``), сумму (``pendingPrice``) и языки (``programmingLanguages``).

Правило проекта соблюдается и здесь: агрегатор — только источник ОБНАРУЖЕНИЯ.
Открытость, отсутствие assignee/claimed PR и реальная сумма награды берутся из
первоисточника — самого GitHub issue (см. :func:`verify_github_issue`).

``pendingPrice`` (USD_CENT) используется только как справочная величина: если в
самом issue сумму найти не удалось, комментарий об этом всё равно попадает в
``notes`` — отчёт не опирается на данные агрегатора как на доказательство.
"""
from __future__ import annotations

from typing import Any, Final

import httpx

from ..config import (
    OPIRE_API_URL,
    OPIRE_MAX_PAGES,
    OPIRE_PAGE_SIZE,
    SOURCE_STATUS_EMPTY,
    SOURCE_STATUS_OK,
    SOURCE_STATUS_PARTIAL,
)
from ..core.models import new_candidate, utc_now_iso
from ..core.verification import (
    github_token,
    parse_github_url,
    verify_bounty_page,
    verify_github_issue,
)
from .base import SourceResult, error_result, fetch_json, finalize_candidate

#: Имя источника в отчёте.
SOURCE_NAME: Final[str] = "opire"

#: Как Opire выплачивает награду (по данным API: суммы в USD_CENT).
PAYMENT_METHOD: Final[str] = "Opire payout (USD)"


def _pending_usd(reward: dict[str, Any]) -> float | None:
    """Перевести ``pendingPrice`` (USD_CENT) в доллары, если поле корректно."""
    price = reward.get("pendingPrice")
    if not isinstance(price, dict):
        return None
    unit = str(price.get("unit") or "").upper()
    value = price.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return None
    if unit == "USD_CENT":
        return round(float(value) / 100.0, 2)
    if unit in ("USD", "US_DOLLAR"):
        return float(value)
    return None


async def collect(
    client: httpx.AsyncClient, *, per_source_limit: int = 25, **_: Any
) -> SourceResult:
    """Собрать rewards из Opire и проверить каждый первоисточник (GitHub issue)."""
    token = github_token()
    diagnostics: dict[str, Any] = {
        "api_url": OPIRE_API_URL,
        "pages_checked": 0,
        "pages": [],
        "api_errors": [],
    }
    rewards: dict[str, dict[str, Any]] = {}

    for page in range(OPIRE_MAX_PAGES):
        result = await fetch_json(client, f"{OPIRE_API_URL}?page={page}&size={OPIRE_PAGE_SIZE}")
        diagnostics["pages_checked"] += 1
        entry: dict[str, Any] = {"page": page, "http_status": result.get("http_status")}
        if not result.get("reachable"):
            entry["error"] = result.get("error") or "unreachable"
            diagnostics["api_errors"].append(f"page {page}: {entry['error']}")
            diagnostics["pages"].append(entry)
            continue
        payload = result.get("json")
        if not isinstance(payload, list):
            entry["error"] = "unexpected payload (list expected)"
            diagnostics["api_errors"].append(f"page {page}: unexpected payload")
            diagnostics["pages"].append(entry)
            continue
        entry["items"] = len(payload)
        new_items = 0
        for reward in payload:
            if not isinstance(reward, dict):
                continue
            url = str(reward.get("url") or "")
            if not url or url in rewards:
                continue
            rewards[url] = reward
            new_items += 1
        entry["new"] = new_items
        diagnostics["pages"].append(entry)

    diagnostics["discovered_total"] = len(rewards)
    if not rewards:
        if diagnostics["api_errors"]:
            return error_result(
                SOURCE_NAME,
                "Opire API недоступен: " + "; ".join(diagnostics["api_errors"][:3]),
                errors=diagnostics["api_errors"][:3],
            )
        return SourceResult(
            name=SOURCE_NAME,
            source_status=SOURCE_STATUS_EMPTY,
            reason="Opire не вернул открытых rewards",
            diagnostics=diagnostics,
            checked_at=utc_now_iso(),
        )

    limit = max(per_source_limit, 0)
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    verified_open = 0

    for url, reward in list(rewards.items())[:limit]:
        parsed = parse_github_url(url)
        if parsed:
            verification = await verify_github_issue(
                client, parsed[0], parsed[1], parsed[2], token=token
            )
        else:
            verification = await verify_bounty_page(client, url)
        if str(verification.get("verified_status")) == "VERIFIED_OPEN":
            verified_open += 1
        if verification.get("error"):
            errors.append(f"{url}: {verification['error']}")

        pending = _pending_usd(reward)
        languages = [str(language) for language in reward.get("programmingLanguages") or []]
        organization = reward.get("organization") or {}
        claimant_count = len(reward.get("claimerUsers") or [])
        candidate = new_candidate(
            source=SOURCE_NAME,
            primary_source=SOURCE_NAME,
            sources=[SOURCE_NAME],
            source_id=str(reward.get("id") or ""),
            title=str(verification.get("title") or reward.get("title") or ""),
            url=str(verification.get("url") or url),
            dashboard_url=url,
            description=str(verification.get("body") or ""),
            repo=f"{parsed[0]}/{parsed[1]}" if parsed else str((reward.get("project") or {}).get("url") or ""),
            language=", ".join(languages),
            labels=[f"opire-claimers:{claimant_count}"],
            reward_amount=None,  # сумма берётся из первоисточника (issue), если она там есть
            reward_currency="",
            payment_method=PAYMENT_METHOD,
            raw_status=str(verification.get("state") or ""),
            freshness=_freshness(verification),
            evidence=[
                f"opire id={reward.get('id')} platform={reward.get('platform')}",
                f"opire pendingPrice={pending} USD (справочно, не подтверждает выплату)",
                f"opire claimers={claimant_count}",
                f"organization={organization.get('name')}",
                f"issue state={verification.get('state')}",
                f"claim markers: {verification.get('claimed_markers')}",
                f"paid markers: {verification.get('paid_markers')}",
            ],
            notes=(
                [str(item) for item in verification.get("reward_evidence") or []]
                + (
                    [f"opire pendingPrice={pending} USD (не подтверждено первоисточником)"]
                    if pending
                    else []
                )
            ),
        )
        items.append(finalize_candidate(candidate, verification))

    status = SOURCE_STATUS_OK
    reason = ""
    if diagnostics["api_errors"] and not items:
        status = SOURCE_STATUS_PARTIAL
        reason = "часть страниц Opire не ответила"
    return SourceResult(
        name=SOURCE_NAME,
        source_status=status,
        reason=reason,
        discovered=len(rewards),
        verified_open=verified_open,
        items=items,
        diagnostics=diagnostics,
        errors=errors[:10],
        checked_at=utc_now_iso(),
    )


def _freshness(verification: dict[str, Any]) -> str:
    """Свежесть задачи по датам первоисточника."""
    updated = str(verification.get("updated_at") or "")
    created = str(verification.get("created_at") or "")
    if updated:
        return f"issue updated_at={updated}"
    if created:
        return f"issue created_at={created}"
    return ""