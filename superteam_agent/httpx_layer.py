"""Асинхронный HTTP-слой: общий ``httpx.AsyncClient`` с повторами.

Повтор выполняется при таймауте, сетевой ошибке, 429 и 5xx. Для 404 и других
постоянных ошибок повторов нет. Используется и для публичных страниц/фида
сайта, и для Agent API.

Параллельность запросов карточек ограничивается семафором, а
:class:`RateLimiter` выдерживает минимальный интервал между стартами запросов
(вежливость к сайту).
"""
from __future__ import annotations

import asyncio
from typing import Any, Final

import httpx

from .config import CONNECT_TIMEOUT_SECONDS, REQUEST_TIMEOUT_SECONDS
from .secrets import redact

#: HTTP-коды, при которых запрос повторяется (временные проблемы).
RETRYABLE_STATUS_CODES: Final[tuple[int, ...]] = (408, 425, 429, 500, 502, 503, 504, 522, 524)


def _build_timeout() -> httpx.Timeout:
    return httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS)


def build_client() -> httpx.AsyncClient:
    """Создать общий асинхронный HTTP-клиент с разумными таймаутами."""
    return httpx.AsyncClient(timeout=_build_timeout(), follow_redirects=True)


class RateLimiter:
    """Ограничивает частоту стартов запросов до одного за ``min_interval`` секунд."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait = self._last + self._min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = loop.time()


def describe_card_status(status_code: int | None) -> str:
    """Описание HTTP-статуса карточки (без секретов)."""
    if status_code is None:
        return "no HTTP response"
    if status_code == 404:
        return "Card page not found (404)"
    if status_code == 429:
        return "Rate limit exceeded (429) while fetching card"
    if status_code >= 500:
        return f"Card page server error ({status_code})"
    if status_code == 403:
        return "Card page access forbidden (403)"
    return f"Card page HTTP status {status_code}"


async def fetch_page(
    client: httpx.AsyncClient,
    url: str,
    *,
    accept: str = "text/html,application/xhtml+xml",
    user_agent: str,
    headers: dict[str, str] | None = None,
    max_retries: int,
    backoff: float,
) -> dict[str, Any]:
    """Скачать страницу с повторами для временных ошибок.

    :returns: словарь ``{"url", "reachable", "http_status", "content_type",
        "length", "text", "error"}``. ``reachable=False`` — страницу получить
        не удалось.
    """
    all_headers = {"Accept": accept, "User-Agent": user_agent}
    if headers:
        all_headers.update(headers)

    last_error = "unknown error"
    last_status: int | None = None

    for attempt in range(max_retries + 1):
        try:
            response = await client.get(url, headers=all_headers)
        except httpx.TimeoutException:
            last_error = f"timeout after {REQUEST_TIMEOUT_SECONDS:.0f}s"
        except httpx.HTTPError as error:
            last_error = f"network error: {redact(str(error))}"
        else:
            last_status = response.status_code
            if response.status_code == 200:
                return {
                    "url": url,
                    "reachable": True,
                    "http_status": 200,
                    "content_type": response.headers.get("content-type", ""),
                    "length": len(response.text),
                    "text": response.text,
                    "error": "",
                }
            last_error = describe_card_status(response.status_code)
            if response.status_code not in RETRYABLE_STATUS_CODES:
                return {
                    "url": url,
                    "reachable": False,
                    "http_status": response.status_code,
                    "content_type": response.headers.get("content-type", ""),
                    "length": 0,
                    "text": "",
                    "error": last_error,
                }

        if attempt < max_retries:
            await asyncio.sleep(backoff * (attempt + 1))

    return {
        "url": url,
        "reachable": False,
        "http_status": last_status,
        "content_type": "",
        "length": 0,
        "text": "",
        "error": f"{last_error} (after {max_retries + 1} attempts)",
    }
