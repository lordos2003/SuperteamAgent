"""Адаптер GitHub: bounty-issues, найденные через GitHub Search API.

Не ограничиваемся словом «bounty»: используются labels популярных платформ
(Algora «💎 Bounty», BountyHub и др.), поиск по ``title`` и по упоминанию USDC.

КРИТИЧЕСКИ ВАЖНО: найденные issue — это только КАНДИДАТЫ. Каждый проверяется по
первоисточнику (state, assignee, связанные PR, признаки claimed/paid, реальная
сумма награды, активность репозитория) через
:func:`superteam_agent.core.verification.verify_github_issue`.
"""
from __future__ import annotations

from typing import Any, Final, Mapping

import httpx

from ..config import (
    GITHUB_API_BASE,
    GITHUB_BOUNTY_QUERIES,
    GITHUB_MAX_VERIFICATIONS,
    SOURCE_STATUS_EMPTY,
    SOURCE_STATUS_OK,
    SOURCE_STATUS_PARTIAL,
)
from ..core.models import new_candidate, utc_now_iso
from ..core.verification import github_get, github_token, parse_github_url, verify_github_issue
from .base import SourceResult, finalize_candidate

#: Имя источника в отчёте.
SOURCE_NAME: Final[str] = "github"

#: Заголовки-мусор: автогенерированные посты-агрегаторы и служебные issue.
NOISE_TITLE_MARKERS: Final[tuple[str, ...]] = (
    "[radar]",
    "bounty alert",
    "bounty digest",
    "bounties found",
)


def _is_noise(title: str) -> bool:
    """Отбросить очевидный мусор до дорогой проверки первоисточника."""
    lowered = (title or "").lower()
    return any(marker in lowered for marker in NOISE_TITLE_MARKERS)


async def search_bounty_issues(
    client: httpx.AsyncClient,
    *,
    token: str = "",
    per_query: int = 10,
    queries: tuple[str, ...] = GITHUB_BOUNTY_QUERIES,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Найти bounty-issues через GitHub Search API.

    :returns: ``(issues, diagnostics)``; ``issues`` — элементы ответа API без
        дубликатов, без pull request'ов и без автогенерированного мусора.
    """
    found: dict[str, dict[str, Any]] = {}
    diagnostics: dict[str, Any] = {
        "queries": [],
        "api_errors": [],
        "rate_limit_remaining": "",
        "unauthenticated": not bool(token),
    }
    for query in queries:
        result = await github_get(
            client,
            f"{GITHUB_API_BASE}/search/issues",
            token=token,
            params={"q": query, "per_page": per_query, "sort": "created", "order": "desc"},
        )
        remaining = str(result.get("headers", {}).get("x-ratelimit-remaining", ""))
        if remaining:
            diagnostics["rate_limit_remaining"] = remaining
        entry: dict[str, Any] = {"query": query, "status": result.get("status"), "found": 0}
        if result.get("error"):
            entry["error"] = result["error"]
            diagnostics["api_errors"].append(f"{query}: {result['error']}")
            diagnostics["queries"].append(entry)
            continue
        payload = result.get("json") or {}
        items = payload.get("items") or []
        entry["total_count"] = payload.get("total_count")
        for item in items:
            if not isinstance(item, Mapping) or item.get("pull_request"):
                continue
            url = str(item.get("html_url") or "")
            parsed = parse_github_url(url)
            if not parsed:
                continue
            owner, repo, number = parsed
            key = f"{owner}/{repo}#{number}"
            if key in found or _is_noise(str(item.get("title") or "")):
                continue
            repository = item.get("repository") or {}
            found[key] = {
                "owner": owner,
                "repo": repo,
                "number": number,
                "title": str(item.get("title") or ""),
                "url": url,
                "state": str(item.get("state") or ""),
                "labels": [str((label or {}).get("name") or "") for label in item.get("labels") or []],
                "comments": int(item.get("comments") or 0),
                "assignees": [
                    str((person or {}).get("login") or "") for person in item.get("assignees") or []
                ],
                "repo_stars": int(repository.get("stargazers_count") or 0),
                "language": str(repository.get("language") or ""),
                "discovered_via": query,
            }
            entry["found"] += 1
        diagnostics["queries"].append(entry)
    return list(found.values()), diagnostics


def _freshness(verification: Mapping[str, Any]) -> str:
    """Свежесть задачи по датам первоисточника (без выдумывания)."""
    updated = str(verification.get("updated_at") or "")
    created = str(verification.get("created_at") or "")
    if updated:
        return f"issue updated_at={updated}"
    if created:
        return f"issue created_at={created}"
    return ""


async def collect(
    client: httpx.AsyncClient,
    *,
    per_source_limit: int = 25,
    max_verifications: int = GITHUB_MAX_VERIFICATIONS,
) -> SourceResult:
    """Собрать и проверить bounty из GitHub.

    :param per_source_limit: сколько кандидатов проверять (ограничение сверху).
    :param max_verifications: жёсткий предел числа проверок за запуск (лимиты API).
    """
    token = github_token()
    issues, diagnostics = await search_bounty_issues(client, token=token)
    diagnostics["discovered_total"] = len(issues)
    diagnostics["token_present"] = bool(token)

    if not issues:
        return SourceResult(
            name=SOURCE_NAME,
            source_status=SOURCE_STATUS_EMPTY,
            reason="GitHub Search API не вернул bounty-issues по заданным запросам",
            discovered=0,
            diagnostics=diagnostics,
            checked_at=utc_now_iso(),
        )

    limit = min(max(per_source_limit, 0), max_verifications, len(issues))
    if limit <= 0:
        return SourceResult(
            name=SOURCE_NAME,
            source_status=SOURCE_STATUS_EMPTY,
            reason="проверка первоисточника не выполнялась (лимит 0)",
            discovered=len(issues),
            diagnostics=diagnostics,
            checked_at=utc_now_iso(),
        )

    items: list[dict[str, Any]] = []
    errors: list[str] = []
    verified_open = 0
    for issue in issues[:limit]:
        verification = await verify_github_issue(
            client, issue["owner"], issue["repo"], issue["number"], token=token
        )
        if str(verification.get("verified_status")) == "VERIFIED_OPEN":
            verified_open += 1
        if verification.get("error"):
            errors.append(f"{issue['url']}: {verification['error']}")
        label_text = " ".join(issue.get("labels") or [])
        candidate = new_candidate(
            source=SOURCE_NAME,
            primary_source=SOURCE_NAME,
            sources=[SOURCE_NAME],
            source_id=f"{issue['owner']}/{issue['repo']}#{issue['number']}",
            title=str(verification.get("title") or issue.get("title") or ""),
            url=str(verification.get("url") or issue.get("url") or ""),
            dashboard_url=str(issue.get("url") or ""),
            description=str(verification.get("body") or ""),
            repo=f"{issue['owner']}/{issue['repo']}",
            language=str(issue.get("language") or ""),
            labels=list(issue.get("labels") or []),
            assignee=str(verification.get("assignee") or ""),
            reward_amount=verification.get("reward_amount"),
            reward_currency=str(verification.get("reward_currency") or ""),
            payment_method="GitHub issue bounty (платформа определяется по labels/комментариям)",
            raw_status=str(verification.get("state") or ""),
            freshness=_freshness(verification),
            evidence=[
                f"issue state={verification.get('state')} (state_reason={verification.get('state_reason')})",
                f"assignees={verification.get('assignees')}",
                f"labels: {label_text}",
                f"linked PRs: {len(verification.get('linked_prs') or [])}",
                f"claim markers: {verification.get('claimed_markers')}",
                f"paid markers: {verification.get('paid_markers')}",
            ],
            notes=[str(item) for item in verification.get("reward_evidence") or []],
        )
        items.append(finalize_candidate(candidate, verification))

    status = SOURCE_STATUS_OK
    reason = ""
    if diagnostics.get("api_errors") and not items:
        status = SOURCE_STATUS_PARTIAL
        reason = "часть поисковых запросов не выполнилась"
    return SourceResult(
        name=SOURCE_NAME,
        source_status=status,
        reason=reason,
        discovered=len(issues),
        verified_open=verified_open,
        items=items,
        diagnostics=diagnostics,
        errors=errors[:10],
        checked_at=utc_now_iso(),
    )