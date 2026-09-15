"""Единая модель оплачиваемой задачи (bounty) и разбор награды/валюты.

Один и тот же формат используют все источники (Superteam, GitHub, BountyBureau,
Opire, warpSpeed, OpenBounty). Значения никогда не выдумываются: если данных
нет — поле остаётся ``""``/``None``/``UNKNOWN``.

Поля контракта (см. :data:`CANDIDATE_FIELDS`): ``source``, ``title``, ``url``,
``status``, ``bounty_status``, ``reward_amount``, ``reward_currency``,
``payment_method``, ``payment_type``, ``financial_risk``, ``region``,
``difficulty``, ``estimated_time``, ``tech_stack``, ``beginner_friendly``,
``agent_compatible``, ``exclusion_reason``, ``verified_at``.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit

from ..config import (
    BOUNTY_AVAILABLE,
    BOUNTY_CLAIMED,
    BOUNTY_PAID,
    BOUNTY_STATUS_UNKNOWN,
    BOUNTY_TAKEN,
    FINANCIAL_RISK_UNKNOWN,
    PAYMENT_TYPE_CRYPTO,
    PAYMENT_TYPE_FIAT,
    PAYMENT_TYPE_UNKNOWN,
)
from ..scoring import FIAT_CURRENCIES, KNOWN_CRYPTO_CURRENCIES

#: Поля задачи, обязательные в отчёте (по требованию задания).
CANDIDATE_FIELDS: Final[tuple[str, ...]] = (
    "source",
    "title",
    "url",
    "status",
    "bounty_status",
    "reward_amount",
    "reward_currency",
    "payment_method",
    "payment_type",
    "financial_risk",
    "region",
    "difficulty",
    "estimated_time",
    "tech_stack",
    "beginner_friendly",
    "agent_compatible",
    "exclusion_reason",
    "verified_at",
)

#: Дополнительные (диагностические) поля — нужны для аудита и дедупликации.
EXTRA_FIELDS: Final[tuple[str, ...]] = (
    "source_id",
    "primary_source",
    "sources",
    "description",
    "repo",
    "language",
    "labels",
    "requirements_text",
    "eligibility_text",
    "agent_access",
    "region_status_override",
    "assignee",
    "deadline",
    "dashboard_url",
    "raw_status",
    "verified_status",
    "evidence",
    "freshness",
    "tech_priority",
    "rank_score",
    "exclusion_reasons",
    "exclusion_tag",
    "financial_risk_reasons",
    "region_reasons",
    "notes",
)

#: Статус задачи.
STATUS_OPEN: Final[str] = "OPEN"
STATUS_CLOSED: Final[str] = "CLOSED"
STATUS_UNKNOWN: Final[str] = "UNKNOWN"

#: Регион (канонические значения).
REGION_GLOBAL: Final[str] = "Global"
REGION_RUSSIA_ALLOWED: Final[str] = "Russia allowed"
REGION_RUSSIA_EXCLUDED: Final[str] = "Russia excluded"
REGION_RESTRICTED: Final[str] = "Restricted"
REGION_UNKNOWN: Final[str] = "UNKNOWN"

#: Статус bounty в терминах «можно ли ещё забрать выплату» (см. config).

#: Порядок приоритета источников при дедупликации (меньше — авторитетнее).
SOURCE_PRIORITY: Final[tuple[str, ...]] = (
    "superteam",
    "bountybureau",
    "opire",
    "github",
    "warpspeed",
    "openbounty",
)

_MONEY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?P<prefix>\$|usd\s*)\s*(?P<amount1>\d[\d\s,]*(?:\.\d+)?)"
    r"|(?P<amount2>\d[\d\s,]*(?:\.\d+)?)\s*(?P<currency>[A-Za-z]{2,8}|\$)",
)
_HOURS_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?P<low>\d{1,3})\s*(?:-|\u2013|to)\s*(?P<high>\d{1,3})\s*(?P<unit>hours?|hrs?|h)\b"
    r"|\b(?P<single>\d{1,3})\s*(?P<unit2>hours?|hrs?|h)\b"
    r"|\b(?P<days1>\d{1,3})\s*(?:-|\u2013|to)\s*(?P<days2>\d{1,3})\s*(?P<dayunit>days?)\b",
    re.I,
)

#: Псевдонимы валют → канонический тикер.
CURRENCY_ALIASES: Final[dict[str, str]] = {
    "USD": "USD",
    "USDC": "USDC",
    "USDT": "USDT",
    "SOL": "SOL",
    "JUPUSD": "jupUSD",
    "USDG": "USDG",
    "ETH": "ETH",
    "BTC": "BTC",
    "$": "USD",
    "EUR": "EUR",
    "GBP": "GBP",
}

#: Все известные коды валют (крипто + фиат) в верхнем регистре — единый источник
#: истины для разбора сумм и определения типа выплаты.
_KNOWN_CURRENCY_CODES: Final[frozenset[str]] = frozenset(
    {code.upper() for code in KNOWN_CRYPTO_CURRENCIES}
    | {code.upper() for code in FIAT_CURRENCIES}
    | set(CURRENCY_ALIASES)
)

#: Слова, которые стоят рядом с числом, но НЕ являются валютой. Без этого списка
#: фразы вида «5 MINUTES» или «10 ISSUES» давали бы ложную награду.
NON_CURRENCY_WORDS: Final[frozenset[str]] = frozenset(
    {
        "MINUTE",
        "MINUTES",
        "MIN",
        "MINS",
        "HOUR",
        "HOURS",
        "HR",
        "HRS",
        "SECOND",
        "SECONDS",
        "SEC",
        "DAY",
        "DAYS",
        "WEEK",
        "WEEKS",
        "MONTH",
        "MONTHS",
        "YEAR",
        "YEARS",
        "ISSUE",
        "ISSUES",
        "PR",
        "PRS",
        "STAR",
        "STARS",
        "FORK",
        "FORKS",
        "COMMIT",
        "COMMITS",
        "LINE",
        "LINES",
        "FILE",
        "FILES",
        "TEST",
        "TESTS",
        "BUG",
        "BUGS",
        "TASK",
        "TASKS",
        "STEP",
        "STEPS",
        "POINTS",
        "XP",
        "KB",
        "MB",
        "GB",
        "TB",
        "MS",
        "CPU",
        "RAM",
        "API",
        "UI",
        "UX",
        "ID",
    }
)


def utc_now() -> datetime:
    """Текущий момент в UTC (единая точка для ``verified_at``)."""
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """Текущий момент в UTC в формате ``YYYY-MM-DDTHH:MM:SSZ``."""
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def payment_type_for(currency: str) -> str:
    """Тип выплаты по валюте: ``CRYPTO`` / ``FIAT`` / ``UNKNOWN``.

    Крипто-валюты определяются по тому же списку, что и скоринг Superteam,
    поэтому классификация согласована с существующей логикой.
    """
    token = (currency or "").strip().upper()
    if not token:
        return PAYMENT_TYPE_UNKNOWN
    if token in {code.upper() for code in KNOWN_CRYPTO_CURRENCIES}:
        return PAYMENT_TYPE_CRYPTO
    if token in {code.upper() for code in FIAT_CURRENCIES} or token in ("US$", "$"):
        return PAYMENT_TYPE_FIAT
    return PAYMENT_TYPE_UNKNOWN


def is_known_currency(code: str) -> bool:
    """Проверить, что код валюты известен проекту (USDC/USDT/SOL/USD/EUR…)."""
    return (code or "").strip().upper() in _KNOWN_CURRENCY_CODES


def normalize_currency(raw: str) -> str:
    """Привести обозначение валюты к каноническому виду (``$`` → ``USD``)."""
    token = (raw or "").strip().strip(".,;:")
    if not token:
        return ""
    alias = CURRENCY_ALIASES.get(token.upper())
    if alias:
        return alias
    return token


def parse_money(text: str) -> tuple[float | None, str]:
    """Найти в тексте сумму и валюту награды.

    Поддерживаются формы ``$25``, ``USD 25``, ``25 USDC``, ``500 USD``,
    ``1 000 USDC``, ``$10,000``. Если валюта не указана, ``reward_currency``
    остаётся пустой — данные не выдумываются.

    :returns: пара ``(amount, currency)``; ``(None, "")`` если суммы нет.
    """
    if not text:
        return None, ""
    for match in _MONEY_PATTERN.finditer(text):
        raw_amount = match.group("amount1") or match.group("amount2") or ""
        raw_currency = match.group("currency") or ""
        cleaned = raw_amount.replace(",", "").replace(" ", "")
        if not cleaned:
            continue
        try:
            amount = float(cleaned)
        except ValueError:
            continue
        if amount <= 0:
            # «$0» — это отсутствие награды, а не награда нулевого размера.
            continue
        currency = normalize_currency(raw_currency)
        if match.group("prefix"):
            return amount, currency or "USD"
        # Валюта без явного символа принимается только если это известный код
        # (USDC/EUR/…) или она записана заглавными буквами — иначе «11 support»
        # ошибочно превратилось бы в награду 11 SUPPORT. Слова времени и единицы
        # измерения (MINUTES/ISSUES/KB) исключены списком NON_CURRENCY_WORDS.
        if currency and currency.upper() not in NON_CURRENCY_WORDS:
            if currency.upper() in _KNOWN_CURRENCY_CODES or raw_currency.isupper():
                return amount, currency
    return None, ""


def parse_estimated_time(text: str) -> str:
    """Оценить время выполнения, если оно явно указано в тексте.

    Ничего не выдумывается: если оценки нет, возвращается ``UNKNOWN``.
    """
    if not text:
        return "UNKNOWN"
    match = _HOURS_PATTERN.search(text)
    if not match:
        return "UNKNOWN"
    if match.group("low") and match.group("high"):
        return f"{match.group('low')}-{match.group('high')} hours"
    if match.group("single"):
        return f"{match.group('single')} hours"
    if match.group("days1") and match.group("days2"):
        return f"{match.group('days1')}-{match.group('days2')} days"
    return "UNKNOWN"


def canonical_url(url: str) -> str:
    """Канонический вид URL (без query/fragment и завершающего слеша)."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    if not parts.scheme:
        return url.strip().rstrip("/")
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def canonical_key(url: str) -> str:
    """Ключ дедупликации: одна и та же задача из разных источников → один ключ.

    Для ссылок GitHub ключ приводится к виду ``gh:owner/repo#123``, поэтому
    issue и соответствующий pull request считаются одной задачей.
    """
    if not url:
        return ""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().replace("www.", "")
    segments = [segment for segment in parts.path.split("/") if segment]
    if host == "github.com" and len(segments) >= 4 and segments[2] in ("issues", "pull", "pulls"):
        return f"gh:{segments[0].lower()}/{segments[1].lower()}#{segments[3]}"
    return canonical_url(url).lower()


def new_candidate(**values: Any) -> dict[str, Any]:
    """Создать запись задачи единого формата.

    Все поля контракта присутствуют всегда; значения по умолчанию —
    безопасные «неизвестно», а не выдуманные данные.
    """
    candidate: dict[str, Any] = {
        "source": "",
        "title": "",
        "url": "",
        "status": STATUS_UNKNOWN,
        "bounty_status": BOUNTY_STATUS_UNKNOWN,
        "reward_amount": None,
        "reward_currency": "",
        "payment_method": "",
        "payment_type": PAYMENT_TYPE_UNKNOWN,
        "financial_risk": FINANCIAL_RISK_UNKNOWN,
        "region": REGION_UNKNOWN,
        "difficulty": "UNKNOWN",
        "estimated_time": "UNKNOWN",
        "tech_stack": [],
        "beginner_friendly": False,
        "agent_compatible": False,
        "exclusion_reason": "",
        "verified_at": "",
        # --- диагностические поля (см. EXTRA_FIELDS) ---
        "source_id": "",
        "primary_source": "",
        "sources": [],
        "description": "",
        "repo": "",
        "language": "",
        "labels": [],
        "requirements_text": "",
        "eligibility_text": "",
        "agent_access": "UNKNOWN",
        "region_status_override": "",
        "assignee": "",
        "deadline": "",
        "dashboard_url": "",
        "raw_status": "",
        "verified_status": "",
        "evidence": [],
        "freshness": "",
        "tech_priority": 99,
        "rank_score": 0.0,
        "exclusion_reasons": [],
        "exclusion_tag": "",
        "financial_risk_reasons": [],
        "region_reasons": [],
        "notes": [],
    }
    unknown = set(values) - set(candidate)
    if unknown:
        raise KeyError(f"unknown candidate fields: {sorted(unknown)}")
    candidate.update(values)
    if candidate["url"] and not candidate["primary_source"]:
        candidate["primary_source"] = candidate["source"]
    if not candidate["sources"] and candidate["source"]:
        candidate["sources"] = [candidate["source"]]
    return candidate


def source_priority(source: str) -> int:
    """Числовой приоритет источника (меньше — авторитетнее)."""
    try:
        return SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(SOURCE_PRIORITY)
