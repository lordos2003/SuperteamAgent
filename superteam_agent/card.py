"""Проверка актуальности задания по ПУБЛИЧНОЙ карточке Superteam Earn.

Agent API может отдавать устаревшие задания, поэтому статус из API
(OPEN + deadline) недостаточен: для каждого задания скачивается
публичная карточка ``{base}/earn/listing/{slug}`` и анализируется её
реальное содержимое (``__NEXT_DATA__``, JSON-LD, meta-теги, видимый текст).
Статус определяется совокупностью сигналов — см. decide_verification_status.

Что фактически отдаёт карточка (проверено на живом сайте):
  * __NEXT_DATA__ -> props.pageProps.listing  (полный объект задания:
    status, deadline, isWinnersAnnounced, winnersAnnouncedAt, region,
    agentAccess, rewardAmount, token, rewards, description, skills);
  * при объявленных winners в dehydratedState появляется query ["winners", id];
  * JSON-LD (schema.org/JobPosting): title, description, validThrough,
    baseSalary, jobLocation.address.addressCountry;
  * meta-теги (og:title, og:description, og:image);
  * несуществующий slug отдаёт HTTP 200 с listing = null (а не 404).

Важно: поле status у карточки остаётся "OPEN" даже у завершённых заданий,
поэтому статус определяется СОВОКУПНОСТЬЮ сигналов.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any, Final, Mapping, Sequence

import httpx

from .api import card_url
from .config import (
    CARD_DESCRIPTION_FULL_LIMIT,
    CARD_DESCRIPTION_LIMIT,
    CARD_MAX_RETRIES,
    CARD_REQUIREMENTS_LIMIT,
    CARD_RETRY_BACKOFF_SECONDS,
    CARD_USER_AGENT,
    CLOSED,
    COMPLETED,
    EXPIRED,
    NOT_FOUND,
    UNKNOWN,
    VERIFIED_OPEN,
    WINNERS_ANNOUNCED,
)
from .httpx_layer import fetch_page
from .parse import DEADLINE_KEYS, format_deadline, format_number, lookup
from .secrets import redact, safe

CARD_STATUS_CLOSED: Final[tuple[str, ...]] = (
    "closed",
    "cancelled",
    "canceled",
    "paused",
    "archived",
    "removed",
    "deleted",
    "hidden",
    "inactive",
)
CARD_STATUS_COMPLETED: Final[tuple[str, ...]] = (
    "completed",
    "complete",
    "finished",
    "finalized",
    "finalised",
    "done",
    "paid",
)
CARD_STATUS_REVIEW: Final[tuple[str, ...]] = (
    "review",
    "reviewing",
    "in review",
    "under review",
    "judging",
    "evaluating",
)
CARD_STATUS_OPEN: Final[tuple[str, ...]] = ("open", "live", "active", "published", "ongoing")

#: Сильные текстовые маркеры: применяются только как fallback, когда
#: структурных данных нет. Одиночные слова "Completed"/"Winners" в разметке
#: игнорируются, чтобы избежать ложных срабатываний.
WINNERS_TEXT_MARKERS: Final[tuple[str, ...]] = (
    "winners announced",
    "winners have been announced",
    "announced winners",
    "winners are announced",
)
CLOSED_TEXT_MARKERS: Final[tuple[str, ...]] = (
    "this listing is closed",
    "listing is closed",
    "submissions are closed",
    "submissions closed",
    "no longer accepting submissions",
)

NEXT_DATA_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>', re.S
)
JSON_LD_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S
)
META_NAME_FIRST_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'<meta[^>]+(?:property|name)="([^"]+)"[^>]*content="([^"]*)"', re.I
)
META_CONTENT_FIRST_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'<meta[^>]+content="([^"]*)"[^>]*(?:property|name)="([^"]+)"', re.I
)
SCRIPT_STYLE_PATTERN: Final[re.Pattern[str]] = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
TAG_PATTERN: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")


async def fetch_card_page(client: httpx.AsyncClient, slug: str) -> dict[str, Any]:
    """Скачать публичную карточку задания с повторами для временных ошибок.

    Повтор выполняется не более ``CARD_MAX_RETRIES`` раз при таймауте, сетевой
    ошибке, 429 и 5xx. Для 404 и других постоянных ошибок повторов нет.

    :param client: общий асинхронный HTTP-клиент.
    :param slug: slug задания.
    :returns: словарь ``{"url", "reachable", "http_status", "html", "error"}``.
        ``reachable=False`` означает, что страницу получить не удалось — такое
        задание нельзя считать закрытым (будет статус UNKNOWN).
    """
    url = card_url(slug)
    page = await fetch_page(
        client,
        url,
        user_agent=CARD_USER_AGENT,
        max_retries=CARD_MAX_RETRIES,
        backoff=CARD_RETRY_BACKOFF_SECONDS,
    )
    return {
        "url": url,
        "reachable": page["reachable"],
        "http_status": page["http_status"],
        "html": page["text"],
        "error": page["error"],
    }


def parse_next_data(html: str) -> Mapping[str, Any] | None:
    """Извлечь JSON из ``<script id="__NEXT_DATA__">`` (или None, если его нет)."""
    match = NEXT_DATA_PATTERN.search(html)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except ValueError:
        return None
    return payload if isinstance(payload, Mapping) else None


def parse_json_ld(html: str) -> list[Mapping[str, Any]]:
    """Извлечь все корректные JSON-LD блоки страницы."""
    blocks: list[Mapping[str, Any]] = []
    for raw in JSON_LD_PATTERN.findall(html):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, Mapping):
            blocks.append(data)
        elif isinstance(data, list):
            blocks.extend(item for item in data if isinstance(item, Mapping))
    return blocks


def parse_job_posting(html: str) -> Mapping[str, Any]:
    """Вернуть JSON-LD блок с ``@type == JobPosting`` (или пустой словарь)."""
    for block in parse_json_ld(html):
        if str(block.get("@type", "")).lower() == "jobposting":
            return block
    return {}


def parse_meta_tags(html: str) -> dict[str, str]:
    """Собрать meta-теги (property/name -> content) в любом порядке атрибутов."""
    metas: dict[str, str] = {}
    for key, value in META_NAME_FIRST_PATTERN.findall(html):
        metas.setdefault(key.lower(), unescape(value))
    for value, key in META_CONTENT_FIRST_PATTERN.findall(html):
        metas.setdefault(key.lower(), unescape(value))
    return metas


def html_to_text(html: str) -> str:
    """Преобразовать HTML в видимый текст (скрипты и стили удаляются)."""
    text = SCRIPT_STYLE_PATTERN.sub(" ", html)
    text = TAG_PATTERN.sub(" ", text)
    text = unescape(text)
    return " ".join(text.split())


def next_data_page_props(payload: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Достать ``props.pageProps`` из ``__NEXT_DATA__``."""
    if not isinstance(payload, Mapping):
        return {}
    props = payload.get("props")
    if not isinstance(props, Mapping):
        return {}
    page_props = props.get("pageProps")
    return page_props if isinstance(page_props, Mapping) else {}


def card_listing(payload: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Достать объект задания (``props.pageProps.listing``) из ``__NEXT_DATA__``."""
    listing = next_data_page_props(payload).get("listing")
    return listing if isinstance(listing, Mapping) else {}


def card_query_keys(payload: Mapping[str, Any] | None) -> list[str]:
    """Собрать ключи react-query из ``dehydratedState`` (например ``winners``)."""
    keys: list[str] = []
    queries = next_data_page_props(payload).get("dehydratedState")
    if not isinstance(queries, Mapping):
        return keys
    items = queries.get("queries")
    if not isinstance(items, list):
        return keys
    for query in items:
        if not isinstance(query, Mapping):
            continue
        key = query.get("queryKey")
        if isinstance(key, list):
            keys.extend(str(part) for part in key)
        elif key is not None:
            keys.append(str(key))
    return keys


def parse_utc(value: Any) -> datetime | None:
    """Разобрать дату (ISO-строка или unix ms/сек) в timezone-aware UTC."""
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000.0 if value > 10_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"none", "null"}:
            return None
        if text.isdigit():
            return parse_utc(int(text))
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return None


def short_date(value: Any) -> str:
    """Короткая дата (YYYY-MM-DD) для дат из API/карточки."""
    from .config import PLACEHOLDER

    moment = parse_utc(value)
    if moment is not None:
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%d")
    return safe(value).strip() if value not in (None, "") else PLACEHOLDER


def first_text_marker(text_lower: str, markers: Sequence[str]) -> str:
    """Вернуть первый найденный текстовый маркер (или пустую строку)."""
    for marker in markers:
        if marker in text_lower:
            return marker
    return ""


def extract_region_text(text: str) -> str:
    """Найти на карточке блок про региональные ограничения (если он есть)."""
    upper = text.upper()
    for anchor in ("REGIONAL LISTING", "ONLY OPEN FOR"):
        index = upper.find(anchor)
        if index != -1:
            return text[index : index + 180].strip()
    return ""


def card_reward(listing: Mapping[str, Any], job_posting: Mapping[str, Any]) -> str:
    """Награда по данным карточки: rewardAmount + token, иначе JSON-LD baseSalary."""
    amount = lookup(listing, ("rewardAmount", "usdValue", "amount"))
    token = lookup(listing, ("token", "currency"))
    if amount is not None:
        text = format_number(amount)
        return f"{text} {safe(token)}" if token else text
    salary = job_posting.get("baseSalary")
    if isinstance(salary, Mapping):
        currency = salary.get("currency")
        value = salary.get("value")
        if isinstance(value, Mapping):
            value = value.get("value")
        if value is not None:
            return f"{format_number(value)} {safe(currency)}" if currency else format_number(value)
    return ""


def card_rewards_breakdown(listing: Mapping[str, Any]) -> str:
    """Разбивка призовых мест (rewards) в читаемом виде, если она есть."""
    rewards = listing.get("rewards")
    if not isinstance(rewards, Mapping) or not rewards:
        return ""
    parts: list[str] = []
    for place, amount in list(rewards.items())[:12]:
        place_text = "bonus" if str(place) == "99" else f"#{place}"
        parts.append(f"{place_text}={format_number(amount)}")
    return ", ".join(parts)


def collect_card_signals(
    *,
    listing: Mapping[str, Any],
    job_posting: Mapping[str, Any],
    query_keys: Sequence[str],
    text: str,
    now: datetime,
) -> dict[str, Any]:
    """Собрать все признаки карточки, нужные для решения о статусе.

    Ни один признак не решает судьбу задания в одиночку — возвращается набор
    сигналов, по которому :func:`decide_verification_status` принимает решение.

    :param listing: ``__NEXT_DATA__`` -> ``props.pageProps.listing``.
    :param job_posting: JSON-LD блок ``JobPosting``.
    :param query_keys: ключи react-query из ``dehydratedState``.
    :param text: видимый текст страницы.
    :param now: текущее время UTC для сравнения с deadline.
    :returns: словарь сигналов.
    """
    status_value = str(lookup(listing, ("status", "state")) or "").strip().lower()
    text_lower = text.lower()
    keys_lower = [key.lower() for key in query_keys]

    deadline_raw = lookup(listing, DEADLINE_KEYS) or job_posting.get("validThrough")
    deadline_moment = parse_utc(deadline_raw)

    return {
        "now": now,
        "has_structured_listing": bool(listing),
        "status_value": status_value,
        "is_open_status": status_value in CARD_STATUS_OPEN,
        "is_closed_status": status_value in CARD_STATUS_CLOSED,
        "is_completed_status": status_value in CARD_STATUS_COMPLETED,
        "is_review_status": status_value in CARD_STATUS_REVIEW,
        "unpublished": listing.get("isPublished") is False,
        "winners_structured": listing.get("isWinnersAnnounced") is True,
        "winners_at": parse_utc(listing.get("winnersAnnouncedAt")),
        "winners_query": "winners" in keys_lower,
        "winners_text": first_text_marker(text_lower, WINNERS_TEXT_MARKERS),
        "closed_text": first_text_marker(text_lower, CLOSED_TEXT_MARKERS),
        "deadline_raw": deadline_raw,
        "deadline_moment": deadline_moment,
        "deadline_passed": bool(deadline_moment is not None and deadline_moment < now),
    }


def decide_verification_status(signals: Mapping[str, Any], evidence: list[str]) -> str:
    """Определить ``verification_status`` по совокупности сигналов карточки.

    Порядок проверок:
      1. winners в данных/query/тексте -> ``WINNERS_ANNOUNCED``;
      2. deadline в прошлом -> ``EXPIRED`` (даже если API говорит OPEN);
      3. явный closed/unpublished/текст про закрытие -> ``CLOSED``;
      4. статус completed/finished -> ``COMPLETED``;
      5. статус review/judging -> ``CLOSED``;
      6. статус open и deadline не прошёл -> ``VERIFIED_OPEN``;
      7. иначе -> ``UNKNOWN`` (данных недостаточно, значения не выдумываются).

    :param signals: результат :func:`collect_card_signals`.
    :param evidence: список строк-обоснований (пополняется внутри).
    :returns: одно из значений ``ALL_VERIFICATION_STATUSES``.
    """
    deadline_moment = signals["deadline_moment"]
    now = signals["now"]

    if signals["winners_structured"]:
        evidence.append("card isWinnersAnnounced=true")
        return WINNERS_ANNOUNCED
    if signals["winners_at"] is not None:
        evidence.append(f"card winnersAnnouncedAt={signals['winners_at'].isoformat()}")
        return WINNERS_ANNOUNCED
    if signals["winners_query"]:
        evidence.append("card data query ['winners', <id>] present")
        return WINNERS_ANNOUNCED
    if signals["winners_text"]:
        evidence.append(f"visible text marker: {signals['winners_text']!r}")
        return WINNERS_ANNOUNCED

    if deadline_moment is not None and deadline_moment < now:
        evidence.append(
            f"card deadline {safe(signals['deadline_raw'])} < now "
            f"{now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )
        return EXPIRED

    if signals["closed_text"]:
        evidence.append(f"visible text marker: {signals['closed_text']!r}")
        return CLOSED
    if signals["unpublished"]:
        evidence.append("card isPublished=false")
        return CLOSED
    if signals["is_closed_status"]:
        evidence.append(f"card status={signals['status_value']!r}")
        return CLOSED
    if signals["is_completed_status"]:
        evidence.append(f"card status={signals['status_value']!r}")
        return COMPLETED
    if signals["is_review_status"]:
        evidence.append(f"card status={signals['status_value']!r} (submissions closed, judging)")
        return CLOSED

    if signals["is_open_status"]:
        if deadline_moment is None:
            evidence.append("card status=open, deadline not found on card")
        else:
            evidence.append(
                f"card status=open and deadline {safe(signals['deadline_raw'])} > now"
            )
        return VERIFIED_OPEN

    if signals["has_structured_listing"]:
        evidence.append(f"card status={signals['status_value']!r} is not recognized")
    else:
        evidence.append("no structured listing data found on card")
    return UNKNOWN


def card_eligibility_text(listing: Mapping[str, Any]) -> str:
    """Собрать текст eligibility-вопросов карточки (это обязательные требования).

    :param listing: объект задания из ``__NEXT_DATA__``.
    :returns: строки вида ``question: ...`` через ``;`` (или пустая строка).
    """
    questions: list[str] = []
    eligibility = listing.get("eligibility")
    if isinstance(eligibility, (list, tuple)):
        for item in eligibility:
            if isinstance(item, Mapping):
                for key in ("question", "label", "title", "prompt"):
                    value = item.get(key)
                    if value not in (None, ""):
                        questions.append(f"question: {value}")
                        break
            elif item not in (None, ""):
                questions.append(str(item))
    elif isinstance(eligibility, str) and eligibility.strip():
        questions.append(eligibility.strip())
    return "; ".join(questions)


def card_reward_amount(listing: Mapping[str, Any], job_posting: Mapping[str, Any]) -> float | None:
    """Числовая сумма reward по данным карточки (или None, если её нет)."""
    value = lookup(listing, ("rewardAmount", "usdValue", "amount"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    salary = job_posting.get("baseSalary")
    if isinstance(salary, Mapping):
        raw = salary.get("value")
        if isinstance(raw, Mapping):
            raw = raw.get("value")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return float(raw)
    return None


def card_submission_count(payload: Mapping[str, Any] | None, text: str) -> int | None:
    """Извлечь количество submissions с карточки (react-query или видимый текст).

    Фактически карточка содержит query ``["submissionCount", <id>]`` со значением
    ``state.data`` (целое число), а в тексте есть метка вида ``30 SUBMISSIONS``.

    :param payload: разобранный ``__NEXT_DATA__``.
    :param text: видимый текст страницы.
    :returns: число submissions или ``None``, если данных нет (не выдумываем).
    """
    queries = next_data_page_props(payload).get("dehydratedState")
    if isinstance(queries, Mapping):
        items = queries.get("queries")
        if isinstance(items, list):
            for query in items:
                if not isinstance(query, Mapping):
                    continue
                key = query.get("queryKey")
                first = key[0] if isinstance(key, list) and key else key
                if str(first).lower() != "submissioncount":
                    continue
                state = query.get("state")
                data = state.get("data") if isinstance(state, Mapping) else None
                value = data.get("count") if isinstance(data, Mapping) else data
                try:
                    return int(value)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    return None

    match = re.search(r"(\d[\d,]*)\s*SUBMISSIONS\b", text, re.I)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


def _empty_card_result(slug: str) -> dict[str, Any]:
    """Пустая заготовка результата проверки карточки."""
    return {
        "slug": slug,
        "card_url": card_url(slug) if slug else "",
        "reachable": False,
        "http_status": None,
        "status": "",
        "deadline": "",
        "deadline_utc": "",
        "deadline_passed": False,
        "deadline_confirmed": False,
        "reward": "",
        "rewards": "",
        "token": "",
        "has_winners": False,
        "winner_info": "",
        "submissions": None,
        "reward_amount": None,
        "region": "",
        "region_text": "",
        "description": "",
        "description_full": "",
        "requirements_text": "",
        "eligibility_text": "",
        "title": "",
        "type": "",
        "agent_access": "",
        "verification_status": UNKNOWN,
        "evidence": [],
        "error": "",
    }


def build_unverified_card(slug: str, reason: str) -> dict[str, Any]:
    """Заготовка результата для задания, которое не проверялось по карточке."""
    result = _empty_card_result(safe(slug))
    result["evidence"] = [reason]
    result["error"] = reason
    return result


async def verify_listing_card(client: httpx.AsyncClient, slug: str) -> dict[str, Any]:
    """Проверить актуальность задания по публичной карточке Superteam Earn.

    Скачивает ``{base}/earn/listing/{slug}`` обычным HTTP GET (без Playwright)
    и разбирает фактические данные страницы: ``__NEXT_DATA__``
    (``props.pageProps.listing``), JSON-LD ``JobPosting``, meta-теги и видимый
    текст. Значения не придумываются: если поля нет в ответе сайта, оно пустое,
    а при недостатке данных статус остаётся ``UNKNOWN``.

    :param client: общий асинхронный HTTP-клиент.
    :param slug: slug задания.
    :returns: словарь с ключами ``slug``, ``card_url``, ``reachable``,
        ``status``, ``deadline``, ``reward``, ``has_winners``, ``winner_info``,
        ``region``, ``description``, ``verification_status`` и дополнительными
        ``http_status``, ``title``, ``type``, ``agent_access``, ``rewards``,
        ``deadline_utc``, ``deadline_passed``, ``deadline_confirmed``,
        ``region_text``, ``evidence``, ``error``.
    """
    clean_slug = (slug or "").strip()
    result = _empty_card_result(clean_slug)
    evidence: list[str] = result["evidence"]

    if not clean_slug:
        result["error"] = "empty slug"
        evidence.append("slug is empty")
        return result

    page = await fetch_card_page(client, clean_slug)
    result["reachable"] = bool(page["reachable"])
    result["http_status"] = page["http_status"]
    result["error"] = safe(page["error"])

    if not page["reachable"]:
        if page["http_status"] == 404:
            result["verification_status"] = NOT_FOUND
            evidence.append("card page HTTP 404 -> NOT_FOUND")
        else:
            # Сайт недоступен: задание НЕ считается закрытым.
            result["verification_status"] = UNKNOWN
            evidence.append(
                f"card not reachable ({result['error']}) -> UNKNOWN, listing is NOT treated as closed"
            )
        return result

    html_text = page["html"]
    next_data = parse_next_data(html_text)
    listing = card_listing(next_data)
    job_posting = parse_job_posting(html_text)
    metas = parse_meta_tags(html_text)
    visible_text = html_to_text(html_text)
    query_keys = card_query_keys(next_data)

    evidence.append(f"__NEXT_DATA__ present: {next_data is not None}")
    evidence.append(f"pageProps.listing present: {bool(listing)}")
    evidence.append(f"json-ld JobPosting present: {bool(job_posting)}")
    if query_keys:
        evidence.append(f"card data queries: {sorted(set(query_keys))}")

    if next_data is not None and not listing:
        # Страница отвечает 200, но объекта задания в данных нет:
        # так сайт отдаёт несуществующий slug (проверено вживую).
        result["verification_status"] = NOT_FOUND
        evidence.append("pageProps.listing is null -> NOT_FOUND")
        return result

    now = datetime.now(timezone.utc)
    signals = collect_card_signals(
        listing=listing, job_posting=job_posting, query_keys=query_keys, text=visible_text, now=now
    )

    result["status"] = safe(listing.get("status") or "")
    result["type"] = safe(listing.get("type") or "")
    result["agent_access"] = safe(listing.get("agentAccess") or "")
    result["title"] = safe(
        listing.get("title") or job_posting.get("title") or metas.get("og:title", "")
    )
    result["reward"] = card_reward(listing, job_posting)
    result["rewards"] = card_rewards_breakdown(listing)
    result["token"] = safe(lookup(listing, ("token", "currency")) or "")
    result["region"] = safe(listing.get("region") or "")
    if not result["region"]:
        location = job_posting.get("jobLocation")
        address = location.get("address") if isinstance(location, Mapping) else None
        if isinstance(address, Mapping):
            result["region"] = safe(address.get("addressCountry") or "")
    result["region_text"] = safe(extract_region_text(visible_text))

    deadline_raw = signals["deadline_raw"]
    if deadline_raw not in (None, ""):
        result["deadline"] = safe(deadline_raw)
        result["deadline_utc"] = format_deadline(deadline_raw)
    result["deadline_confirmed"] = signals["deadline_moment"] is not None
    result["deadline_passed"] = signals["deadline_passed"]

    description_source = str(
        listing.get("description") or job_posting.get("description") or metas.get("og:description", "")
    )
    description_text = (
        html_to_text(description_source) if "<" in description_source else description_source
    )
    description_text = redact(" ".join(description_text.split()))
    result["description"] = description_text[:CARD_DESCRIPTION_LIMIT]
    result["description_full"] = description_text[:CARD_DESCRIPTION_FULL_LIMIT]
    result["requirements_text"] = redact(
        " ".join(str(listing.get("requirements") or "").split())
    )[:CARD_REQUIREMENTS_LIMIT]
    result["eligibility_text"] = redact(card_eligibility_text(listing))[:CARD_REQUIREMENTS_LIMIT]

    winners_reasons: list[str] = []
    if signals["winners_structured"]:
        winners_reasons.append("isWinnersAnnounced=true")
    if signals["winners_at"] is not None:
        winners_reasons.append(f"winnersAnnouncedAt={signals['winners_at'].isoformat()}")
    if signals["winners_query"]:
        winners_reasons.append("winners query present in card data")
    if signals["winners_text"]:
        winners_reasons.append(f"visible text {signals['winners_text']!r}")
    result["has_winners"] = bool(winners_reasons)
    result["winner_info"] = (
        "; ".join(winners_reasons) if winners_reasons else "no winners announced on card"
    )
    result["submissions"] = card_submission_count(next_data, visible_text)
    result["reward_amount"] = card_reward_amount(listing, job_posting)

    result["verification_status"] = decide_verification_status(signals, evidence)
    return result


def result_label(verification_status: str) -> str:
    """Метка результата проверки: CANDIDATE / EXCLUDE / MANUAL_CHECK."""
    if verification_status == VERIFIED_OPEN:
        return "CANDIDATE"
    if verification_status == UNKNOWN:
        return "MANUAL_CHECK (card data unavailable, listing NOT treated as closed)"
    return "EXCLUDE"
