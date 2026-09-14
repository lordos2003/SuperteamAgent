"""Публичный источник: страницы /earn и JSON-фид сайта Superteam Earn.

Авторизация не используется — это открытые страницы и публичный фид сайта
(его же использует frontend). Базовый URL тот же, что и для Agent API
(см. ``get_base_url``).

Что фактически содержит публичный сайт (проверено на живом сайте):
  * /earn, /earn/all, /earn/bounties, /earn/projects отдают HTTP 200 и
    __NEXT_DATA__, но в pageProps только potentialSession/totalSponsors/totalUsers:
    0 ссылок /earn/listing/ и 0 объектов заданий — лента рендерится JS;
  * /earn/development, /earn/dev, /earn/content, /earn/design -> HTTP 404;
  * Next.js data route /_next/data/{buildId}/earn.json -> те же пустые pageProps;
  * рабочий публичный фид самого сайта (без авторизации):
    /api/listings/?status=open -> актуальные задания (bounty/project)
    с полями slug, title, status, agentAccess, deadline, rewardAmount, token,
    type, isWinnersAnnounced, winnersAnnouncedAt.
"""
from __future__ import annotations

import json
import re
from typing import Any, Final, Mapping, Sequence

import httpx

from .api import get_base_url
from .card import parse_next_data
from .config import PUBLIC_MAX_RETRIES, PUBLIC_RETRY_BACKOFF_SECONDS, PUBLIC_USER_AGENT
from .httpx_layer import fetch_page
from .parse import normalize_listing
from .secrets import redact

#: Публичный JSON-фид сайта (его использует frontend; авторизация не нужна).
WEBSITE_FEED_PATH: Final[str] = "/api/listings/?status=open"
#: Страницы сайта, которые проверяются на наличие карточек в HTML/embedded JSON.
#: Это диагностический набор: лента на них рендерится JS, заданий там нет.
WEBSITE_PAGE_PATHS: Final[tuple[str, ...]] = (
    "/earn",
    "/earn/all",
    "/earn/bounties",
    "/earn/projects",
)

LISTING_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"/earn/listing/([A-Za-z0-9][A-Za-z0-9._\-]*)"
)


async def fetch_public_page(
    client: httpx.AsyncClient,
    url: str,
    accept: str = "text/html,application/xhtml+xml",
) -> dict[str, Any]:
    """GET публичного URL сайта с повторами для временных ошибок.

    Авторизация не используется — это открытые страницы и публичный фид сайта.

    :param client: общий асинхронный HTTP-клиент.
    :param url: полный URL.
    :param accept: значение заголовка Accept.
    :returns: словарь ``{"url", "reachable", "http_status", "content_type",
        "length", "text", "error"}``.
    """
    page = await fetch_page(
        client,
        url,
        accept=accept,
        user_agent=PUBLIC_USER_AGENT,
        max_retries=PUBLIC_MAX_RETRIES,
        backoff=PUBLIC_RETRY_BACKOFF_SECONDS,
    )
    return {
        "url": url,
        "reachable": page["reachable"],
        "http_status": page["http_status"],
        "content_type": page["content_type"],
        "length": page["length"],
        "text": redact(page["text"]),
        "error": page["error"],
    }


def find_listing_records(payload: Any, depth: int = 0) -> list[Mapping[str, Any]]:
    """Рекурсивно найти в JSON объекты-задания (словари со ``slug``).

    Используется для embedded JSON / ``__NEXT_DATA__``: структура заранее не
    предполагается, ищутся любые вложенные объекты, похожие на задание.
    """
    if depth > 6:
        return []
    found: list[Mapping[str, Any]] = []
    if isinstance(payload, Mapping):
        if "slug" in payload and any(
            key in payload for key in ("title", "rewardAmount", "deadline", "agentAccess")
        ):
            found.append(payload)
        for value in payload.values():
            found.extend(find_listing_records(value, depth + 1))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(find_listing_records(item, depth + 1))
    return found


async def collect_website_source(
    client: httpx.AsyncClient, include_diagnostics: bool = True
) -> dict[str, Any]:
    """Собрать актуальные задания с публичного сайта Superteam Earn.

    Сначала (опционально) проверяются страницы ленты (``WEBSITE_PAGE_PATHS``)
    на наличие карточек в HTML / ``__NEXT_DATA__`` / embedded JSON и ссылок
    ``/earn/listing/{slug}``, затем используется публичный JSON-фид сайта
    (``WEBSITE_FEED_PATH``), который фактически и отдаёт актуальную ленту.

    :param client: общий асинхронный HTTP-клиент.
    :param include_diagnostics: проверять ли диагностические страницы
        ``/earn*`` (флажок ``--no-diagnostics`` отключает их).
    :returns: словарь ``{"listings", "diagnostics", "feed", "html_links"}``.
        ``diagnostics`` — фактические данные о страницах (URL, HTTP-статус,
        найден ли ``__NEXT_DATA__``, сколько заданий в embedded JSON, сколько
        ссылок ``/earn/listing/``), ``feed`` — информация о публичном фиде.
    """
    base = get_base_url()
    listings: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    html_links: set[str] = set()

    if include_diagnostics:
        for path in WEBSITE_PAGE_PATHS:
            url = f"{base}{path}"
            page = await fetch_public_page(client, url)
            entry: dict[str, Any] = {
                "url": url,
                "http_status": page["http_status"],
                "reachable": page["reachable"],
                "content_type": page["content_type"],
                "bytes": page["length"],
                "next_data_found": False,
                "embedded_listings_found": 0,
                "listing_links_found": 0,
                "error": page["error"],
            }
            if page["reachable"]:
                text = page["text"]
                next_data = parse_next_data(text)
                entry["next_data_found"] = next_data is not None
                records = find_listing_records(next_data) if next_data is not None else []
                entry["embedded_listings_found"] = len(records)
                for record in records:
                    normalized = normalize_listing(record, "website", url)
                    if normalized["slug"]:
                        listings.setdefault(normalized["slug"], normalized)
                links = set(LISTING_LINK_PATTERN.findall(text))
                html_links |= links
                entry["listing_links_found"] = len(links)
            diagnostics.append(entry)

    feed_url = f"{base}{WEBSITE_FEED_PATH}"
    feed_page = await fetch_public_page(client, feed_url, accept="application/json, text/plain, */*")
    feed_info: dict[str, Any] = {
        "url": feed_url,
        "http_status": feed_page["http_status"],
        "reachable": feed_page["reachable"],
        "items": 0,
        "error": feed_page["error"],
    }
    if feed_page["reachable"]:
        try:
            payload = json.loads(feed_page["text"])
        except ValueError:
            feed_info["error"] = "feed response is not valid JSON"
        else:
            records = payload if isinstance(payload, list) else find_listing_records(payload)
            feed_count = 0
            for record in records:
                if not isinstance(record, Mapping):
                    continue
                normalized = normalize_listing(record, "website", feed_url)
                if normalized["slug"]:
                    listings[normalized["slug"]] = normalized
                    feed_count += 1
            feed_info["items"] = feed_count

    html_count = sum(entry["embedded_listings_found"] for entry in diagnostics)

    return {
        "listings": list(listings.values()),
        "diagnostics": diagnostics,
        "feed": feed_info,
        "html_links": sorted(html_links),
        "html_listings_found": html_count,
    }


def merge_sources(
    api_items: Sequence[Mapping[str, Any]], website_items: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Объединить задания из Agent API и с публичного сайта по slug.

    Для каждой уникальной записи сохраняются оба источника:
    ``source_api`` / ``source_website``, а исходные значения API и сайта
    дублируются в отдельных полях (``api_*`` и ``website_*``), чтобы было видно,
    откуда пришло каждое значение.

    :param api_items: нормализованные записи Agent API.
    :param website_items: нормализованные записи публичного сайта.
    :returns: список уникальных записей (порядок: сначала Agent API).
    """
    merged: dict[str, dict[str, Any]] = {}

    for item in api_items:
        slug = str(item.get("slug") or "")
        if not slug:
            continue
        merged[slug] = {
            **item,
            "source_api": True,
            "source_website": False,
            "sources": ["agent_api"],
            "api_status": item.get("status", ""),
            "api_deadline": item.get("deadline", ""),
            "api_reward": item.get("reward", ""),
            "api_agent_access": item.get("agent_access", ""),
        }

    for item in website_items:
        slug = str(item.get("slug") or "")
        if not slug:
            continue
        entry = merged.get(slug)
        if entry is None:
            merged[slug] = {
                **item,
                "source_api": False,
                "source_website": True,
                "sources": ["website"],
                "website_status": item.get("status", ""),
                "website_deadline": item.get("deadline", ""),
                "website_reward": item.get("reward", ""),
            }
            continue

        entry["source_website"] = True
        entry["sources"] = ["agent_api", "website"]
        entry["website_status"] = item.get("status", "")
        entry["website_deadline"] = item.get("deadline", "")
        entry["website_reward"] = item.get("reward", "")
        # Пустые поля заполняем данными сайта, но ничего не перетираем.
        for key in ("title", "type", "reward", "status", "deadline", "agent_access", "region", "token"):
            if not entry.get(key) and item.get(key):
                entry[key] = item[key]

    return list(merged.values())
