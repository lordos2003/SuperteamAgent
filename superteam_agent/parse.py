"""Разбор ответа Agent API: нечувствительный к схеме поиск полей и формatters.

Точная схема Agent API не публикуется, поэтому используется поиск по
нескольким вероятным ключам (регистр не важен). Секреты (API key,
claimCode, Authorization) в вывод никогда не попадают.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Final, Mapping, Sequence

from .config import PLACEHOLDER, REDACTED
from .secrets import safe, to_safe_json

#: Возможные имена полей: точная схема Agent API не публикуется, поэтому
#: используется поиск по нескольким вероятным ключам (регистр не важен).
TITLE_KEYS: Final[tuple[str, ...]] = ("title", "name", "heading")
SLUG_KEYS: Final[tuple[str, ...]] = ("slug", "id", "_id", "uuid")
TYPE_KEYS: Final[tuple[str, ...]] = ("type", "listingType", "kind", "category", "label")
STATUS_KEYS: Final[tuple[str, ...]] = ("status", "state", "listingStatus", "isOpen")
DEADLINE_KEYS: Final[tuple[str, ...]] = (
    "deadline",
    "deadlineAt",
    "endsAt",
    "endDate",
    "expiryDate",
    "dueDate",
    "submissionDeadline",
)
REWARD_KEYS: Final[tuple[str, ...]] = (
    "rewards",
    "reward",
    "rewardAmount",
    "usdValue",
    "compensation",
    "prize",
    "bounty",
    "amount",
)
REWARD_TOKEN_KEYS: Final[tuple[str, ...]] = (
    "token",
    "rewardToken",
    "tokenSymbol",
    "currency",
    "symbol",
    "asset",
)
SKILL_KEYS: Final[tuple[str, ...]] = (
    "skills",
    "skillsRequired",
    "requiredSkills",
    "categories",
    "tags",
    "requirements",
)
LIST_CONTAINER_KEYS: Final[tuple[str, ...]] = (
    "data",
    "listings",
    "items",
    "results",
    "bounties",
    "projects",
    "live",
)
DETAIL_CONTAINER_KEYS: Final[tuple[str, ...]] = ("data", "listing", "result", "item")

#: Если ключ содержит одну из этих подстрок, значение никогда не печатается:
#: такие поля могут содержать claimCode, API key или другой секрет.
SENSITIVE_KEY_HINTS: Final[tuple[str, ...]] = (
    "claim",
    "secret",
    "key",
    "token",
    "auth",
    "credential",
    "password",
    "private",
    "signature",
)


def is_sensitive_key(key: Any) -> bool:
    """Проверить, похоже ли имя поля на секрет (claimCode, apiKey, token…)."""
    lowered = str(key).lower()
    return any(hint in lowered for hint in SENSITIVE_KEY_HINTS)


def lookup(mapping: Mapping[str, Any], names: Sequence[str]) -> Any:
    """Вернуть первое непустое значение по списку возможных ключей.

    Имена ключей сравниваются без учёта регистра.
    """
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value not in (None, "", [], {}):
            return value
    return None


def format_number(value: Any) -> str:
    """Отформатировать число: пробелы между разрядами, без лишних нулей."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return safe(value)
    if number.is_integer():
        return f"{int(number):,}".replace(",", " ")
    text = f"{number:,.8f}".rstrip("0").rstrip(".")
    return text.replace(",", " ")


def format_reward(value: Any) -> str:
    """Отформатировать награду любой формы (число, строка, объект, список)."""
    if isinstance(value, Mapping):
        amount = lookup(value, ("amount", "value", "quantity", "usdValue", "total"))
        token = lookup(value, ("token", "currency", "symbol", "unit", "asset"))
        if amount is not None:
            amount_text = format_number(amount)
            return f"{amount_text} {safe(token)}" if token else amount_text
        return to_safe_json(value, limit=120)
    if isinstance(value, (list, tuple)):
        parts = [text for text in (format_reward(item) for item in value) if text]
        return " / ".join(parts)
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return format_number(value)
    return safe(value)


def extract_reward(listing: Mapping[str, Any]) -> str:
    """Собрать читаемое описание награды из полей задания."""
    token = lookup(listing, REWARD_TOKEN_KEYS)
    for key in REWARD_KEYS:
        value = lookup(listing, (key,))
        if value is None:
            continue
        text = format_reward(value)
        if not text:
            continue
        if token and isinstance(value, (int, float, str)) and str(token).lower() not in text.lower():
            return f"{text} {safe(token)}"
        return text
    return PLACEHOLDER


def format_deadline(value: Any) -> str:
    """Отформатировать дедлайн (ISO-строка или unix timestamp в мс/сек)."""
    if value in (None, ""):
        return PLACEHOLDER

    moment: datetime | None = None
    if isinstance(value, bool):
        return safe(value)
    if isinstance(value, (int, float)):
        seconds = value / 1000.0 if value > 10_000_000_000 else float(value)
        try:
            moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return safe(value)
    elif isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return format_deadline(int(text))
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return safe(text)
    else:
        return safe(value)

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def format_status(value: Any) -> str:
    """Привести статус задания к читаемому виду."""
    if value in (None, ""):
        return PLACEHOLDER
    if isinstance(value, bool):
        return "OPEN" if value else "NOT OPEN"
    text = safe(value).strip()
    return text.upper() if text else PLACEHOLDER


def format_skills(value: Any) -> str:
    """Собрать список навыков/категорий в одну строку."""
    if value in (None, "", [], {}):
        return PLACEHOLDER
    items = value if isinstance(value, (list, tuple)) else [value]
    result: list[str] = []
    for item in items:
        if isinstance(item, Mapping):
            name = lookup(item, ("name", "skill", "label", "title", "value", "slug"))
            result.append(safe(name) if name is not None else to_safe_json(item, limit=80))
        elif item not in (None, ""):
            result.append(safe(item))
    return ", ".join(result) if result else PLACEHOLDER


def collect_agent_fields(
    node: Any,
    path: str = "",
    findings: list[str] | None = None,
    depth: int = 0,
) -> list[str]:
    """Найти в объекте задания все поля, относящиеся к agent eligibility.

    Точная схема API неизвестна, поэтому ищутся любые ключи, содержащие
    подстроку ``agent`` (например ``agentOnly``, ``agentEligible``,
    ``agentStatus``), и возвращается их путь вместе со значением.

    :param node: произвольный фрагмент JSON-ответа.
    :param path: префикс пути (для вложенных полей).
    :param findings: накопитель результатов вида ``путь=значение``.
    :param depth: текущая глубина обхода.
    :returns: список найденных строк ``путь=значение``.
    """
    if findings is None:
        findings = []
    if depth > 3 or len(findings) >= 6:
        return findings

    if isinstance(node, Mapping):
        for key, value in node.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if "agent" in key_text.lower():
                if is_sensitive_key(key_text):
                    findings.append(f"{child_path}={REDACTED}")
                elif isinstance(value, (str, int, float, bool)) or value is None:
                    findings.append(f"{child_path}={safe(value)}")
                else:
                    findings.append(f"{child_path}={to_safe_json(value, limit=80)}")
            else:
                collect_agent_fields(value, child_path, findings, depth + 1)
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node[:3]):
            collect_agent_fields(item, f"{path}[{index}]", findings, depth + 1)

    return findings


def extract_agent_eligibility(listing: Mapping[str, Any]) -> str:
    """Вернуть читаемую строку про agent eligibility одного задания."""
    findings = collect_agent_fields(listing)
    return "; ".join(findings) if findings else "not specified in API response"


def extract_listings(payload: Any, depth: int = 0) -> list[Mapping[str, Any]]:
    """Найти в ответе API список заданий, не привязываясь к обёртке.

    Поддерживаются ответы вида ``[...]``, ``{"data": [...]}``,
    ``{"listings": [...]}`` и вложенные комбинации.

    :param payload: распарсенный JSON ответа.
    :param depth: текущая глубина рекурсии (защита от слишком глубоких ответов).
    :returns: список заданий (объектов JSON).
    """
    if depth > 5:
        return []

    if isinstance(payload, Mapping):
        for key in LIST_CONTAINER_KEYS:
            value = payload.get(key)
            if isinstance(value, list) and value and all(isinstance(item, Mapping) for item in value):
                return list(value)
        for value in payload.values():
            found = extract_listings(value, depth + 1)
            if found:
                return found
    elif isinstance(payload, list):
        if payload and all(isinstance(item, Mapping) for item in payload):
            return list(payload)
        for item in payload:
            found = extract_listings(item, depth + 1)
            if found:
                return found

    return []


def unwrap_listing(payload: Any) -> Mapping[str, Any]:
    """Достать объект задания из возможной обёртки ``{"data": {...}}``."""
    if isinstance(payload, Mapping):
        for key in DETAIL_CONTAINER_KEYS:
            value = payload.get(key)
            if isinstance(value, Mapping) and lookup(value, SLUG_KEYS + TITLE_KEYS) is not None:
                return value
        return payload
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, Mapping):
                return item
    return {}


def normalize_listing(item: Mapping[str, Any], source: str, source_url: str = "") -> dict[str, Any]:
    """Привести запись источника (Agent API или сайт) к единому виду.

    :param item: элемент ответа Agent API или публичного фида сайта.
    :param source: ``"agent_api"`` или ``"website"``.
    :param source_url: URL, откуда получена запись.
    :returns: словарь с унифицированными полями (значения не выдумываются).
    """
    amount = lookup(item, ("rewardAmount", "usdValue", "amount", "maxRewardAsk"))
    token = lookup(item, REWARD_TOKEN_KEYS)
    if amount is not None and token:
        reward = f"{format_number(amount)} {safe(token)}"
    elif amount is not None:
        reward = format_number(amount)
    else:
        reward = ""

    status_value = lookup(item, ("status", "state"))
    if isinstance(status_value, bool):
        status_text = "OPEN" if status_value else "CLOSED"
    else:
        status_text = str(status_value).upper() if status_value not in (None, "") else ""

    return {
        "slug": str(lookup(item, SLUG_KEYS) or "").strip(),
        "title": safe(lookup(item, TITLE_KEYS) or ""),
        "type": safe(lookup(item, TYPE_KEYS) or ""),
        "reward": reward,
        "reward_amount": amount if isinstance(amount, (int, float)) else None,
        "token": safe(token) if token else "",
        "status": status_text,
        "deadline": safe(lookup(item, DEADLINE_KEYS) or ""),
        "agent_access": safe(lookup(item, ("agentAccess", "agent_access", "agentEligibility")) or ""),
        "region": safe(lookup(item, ("region", "regionName", "country")) or ""),
        "winners_flagged": bool(lookup(item, ("isWinnersAnnounced", "winnersAnnounced"))),
        "winners_announced_at": safe(lookup(item, ("winnersAnnouncedAt",)) or ""),
        "source": source,
        "source_url": source_url,
    }
