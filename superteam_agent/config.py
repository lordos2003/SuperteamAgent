"""Конфигурация: пути, таймауты и константы статусов.

Часть значений можно переопределить переменными окружения (см. API_KEY_ENV,
BASE_URL_ENV, USER_REGION_ENVS).
"""
from __future__ import annotations

from pathlib import Path
from typing import Final

#: Корень проекта (родитель каталога пакета) — рядом лежит .env и артефакты.
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
ENV_FILE: Final[Path] = PROJECT_ROOT / ".env"
API_KEY_ENV: Final[str] = "SUPERTEAM_API_KEY"
BASE_URL_ENV: Final[str] = "SUPERTEAM_API_BASE_URL"
#: Единый base URL: Agent API, публичные карточки и фид сайта — один и тот же
#: домен (по умолчанию https://superteam.fun).
DEFAULT_BASE_URL: Final[str] = "https://superteam.fun"

#: Эндпоинты Agent API (относительные пути от base URL).
LIVE_LISTINGS_PATH: Final[str] = "/api/agents/listings/live"
LISTING_DETAILS_PATH: Final[str] = "/api/agents/listings/details/{slug}"
#: Публичная карточка задания на сайте Superteam Earn (не Agent API).
CARD_PATH_TEMPLATE: Final[str] = "/earn/listing/{slug}"

REQUEST_TIMEOUT_SECONDS: Final[float] = 20.0
CONNECT_TIMEOUT_SECONDS: Final[float] = 10.0
MAX_RESPONSE_SNIPPET: Final[int] = 300
DEFAULT_SHOW_LISTINGS: Final[int] = 10
DEFAULT_DETAILS_LIMIT: Final[int] = 3

#: Повторы и задержка для запросов к карточкам (временные ошибки).
CARD_MAX_RETRIES: Final[int] = 2
CARD_RETRY_BACKOFF_SECONDS: Final[float] = 2.0
CARD_USER_AGENT: Final[str] = "Mozilla/5.0 (compatible; SuperteamAgent/1.0)"
#: Повторы и задержка для публичных страниц/фида сайта.
PUBLIC_MAX_RETRIES: Final[int] = 2
PUBLIC_RETRY_BACKOFF_SECONDS: Final[float] = 2.0
PUBLIC_USER_AGENT: Final[str] = "Mozilla/5.0 (compatible; SuperteamAgent/1.0)"
#: Повторы запросов к Agent API (раньше их не было, а README обещал).
API_MAX_RETRIES: Final[int] = 2
API_RETRY_BACKOFF_SECONDS: Final[float] = 2.0
#: Вежливость к сайту: минимальный интервал между стартами запросов карточек.
REQUEST_MIN_INTERVAL_SECONDS: Final[float] = 0.3
#: Сколько карточек проверять параллельно.
CARD_CONCURRENCY: Final[int] = 4

#: Ограничение длины текста описания задания в отчёте.
CARD_DESCRIPTION_LIMIT: Final[int] = 600
#: Полный текст описания (используется только для анализа риска, не для вывода).
CARD_DESCRIPTION_FULL_LIMIT: Final[int] = 20000
#: Ограничение длины requirements/eligibility текста.
CARD_REQUIREMENTS_LIMIT: Final[int] = 4000

REDACTED: Final[str] = "***REDACTED***"
#: Плейсхолдер для отсутствующих значений (только ASCII — безопасно для любой консоли).
PLACEHOLDER: Final[str] = "-"

#: Файлы-артефакты запуска (рядом с .env).
VERIFIED_LISTINGS_FILE: Final[Path] = PROJECT_ROOT / "verified_listings.json"
RESULTS_FILE: Final[Path] = PROJECT_ROOT / "superteam_results.json"

#: Значения поля ``verification_status`` из verify_listing_card().
VERIFIED_OPEN: Final[str] = "VERIFIED_OPEN"
EXPIRED: Final[str] = "EXPIRED"
CLOSED: Final[str] = "CLOSED"
COMPLETED: Final[str] = "COMPLETED"
WINNERS_ANNOUNCED: Final[str] = "WINNERS_ANNOUNCED"
NOT_FOUND: Final[str] = "NOT_FOUND"
UNKNOWN: Final[str] = "UNKNOWN"

#: Все возможные статусы проверки (для сводки и JSON-отчёта).
ALL_VERIFICATION_STATUSES: Final[tuple[str, ...]] = (
    VERIFIED_OPEN,
    EXPIRED,
    CLOSED,
    COMPLETED,
    WINNERS_ANNOUNCED,
    NOT_FOUND,
    UNKNOWN,
)
#: Статусы, при которых задание исключается из кандидатов.
EXCLUDED_STATUSES: Final[tuple[str, ...]] = (
    EXPIRED,
    CLOSED,
    COMPLETED,
    WINNERS_ANNOUNCED,
    NOT_FOUND,
)
