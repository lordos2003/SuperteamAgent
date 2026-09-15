"""Верификация первоисточника задачи (GitHub issue / страница bounty).

КРИТИЧЕСКОЕ ПРАВИЛО проекта: агрегатор или список bounty **не является**
доказательством. Для каждой найденной задачи проверяется первоисточник —
конкретный GitHub issue (через GitHub API) или конкретная страница bounty.

Подтверждается:
  * issue действительно ``open`` (и не ``state_reason=not_planned``);
  * нет assignee (задача не занята исполнителем);
  * нет merge/закрытого PR, закрывающего issue (bounty фактически отработан);
  * нет признаков ``claimed``/``paid``/``awarded`` в комментариях и timeline;
  * награда действительно указана (сумма + валюта), а не «paid bounty» без суммы;
  * issue не является автогенерированным постом-агрегатором.

Ничего не додумывается: если данных нет — статус ``UNKNOWN``/``RATE_LIMITED`` и
соответствующая причина, а не «открыто».
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Final, Mapping

import httpx

from ..config import (
    BOUNTY_ASSIGNED,
    BOUNTY_CLAIMED,
    BOUNTY_CLOSED,
    BOUNTY_NOT_FOUND,
    BOUNTY_PR_LINKED,
    BOUNTY_RATE_LIMITED,
    BOUNTY_UNKNOWN,
    BOUNTY_VERIFIED_OPEN,
    GITHUB_API_BASE,
    GITHUB_MAX_RETRIES,
    GITHUB_RETRY_BACKOFF_SECONDS,
    GITHUB_TOKEN_ENV,
    GITHUB_USER_AGENT,
)
from ..secrets import redact
from .models import parse_money, utc_now_iso

#: Ссылка на GitHub issue/pr.
GITHUB_URL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/(?:issues|pull)/(?P<number>\d+)",
    re.I,
)

#: Признаки того, что bounty уже забрали/выплатили (комментарии и timeline).
CLAIM_MARKERS: Final[tuple[str, ...]] = (
    "bounty has been claimed",
    "bounty was claimed",
    "has been claimed by",
    "bounty is claimed",
    "claimed this bounty",
    "already claimed",
)
PAID_MARKERS: Final[tuple[str, ...]] = (
    "bounty has been paid",
    "bounty was paid",
    "has been paid",
    "payout completed",
    "bounty paid out",
    "reward has been sent",
    "reward was sent",
    "winner selected",
    "winner has been selected",
)
#: Признаки автогенерированного поста-агрегатора вместо реальной задачи.
AGGREGATOR_MARKERS: Final[tuple[str, ...]] = (
    "bounty alert",
    "new opportunit",
    "[radar",
    "radar]",
    "bounty digest",
    "weekly bounty",
    "list of bounties",
    "found bounties",
)
#: Признаки того, что задача фактически закреплена за исполнителем в тексте.
ASSIGN_INTENT_MARKERS: Final[tuple[str, ...]] = (
    "we will assign",
    "already assigned",
    "assigning this to",
    "taken by @",
)

#: Маркеры платформ, которые публикуют bounty прямо в комментариях к issue.
BOUNTY_PLATFORM_MARKERS: Final[tuple[str, ...]] = (
    "bountyhub",
    "issuehunt",
    "algora",
    "opire",
    "bountybureau",
    "bounty of",
)

#: Кэш метаданных репозиториев на время запуска (экономия запросов к API).
_REPO_CACHE: dict[str, dict[str, Any]] = {}


def github_token() -> str:
    """Прочитать токен GitHub из окружения (``GITHUB_TOKEN``), если он задан.

    Токен нужен только для повышенных лимитов API; он никогда не печатается и
    не попадает в отчёты (все строки проходят через :func:`redact`).
    """
    return os.getenv(GITHUB_TOKEN_ENV, "").strip()


def parse_github_url(url: str) -> tuple[str, str, int] | None:
    """Разобрать ссылку GitHub issue/pr в ``(owner, repo, number)``."""
    match = GITHUB_URL_PATTERN.match((url or "").strip())
    if not match:
        return None
    return match.group("owner"), match.group("repo"), int(match.group("number"))


def _headers(token: str) -> dict[str, str]:
    """Заголовки GitHub API (токен добавляется, если он есть)."""
    headers = {
        "User-Agent": GITHUB_USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def github_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    token: str = "",
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """GET GitHub API с повторами для временных ошибок.

    Исключения наружу не выбрасываются: ошибка проверки одной задачи не должна
    прерывать весь поиск.

    :returns: словарь ``{"status", "json", "text", "headers", "error",
        "rate_limited"}``.
    """
    last_error = ""
    last_status: int | None = None
    for attempt in range(GITHUB_MAX_RETRIES + 1):
        try:
            response = await client.get(url, headers=_headers(token), params=dict(params or {}))
        except httpx.TimeoutException:
            last_error = "timeout"
        except httpx.HTTPError as error:
            last_error = f"network error: {redact(str(error))}"
        else:
            remaining = response.headers.get("x-ratelimit-remaining")
            rate_limited = remaining == "0" and response.status_code in (403, 429)
            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    return {
                        "status": 200,
                        "json": None,
                        "text": response.text[:400],
                        "headers": dict(response.headers),
                        "error": "response is not valid JSON",
                        "rate_limited": False,
                    }
                return {
                    "status": 200,
                    "json": payload,
                    "text": "",
                    "headers": dict(response.headers),
                    "error": "",
                    "rate_limited": False,
                }
            last_status = response.status_code
            if rate_limited:
                return {
                    "status": response.status_code,
                    "json": None,
                    "text": response.text[:200],
                    "headers": dict(response.headers),
                    "error": "GitHub API rate limit exhausted",
                    "rate_limited": True,
                }
            if response.status_code not in (429, 500, 502, 503, 504):
                return {
                    "status": response.status_code,
                    "json": None,
                    "text": response.text[:200],
                    "headers": dict(response.headers),
                    "error": f"HTTP {response.status_code}",
                    "rate_limited": False,
                }
            last_error = f"temporary HTTP {response.status_code}"
        if attempt < GITHUB_MAX_RETRIES:
            await asyncio.sleep(GITHUB_RETRY_BACKOFF_SECONDS * (attempt + 1))
    return {
        "status": last_status,
        "json": None,
        "text": "",
        "headers": {},
        "error": f"{last_error} (after {GITHUB_MAX_RETRIES + 1} attempts)",
        "rate_limited": False,
    }


def text_hits(text: str, markers: tuple[str, ...]) -> list[str]:
    """Найти в тексте сработавшие маркеры (без учёта регистра)."""
    lowered = (text or "").lower()
    return [marker for marker in markers if marker in lowered]


def extract_issue_reward(
    issue: Mapping[str, Any], extra_text: str = ""
) -> tuple[float | None, str, list[str]]:
    """Найти сумму награды в labels / title / body / bounty-комментариях.

    Приоритет — labels платформ (Algora «💎 $500»), затем title, body и
    комментарии, где платформы публикуют «A bounty of $X has been created».

    :returns: ``(amount, currency, evidence)``; ``(None, "", [])`` если суммы нет.
    """
    evidence: list[str] = []
    sources: list[tuple[str, str]] = []
    for label in issue.get("labels") or []:
        name = label.get("name") if isinstance(label, Mapping) else str(label)
        if name:
            sources.append((str(name), "label"))
    sources.append((str(issue.get("title") or ""), "title"))
    body = str(issue.get("body") or "")
    if body:
        sources.append((body[:4000], "body"))
    if extra_text:
        sources.append((extra_text[:4000], "bounty comment"))

    for text, origin in sources:
        amount, currency = parse_money(text)
        if amount and amount > 0:
            evidence.append(f"reward from {origin}: {' '.join(text.split())[:120]}")
            return amount, currency, evidence
    return None, "", evidence


async def fetch_repo_meta(
    client: httpx.AsyncClient, owner: str, repo: str, *, token: str = ""
) -> dict[str, Any]:
    """Метаданные репозитория (звёзды, язык, архивность) с кэшем на запуск.

    Нужны для оценки «живости» проекта: архивированный репозиторий не может
    принимать новые bounty-работы.
    """
    key = f"{owner.lower()}/{repo.lower()}"
    if key in _REPO_CACHE:
        return _REPO_CACHE[key]
    result = await github_get(client, f"{GITHUB_API_BASE}/repos/{owner}/{repo}", token=token)
    payload = result.get("json") or {}
    meta = {
        "stars": payload.get("stargazers_count"),
        "language": payload.get("language") or "",
        "archived": bool(payload.get("archived")),
        "disabled": bool(payload.get("disabled")),
        "pushed_at": payload.get("pushed_at") or "",
        "open_issues": payload.get("open_issues_count"),
        "html_url": payload.get("html_url") or "",
        "error": result.get("error", ""),
    }
    _REPO_CACHE[key] = meta
    return meta


async def fetch_linked_pulls(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    number: int,
    timeline: list[Any],
    *,
    token: str = "",
    max_checks: int = 3,
) -> list[dict[str, Any]]:
    """Состояния PR, связанных с issue.

    Из timeline берутся события ``cross-referenced``/``connected`` с pull
    request, затем проверяется фактическое состояние каждого PR: merge или
    закрытие означает, что bounty практически занят.
    """
    numbers: list[int] = []
    for event in timeline:
        if not isinstance(event, Mapping):
            continue
        source = event.get("source") or {}
        issue = source.get("issue") if isinstance(source, Mapping) else None
        if isinstance(issue, Mapping) and issue.get("pull_request"):
            pr_number = issue.get("number")
            if isinstance(pr_number, int) and pr_number not in numbers:
                numbers.append(pr_number)
        elif event.get("event") == "connected":
            continue
    linked: list[dict[str, Any]] = []
    for pr_number in numbers[:max_checks]:
        result = await github_get(
            client, f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}", token=token
        )
        payload = result.get("json") or {}
        if not payload:
            linked.append({"number": pr_number, "state": "unknown", "merged": False, "error": result.get("error", "")})
            continue
        linked.append(
            {
                "number": pr_number,
                "state": payload.get("state") or "",
                "merged": bool(payload.get("merged")),
                "merged_at": payload.get("merged_at") or "",
                "html_url": payload.get("html_url") or "",
                "title": (payload.get("title") or "")[:120],
            }
        )
    return linked


async def verify_github_issue(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    number: int,
    *,
    token: str = "",
    max_pr_checks: int = 3,
) -> dict[str, Any]:
    """Проверить конкретный GitHub issue как первоисточник bounty.

    Запрашиваются issue, комментарии, timeline и метаданные репозитория; при
    наличии связанных PR проверяется их состояние. Признаки не додумываются:
    статус ``UNKNOWN``/``RATE_LIMITED`` вместо «открыто», если данных получить
    не удалось.

    :returns: словарь с ``verified_status`` (см. ``BOUNTY_*``), доказательствами,
        наградой и флагами (claimed/paid/aggregator).
    """
    api = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{number}"
    issue_result = await github_get(client, api, token=token)
    result: dict[str, Any] = {
        "verified_status": BOUNTY_UNKNOWN,
        "verified_at": utc_now_iso(),
        "url": f"https://github.com/{owner}/{repo}/issues/{number}",
        "repo": f"{owner}/{repo}",
        "state": "",
        "state_reason": "",
        "title": "",
        "body": "",
        "assignee": "",
        "assignees": [],
        "labels": [],
        "comments_count": 0,
        "comments_checked": 0,
        "locked": False,
        "created_at": "",
        "updated_at": "",
        "closed_at": "",
        "linked_prs": [],
        "claimed_markers": [],
        "paid_markers": [],
        "aggregator_markers": [],
        "assign_intent_markers": [],
        "platform_markers": [],
        "reward_amount": None,
        "reward_currency": "",
        "reward_evidence": [],
        "repo_meta": {},
        "api_requests": 1,
        "rate_limit_remaining": str(issue_result.get("headers", {}).get("x-ratelimit-remaining", "")),
        "error": "",
    }

    if issue_result["rate_limited"]:
        result["verified_status"] = BOUNTY_RATE_LIMITED
        result["error"] = "GitHub API rate limit exhausted"
        return result
    if issue_result["status"] == 404:
        result["verified_status"] = BOUNTY_NOT_FOUND
        result["error"] = "primary source not found (HTTP 404)"
        return result
    payload = issue_result.get("json")
    if not isinstance(payload, Mapping):
        result["error"] = issue_result.get("error") or "no issue data"
        return result

    result["state"] = str(payload.get("state") or "")
    result["state_reason"] = str(payload.get("state_reason") or "")
    result["title"] = str(payload.get("title") or "")
    result["body"] = str(payload.get("body") or "")
    result["locked"] = bool(payload.get("locked"))
    result["comments_count"] = int(payload.get("comments") or 0)
    result["created_at"] = str(payload.get("created_at") or "")
    result["updated_at"] = str(payload.get("updated_at") or "")
    result["closed_at"] = str(payload.get("closed_at") or "")
    result["labels"] = [
        str(label.get("name")) for label in payload.get("labels") or [] if isinstance(label, Mapping)
    ]
    assignees = [
        str(person.get("login"))
        for person in payload.get("assignees") or []
        if isinstance(person, Mapping) and person.get("login")
    ]
    if not assignees and isinstance(payload.get("assignee"), Mapping):
        login = payload["assignee"].get("login")
        if login:
            assignees = [str(login)]
    result["assignees"] = assignees
    result["assignee"] = assignees[0] if assignees else ""

    # --- комментарии: платформы публикуют bounty и признаки claim/paid там ---
    comments_text = ""
    comments_result = await github_get(
        client, f"{api}/comments", token=token, params={"per_page": 100}
    )
    result["api_requests"] += 1
    comments = comments_result.get("json") if comments_result["status"] == 200 else None
    if isinstance(comments, list):
        keep = [str(item.get("body") or "") for item in comments if isinstance(item, Mapping)]
        result["comments_checked"] = len(keep)
        comments_text = "\n".join(keep)
    # --- timeline: события assigned / cross-referenced / closed ---
    timeline_result = await github_get(
        client, f"{api}/timeline", token=token, params={"per_page": 100}
    )
    result["api_requests"] += 1
    timeline = timeline_result.get("json") if timeline_result["status"] == 200 else []
    if not isinstance(timeline, list):
        timeline = []
    for event in timeline:
        if isinstance(event, Mapping) and event.get("event") == "assigned":
            assignee = (event.get("assignee") or {}).get("login")
            if assignee and str(assignee) not in result["assignees"]:
                result["assignees"].append(str(assignee))
                result["assignee"] = result["assignee"] or str(assignee)

    # --- метаданные репозитория (архивность, активность, язык) ---
    result["repo_meta"] = await fetch_repo_meta(client, owner, repo, token=token)
    result["api_requests"] += 1

    # --- связанные PR: merge/closed означает, что bounty фактически занят ---
    linked = await fetch_linked_pulls(
        client, owner, repo, number, timeline, token=token, max_checks=max_pr_checks
    )
    result["linked_prs"] = linked
    result["api_requests"] += len(linked)

    combined = "\n".join(
        [result["title"], result["body"], " ".join(result["labels"]), comments_text]
    )
    result["claimed_markers"] = text_hits(combined, CLAIM_MARKERS)
    result["paid_markers"] = text_hits(combined, PAID_MARKERS)
    result["aggregator_markers"] = text_hits(combined, AGGREGATOR_MARKERS)
    result["assign_intent_markers"] = text_hits(combined, ASSIGN_INTENT_MARKERS)
    result["platform_markers"] = text_hits(combined, BOUNTY_PLATFORM_MARKERS)

    amount, currency, reward_evidence = extract_issue_reward(payload, comments_text)
    result["reward_amount"] = amount
    result["reward_currency"] = currency
    result["reward_evidence"] = reward_evidence

    status = BOUNTY_VERIFIED_OPEN
    if result["state"] != "open" or result["state_reason"] == "not_planned":
        status = BOUNTY_CLOSED
    elif result["locked"]:
        status = BOUNTY_CLOSED
    elif result["paid_markers"] or result["claimed_markers"]:
        status = BOUNTY_CLAIMED
    elif result["assignees"]:
        status = BOUNTY_ASSIGNED
    elif any(pr.get("merged") or pr.get("state") == "closed" for pr in linked):
        status = BOUNTY_PR_LINKED
    result["verified_status"] = status
    return result


#: Маркеры состояния на произвольной странице bounty (не GitHub).
PAGE_CLOSED_MARKERS: Final[tuple[str, ...]] = (
    "bounty is closed",
    "bounty closed",
    "no longer accepting",
    "this bounty has ended",
    "position filled",
    "already claimed",
    "bounty has been paid",
    "expired",
)
PAGE_OPEN_MARKERS: Final[tuple[str, ...]] = (
    "open bounty",
    "claim this bounty",
    "submit a pull request",
    "accepting submissions",
    "still open",
)


async def verify_bounty_page(
    client: httpx.AsyncClient, url: str, *, max_retries: int = 2, backoff: float = 2.0
) -> dict[str, Any]:
    """Проверить первоисточник-bounty, у которого нет GitHub issue (страница).

    Используется для задач, найденных на собственной странице платформы. Если
    страницу получить не удалось — статус ``UNKNOWN`` с причиной, а не «открыто».
    """
    from ..config import PUBLIC_MAX_RETRIES, PUBLIC_RETRY_BACKOFF_SECONDS
    from ..httpx_layer import fetch_page
    from ..config import PUBLIC_USER_AGENT

    page = await fetch_page(
        client,
        url,
        accept="text/html,application/xhtml+xml",
        user_agent=PUBLIC_USER_AGENT,
        max_retries=max_retries or PUBLIC_MAX_RETRIES,
        backoff=backoff or PUBLIC_RETRY_BACKOFF_SECONDS,
    )
    text = " ".join((page.get("text") or "").lower().split())
    closed_hits = text_hits(text, PAGE_CLOSED_MARKERS)
    open_hits = text_hits(text, PAGE_OPEN_MARKERS)
    status = BOUNTY_UNKNOWN
    if not page.get("reachable"):
        status = BOUNTY_NOT_FOUND
    elif closed_hits:
        status = BOUNTY_CLOSED
    elif open_hits:
        status = BOUNTY_VERIFIED_OPEN
    return {
        "verified_status": status,
        "verified_at": utc_now_iso(),
        "url": url,
        "state": "open" if status == BOUNTY_VERIFIED_OPEN else ("closed" if status == BOUNTY_CLOSED else ""),
        "http_status": page.get("http_status"),
        "open_markers": open_hits,
        "closed_markers": closed_hits,
        "error": page.get("error", ""),
        "evidence": [f"page markers: open={open_hits} closed={closed_hits}"],
    }


#: Как статус верификации превращается в причину исключения и тег лога.
VERIFICATION_EXCLUSIONS: Final[dict[str, tuple[str, str]]] = {
    BOUNTY_CLOSED: ("CLOSED", "[EXCLUDED][CLOSED]"),
    BOUNTY_ASSIGNED: ("ASSIGNED", "[EXCLUDED][ASSIGNED]"),
    BOUNTY_PR_LINKED: ("PR_LINKED", "[EXCLUDED][PR_LINKED]"),
    BOUNTY_CLAIMED: ("BOUNTY_CLAIMED", "[EXCLUDED][CLAIMED]"),
    BOUNTY_NOT_FOUND: ("NOT_FOUND", "[EXCLUDED][NOT_FOUND]"),
    BOUNTY_RATE_LIMITED: ("RATE_LIMITED", "[EXCLUDED][RATE_LIMITED]"),
    BOUNTY_UNKNOWN: ("UNVERIFIED", "[EXCLUDED][UNVERIFIED]"),
}


def verification_exclusion(verified_status: str) -> tuple[str, str]:
    """Вернуть ``(exclusion_reason, log_tag)`` для статуса верификации.

    ``VERIFIED_OPEN`` не даёт исключения — задача проходит дальше к фильтрам.
    """
    if verified_status == BOUNTY_VERIFIED_OPEN:
        return "", ""
    return VERIFICATION_EXCLUSIONS.get(verified_status, ("UNVERIFIED", "[EXCLUDED][UNVERIFIED]"))