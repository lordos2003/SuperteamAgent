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

#: Модель статусов проверки карточки (card verification).
#:
#: * ``VERIFIED_OPEN`` — карточка открылась и подтверждает открытый bounty;
#: * ``VERIFIED_CLOSED`` — карточка подтверждает закрытие/completed;
#: * ``VERIFIED_EXPIRED`` — карточка подтверждает, что deadline уже прошёл;
#: * ``VERIFIED_WINNER_ANNOUNCED`` — объявлены победители;
#: * ``VERIFIED_HUMAN_ONLY`` — карточка явно говорит, что bounty только для людей;
#: * ``UNKNOWN`` — статус определить не удалось (страница, парсер, данные).
#:
#: ``UNKNOWN`` НИКОГДА не превращается в ``VERIFIED_OPEN``: API-статус OPEN не
#: является доказательством, доказательство даёт только карточка.
VERIFIED_OPEN: Final[str] = "VERIFIED_OPEN"
VERIFIED_CLOSED: Final[str] = "VERIFIED_CLOSED"
VERIFIED_EXPIRED: Final[str] = "VERIFIED_EXPIRED"
VERIFIED_WINNER_ANNOUNCED: Final[str] = "VERIFIED_WINNER_ANNOUNCED"
VERIFIED_HUMAN_ONLY: Final[str] = "VERIFIED_HUMAN_ONLY"
UNKNOWN: Final[str] = "UNKNOWN"

#: Устаревшие имена статусов (обратная совместимость кода и отчётов):
#: ``COMPLETED`` — подтверждённое закрытие, ``NOT_FOUND`` — статус определить
#: не удалось (страница не найдена), поэтому оба сводятся к новым значениям.
CLOSED: Final[str] = VERIFIED_CLOSED
COMPLETED: Final[str] = VERIFIED_CLOSED
EXPIRED: Final[str] = VERIFIED_EXPIRED
WINNERS_ANNOUNCED: Final[str] = VERIFIED_WINNER_ANNOUNCED
NOT_FOUND: Final[str] = UNKNOWN

#: Все возможные статусы проверки (для сводки и JSON-отчёта).
ALL_VERIFICATION_STATUSES: Final[tuple[str, ...]] = (
    VERIFIED_OPEN,
    VERIFIED_CLOSED,
    VERIFIED_EXPIRED,
    VERIFIED_WINNER_ANNOUNCED,
    VERIFIED_HUMAN_ONLY,
    UNKNOWN,
)
#: Статусы, при которых задание исключается из кандидатов.
EXCLUDED_STATUSES: Final[tuple[str, ...]] = (
    VERIFIED_CLOSED,
    VERIFIED_EXPIRED,
    VERIFIED_WINNER_ANNOUNCED,
)
#: Всё, что не подтверждено открытым (в т.ч. human-only и UNKNOWN).
NON_OPEN_STATUSES: Final[tuple[str, ...]] = tuple(
    status for status in ALL_VERIFICATION_STATUSES if status != VERIFIED_OPEN
)

#: --- Кэш проверки карточек (одна и та же карточка не скачивается слишком часто).
#: TTL настраивается переменной окружения ``SUPERTEAM_VERIFICATION_CACHE_TTL``
#: (секунды); ``0`` полностью отключает кэш. Кэш никогда не используется вечно:
#: по истечении TTL карточка проверяется заново.
VERIFICATION_CACHE_FILE: Final[Path] = PROJECT_ROOT / "verification_cache.json"
VERIFICATION_CACHE_TTL_ENV: Final[str] = "SUPERTEAM_VERIFICATION_CACHE_TTL"
VERIFICATION_CACHE_TTL_SECONDS: Final[int] = 900

#: --- Состояние финансового риска. Разделяются три состояния:
#: ``confirmed_safe`` (текст проверен, требований к деньгам исполнителя нет),
#: ``unknown`` (информации недостаточно — НЕ доказательство безопасности),
#: ``risk_detected`` (найдены требования депозита/своих средств и т.п.).
FINANCIAL_STATE_CONFIRMED_SAFE: Final[str] = "confirmed_safe"
FINANCIAL_STATE_UNKNOWN: Final[str] = "unknown"
FINANCIAL_STATE_RISK_DETECTED: Final[str] = "risk_detected"
#: Минимальная длина описания с карточки, при которой отсутствие риск-паттернов
#: считается подтверждённо безопасным (короткий текст — «недостаточно данных»).
MIN_TEXT_FOR_FINANCIAL_LOW: Final[int] = 80

#: --- PRE-FILTER перед проверкой карточек: сколько кандидатов вообще брать в
#: проверку за один прогон (0 = без ограничения). Защищает от ситуации, когда
#: лимит проверки тратится на устаревшие API-записи.
PRE_FILTER_MAX_CANDIDATES: Final[int] = 200

#: --- Человекочитаемый отчёт ---
#: Excel-отчёт (основной пользовательский результат) рядом с остальными артефактами.
EXCEL_REPORT_FILE: Final[Path] = PROJECT_ROOT / "superteam_report.xlsx"
#: Markdown-отчёт рядом с остальными артефактами (открывается в VS Code/GitHub).
REPORT_FILE: Final[Path] = PROJECT_ROOT / "superteam_report.md"
#: Отключить ANSI OSC 8 hyperlinks (если терминал их не поддерживает).
NO_HYPERLINKS_ENV: Final[str] = "SUPERTEAM_NO_HYPERLINKS"
#: Сколько символов описания показывать в отчёте (2-4 строки, без «простыней»).
REPORT_DESCRIPTION_LIMIT: Final[int] = 240
#: Ширина разделителей в консольном отчёте.
REPORT_RULE_WIDTH: Final[int] = 60

#: --- Excel-отчёт ---
#: Сколько символов описания показывать в колонке «What to build».
EXCEL_DESCRIPTION_LIMIT: Final[int] = 320
#: Порог «срочности» дедлайна (дней) для условного форматирования.
EXCEL_URGENT_DAYS: Final[int] = 3
EXCEL_SOON_DAYS: Final[int] = 7

# =====================================================================================
# Multi-source bounty search (новые источники: GitHub, BountyBureau, Opire, warpSpeed,
# OpenBounty). Существующая логика Superteam выше не изменяется.
# =====================================================================================

#: Статусы источников в отчёте: не делать вид, что источник работает, если он недоступен.
SOURCE_STATUS_OK: Final[str] = "OK"
SOURCE_STATUS_EMPTY: Final[str] = "EMPTY"
SOURCE_STATUS_PARTIAL: Final[str] = "PARTIAL"
SOURCE_STATUS_ERROR: Final[str] = "ERROR"
SOURCE_STATUS_NOT_FOUND: Final[str] = "NOT_FOUND"

#: Тип выплаты.
PAYMENT_TYPE_CRYPTO: Final[str] = "CRYPTO"
PAYMENT_TYPE_FIAT: Final[str] = "FIAT"
PAYMENT_TYPE_UNKNOWN: Final[str] = "UNKNOWN"

#: Финансовый риск, когда по тексту невозможно определить требования к деньгам
#: исполнителя: такая задача НЕ считается безопасной и не попадает в recommended.
FINANCIAL_RISK_UNKNOWN: Final[str] = "UNKNOWN"

#: Статусы верификации первоисточника (GitHub issue / страница bounty).
BOUNTY_VERIFIED_OPEN: Final[str] = "VERIFIED_OPEN"
BOUNTY_CLOSED: Final[str] = "CLOSED"
#: Статус bounty в терминах «можно ли ещё забрать выплату».
BOUNTY_AVAILABLE: Final[str] = "AVAILABLE"
BOUNTY_TAKEN: Final[str] = "TAKEN"
BOUNTY_PAID: Final[str] = "PAID"
BOUNTY_STATUS_UNKNOWN: Final[str] = "UNKNOWN"
BOUNTY_ASSIGNED: Final[str] = "ASSIGNED"
BOUNTY_PR_LINKED: Final[str] = "PR_LINKED"
BOUNTY_CLAIMED: Final[str] = "BOUNTY_CLAIMED"
BOUNTY_NOT_FOUND: Final[str] = "NOT_FOUND"
BOUNTY_RATE_LIMITED: Final[str] = "RATE_LIMITED"
BOUNTY_UNKNOWN: Final[str] = "UNKNOWN"

#: --- GitHub ---
GITHUB_TOKEN_ENV: Final[str] = "GITHUB_TOKEN"
GITHUB_API_BASE: Final[str] = "https://api.github.com"
GITHUB_USER_AGENT: Final[str] = "SuperteamAgent/1.0 (+bounty-search)"
GITHUB_MAX_RETRIES: Final[int] = 2
GITHUB_RETRY_BACKOFF_SECONDS: Final[float] = 2.0
#: Сколько найденных issue реально проверять по первоисточнику за один запуск
#: (ограничение важно для анонимного GitHub API без токена: 60 запросов/час).
GITHUB_MAX_VERIFICATIONS: Final[int] = 40
#: Поисковые запросы bounty-issues. Не ограничиваемся словом "bounty": учитываются
#: labels популярных платформ (Algora «💎 Bounty», BountyHub и т.п.).
GITHUB_BOUNTY_QUERIES: Final[tuple[str, ...]] = (
    "label:bounty state:open type:issue",
    "label:\"\U0001F48E Bounty\" state:open type:issue",
    "label:\"bounty \U0001F3C6\" state:open type:issue",
    "bounty in:title state:open type:issue",
    "\"bounty\" \"USDC\" in:title state:open type:issue",
)

#: --- BountyBureau (certification bureau поверх GitHub) ---
BOUNTYBUREAU_API_URL: Final[str] = "https://bountybureau.com/api/bounties"
#: --- Opire ---
OPIRE_API_URL: Final[str] = "https://api.opire.dev/rewards"
OPIRE_PAGE_SIZE: Final[int] = 30
OPIRE_MAX_PAGES: Final[int] = 3
#: --- warpSpeed / OpenBounty: кандидаты хостов, которые проверяются вживую ---
WARPSPEED_CANDIDATE_URLS: Final[tuple[str, ...]] = (
    "https://warpspeed.xyz/",
    "https://warpspeed.dev/",
    "https://www.warpspeed.so/",
)
OPENBOUNTY_CANDIDATE_URLS: Final[tuple[str, ...]] = (
    "https://openbounty.xyz/",
    "https://openbounty.com/",
    "https://openbounties.com/",
    "https://openbounty.dev/",
)

#: Файл сводного отчёта по всем источникам.
MULTI_SOURCE_RESULTS_FILE: Final[Path] = PROJECT_ROOT / "bounty_results.json"
#: Сколько записей брать из каждого источника до верификации.
DEFAULT_PER_SOURCE_LIMIT: Final[int] = 25
#: Минимальная награда не ограничивается сверху, но 0/неизвестная награда не принимается.
MIN_REWARD_USD: Final[float] = 1.0
#: Задача не считается актуальной, если в тексте есть дедлайн и он уже прошёл.
STALE_REPO_DAYS: Final[int] = 365 * 3
#: Строгость политики (по требованию задания): неизвестное НЕ считается подходящим
#: автоматически. Флаги позволяют ослабить правило одной строкой, если нужно.
ALLOW_UNKNOWN_REGION_IN_TOP: Final[bool] = False
ALLOW_UNKNOWN_FINANCIAL_RISK_IN_TOP: Final[bool] = False
ALLOW_MEDIUM_FINANCIAL_RISK_IN_TOP: Final[bool] = False
