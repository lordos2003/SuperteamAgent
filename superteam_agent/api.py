"""Authenticated-запросы к Superteam Earn Agent API.

Эндпоинты (проверены на живом API):
  * ``GET /api/agents/listings/live`` — список живых заданий;
  * ``GET /api/agents/listings/details/{slug}`` — детали конкретного задания.

Поведение ошибок: ответ API всегда разбирается безопасно — API key и
заголовок Authorization в сообщения не попадают. Повторы выполняются для
временных ошибок (таймаут, 429, 5xx).
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Mapping
from urllib.parse import quote


import httpx

from .config import (
    API_KEY_ENV,
    API_MAX_RETRIES,
    API_RETRY_BACKOFF_SECONDS,
    BASE_URL_ENV,
    CARD_PATH_TEMPLATE,
    DEFAULT_BASE_URL,
    ENV_FILE,
    LIVE_LISTINGS_PATH,
    LISTING_DETAILS_PATH,
    MAX_RESPONSE_SNIPPET,
    REQUEST_TIMEOUT_SECONDS,
)
from .errors import SuperteamApiError
from .secrets import get_api_key, redact, to_safe_json


def get_base_url() -> str:
    """Вернуть единый base URL (Agent API, карточки и фид сайта с того же домена).

    По умолчанию https://superteam.fun; переопределяется переменной
    окружения ``SUPERTEAM_API_BASE_URL``.
    """
    return os.getenv(BASE_URL_ENV, DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL


def card_url(slug: str) -> str:
    """Вернуть публичный URL карточки задания для указанного slug."""
    return f"{get_base_url()}{CARD_PATH_TEMPLATE.format(slug=quote((slug or '').strip(), safe=''))}"


def get_headers() -> dict[str, str]:
    """Вернуть HTTP-заголовки для authenticated запросов к Agent API.

    :returns: словарь с ``Authorization: Bearer <key>`` и ``Accept: application/json``.
    :raises SuperteamApiError: если переменная ``SUPERTEAM_API_KEY`` не задана.
    """
    api_key = get_api_key()
    if not api_key:
        raise SuperteamApiError(
            None,
            f"{API_KEY_ENV} is not set. Add your key to {ENV_FILE.name} and retry",
        )
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def safe_response_snippet(response: httpx.Response) -> str:
    """Короткое безопасное описание тела ответа без ключа и Authorization.

    Из JSON берутся поля ``message``/``error``/``detail``/``description``,
    иначе — компактный JSON целиком. Ответ всегда обрезается по длине.
    """
    payload: Any = None
    try:
        payload = response.json()
    except ValueError:
        payload = None

    message = ""
    if isinstance(payload, Mapping):
        for key in ("message", "error", "detail", "description", "errors", "reason"):
            value = payload.get(key)
            if value not in (None, "", [], {}):
                message = value if isinstance(value, str) else to_safe_json(value, limit=None)
                break
        if not message:
            message = to_safe_json(payload, limit=None)
    elif payload is not None:
        message = to_safe_json(payload, limit=None)
    if not message:
        message = response.text or ""

    message = redact(" ".join(str(message).split()))
    if len(message) > MAX_RESPONSE_SNIPPET:
        message = f"{message[:MAX_RESPONSE_SNIPPET]}... (truncated)"
    return message


def describe_http_error(response: httpx.Response) -> str:
    """Человеко-читаемое описание ошибки по HTTP-коду ответа.

    Поддерживаются коды 400, 401, 403, 404, 429 и 500+.
    Сообщение никогда не содержит API key или заголовок Authorization.
    """
    code = response.status_code

    if code == 400:
        base = "Bad request (400)"
    elif code == 401:
        return "Authentication failed: check SUPERTEAM_API_KEY"
    elif code == 403:
        base = "Access forbidden (403): the agent is not allowed to use this endpoint"
    elif code == 404:
        base = "Resource not found (404)"
    elif code == 429:
        return "Rate limit exceeded"
    elif code >= 500:
        base = f"Server error ({code}) - try again later"
    else:
        base = f"Unexpected HTTP status ({code})"

    detail = safe_response_snippet(response)
    return f"{base}: {detail}" if detail else base


async def request_json(client: httpx.AsyncClient, path: str, params: Mapping[str, Any] | None = None) -> Any:
    """Выполнить GET-запрос с Bearer-авторизацией и вернуть JSON.

    :param client: общий асинхронный HTTP-клиент.
    :param path: относительный путь, например ``/api/agents/listings/live``.
    :param params: необязательные query-параметры.
    :returns: распарсенный JSON ответа.
    :raises SuperteamApiError: при сетевой ошибке, таймауте, ошибке авторизации
        или любом HTTP-коде, отличном от 200.
    """
    url = f"{get_base_url()}{path}"
    headers = get_headers()

    last_error = "unknown error"
    last_status: int | None = None

    for attempt in range(API_MAX_RETRIES + 1):
        try:
            response = await client.get(url, headers=headers, params=dict(params) if params else None)
        except httpx.TimeoutException:
            last_error = f"Request timed out after {REQUEST_TIMEOUT_SECONDS:.0f}s: {redact(url)}"
        except httpx.HTTPError as error:
            last_error = f"Network error: {redact(str(error))}"
        else:
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:
                    raise SuperteamApiError(
                        response.status_code,
                        f"Response is not valid JSON: {safe_response_snippet(response)}",
                    ) from None
            last_status = response.status_code
            if response.status_code not in (429, 500, 502, 503, 504):
                raise SuperteamApiError(response.status_code, describe_http_error(response))

        if attempt < API_MAX_RETRIES:
            await asyncio.sleep(API_RETRY_BACKOFF_SECONDS * (attempt + 1))

    if last_status is not None:
        raise SuperteamApiError(last_status, f"Server kept failing (HTTP {last_status}) after {API_MAX_RETRIES + 1} attempts")
    raise SuperteamApiError(None, f"{last_error}")


async def get_live_listings(client: httpx.AsyncClient) -> Any:
    """Получить список живых заданий: ``GET /api/agents/listings/live``.

    :returns: JSON ответа API (список или объект-обёртка).
    :raises SuperteamApiError: при ошибке HTTP/сети.
    """
    return await request_json(client, LIVE_LISTINGS_PATH)


async def get_listing_details(client: httpx.AsyncClient, slug: str) -> Any:
    """Получить детали задания: ``GET /api/agents/listings/details/{slug}``.

    :param client: общий асинхронный HTTP-клиент.
    :param slug: идентификатор задания (slug).
    :returns: JSON ответа API.
    :raises SuperteamApiError: при пустом slug или ошибке HTTP/сети.
    """
    clean_slug = (slug or "").strip()
    if not clean_slug:
        raise SuperteamApiError(None, "Listing slug is empty")
    path = LISTING_DETAILS_PATH.format(slug=quote(clean_slug, safe=""))
    return await request_json(client, path)
