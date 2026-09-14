"""Работа с секретами: API key из .env и redaction-хелперы.

Ключ, claimCode и заголовок Authorization никогда не печатаются — все
сообщения прогоняются через :func:`redact`.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Final

from .config import API_KEY_ENV, MAX_RESPONSE_SNIPPET, REDACTED

_BEARER_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+")


def get_api_key() -> str:
    """Вернуть API key из окружения или пустую строку, если он не задан."""
    return os.getenv(API_KEY_ENV, "").strip()


def redact(text: str) -> str:
    """Убрать из текста API key и любые значения заголовка Authorization."""
    key = get_api_key()
    if key:
        text = text.replace(key, REDACTED)
    return _BEARER_PATTERN.sub(f"Bearer {REDACTED}", text)


def safe(value: Any) -> str:
    """Преобразовать любое значение в строку, гарантированно без секретов."""
    return redact(str(value))


def to_safe_json(value: Any, limit: int | None = MAX_RESPONSE_SNIPPET) -> str:
    """Сериализовать объект в JSON с вырезанными секретами.

    :param limit: максимальная длина результата; ``None`` — без обрезки.
    """
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        text = str(value)
    text = redact(text)
    if limit is not None and len(text) > limit:
        text = f"{text[:limit]}... (truncated)"
    return text
