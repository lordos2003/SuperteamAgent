"""Общая инфраструктура адаптеров источников bounty.

Каждый источник — независимый модуль с функцией ``collect(client, ...)``,
возвращающий :class:`SourceResult`. Требования проекта, которые обеспечивает
этот слой:

* ошибка одного источника НЕ останавливает остальные (оркестратор ловит
  исключения и ставит ``SOURCE_STATUS_ERROR`` с причиной);
* честные статусы ``OK`` / ``EMPTY`` / ``PARTIAL`` / ``ERROR`` / ``NOT_FOUND``;
* никаких выдуманных данных: нет результата — пустой список и причина;
* пароль/ключи не попадают в отчёты (все строки проходят через ``redact``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Final, Mapping

import httpx

from ..config import (
    PUBLIC_MAX_RETRIES,
    PUBLIC_RETRY_BACKOFF_SECONDS,
    PUBLIC_USER_AGENT,
    SOURCE_STATUS_ERROR,
    SOURCE_STATUS_NOT_FOUND,
    SOURCE_STATUS_OK,
)
from ..core.filters import evaluate
from ..core.models import CANDIDATE_FIELDS, EXTRA_FIELDS, utc_now_iso
from ..core.ranking import rank_score, ranking_factors
from ..httpx_layer import fetch_page
from ..secrets import redact

#: Поля, которые политика перезаписывает в записи задачи.
POLICY_FIELDS: Final[tuple[str, ...]] = (
    "status",
    "bounty_status",
    "financial_risk",
    "reward_amount",
    "reward_currency",
    "payment_type",
    "region",
    "difficulty",
    "estimated_time",
    "tech_stack",
    "tech_priority",
    "beginner_friendly",
    "agent_compatible",
    "exclusion_reason",
    "exclusion_reasons",
    "exclusion_tag",
    "verified_status",
    "verified_at",
    "financial_risk_reasons",
    "region_reasons",
    "notes",
)


@dataclass
class SourceResult:
    """Итог работы одного источника (данные для отчёта ``sources``)."""

    name: str
    source_status: str = SOURCE_STATUS_OK
    reason: str = ""
    discovered: int = 0
    verified_open: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Представление источника для JSON-отчёта (без секретов)."""
        return {
            "source": self.name,
            "source_status": self.source_status,
            "reason": self.reason,
            "discovered": self.discovered,
            "verified_open": self.verified_open,
            "kept": len(self.items),
            "errors": [redact(str(error)) for error in self.errors],
            "diagnostics": self.diagnostics,
            "checked_at": self.checked_at or utc_now_iso(),
        }


def finalize_candidate(candidate: Mapping[str, Any], verification: Mapping[str, Any]) -> dict[str, Any]:
    """Применить политику к проверенному кандидату и посчитать ранжирование.

    :param candidate: запись единого формата (см. :mod:`..core.models`).
    :param verification: результат проверки первоисточника.
    :returns: запись с полями политики, ``rank_score`` и факторами ранжирования.
    """
    policy = evaluate(candidate, verification)
    entry: dict[str, Any] = dict(candidate)
    for field_name in POLICY_FIELDS:
        if field_name in policy:
            entry[field_name] = policy[field_name]
    entry["exclusion_reason"] = (policy.get("exclusion_reasons") or [""])[0]
    entry["verification"] = dict(verification)
    entry["manual_check_reasons"] = policy.get("manual_check_reasons") or []
    entry["reward_reason"] = policy.get("reward_reason") or ""
    entry["verified_at"] = str(verification.get("verified_at") or utc_now_iso())
    if not entry.get("verified_status"):
        entry["verified_status"] = str(verification.get("verified_status") or "")
    entry["rank_score"] = rank_score(entry)
    entry["ranking_factors"] = ranking_factors(entry)
    for field_name in CANDIDATE_FIELDS + EXTRA_FIELDS:
        entry.setdefault(field_name, None if field_name == "reward_amount" else "")
    return entry


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    accept: str = "application/json",
    max_retries: int = PUBLIC_MAX_RETRIES,
    backoff: float = PUBLIC_RETRY_BACKOFF_SECONDS,
) -> dict[str, Any]:
    """Скачать JSON публичного API источника (с повторами).

    :returns: словарь ``{"url", "reachable", "http_status", "json", "error"}``.
        Исключения не выбрасываются: ошибка источника — это данные отчёта.
    """
    page = await fetch_page(
        client,
        url,
        accept=accept,
        user_agent=PUBLIC_USER_AGENT,
        max_retries=max_retries,
        backoff=backoff,
    )
    result: dict[str, Any] = {
        "url": url,
        "reachable": bool(page.get("reachable")),
        "http_status": page.get("http_status"),
        "json": None,
        "error": redact(str(page.get("error") or "")),
    }
    if not page.get("reachable"):
        return result
    try:
        result["json"] = json.loads(page.get("text") or "")
    except ValueError:
        result["error"] = "response is not valid JSON"
    return result


def error_result(name: str, reason: str, *, errors: list[str] | None = None) -> SourceResult:
    """Источник недоступен: честный ``ERROR``/``NOT_FOUND`` вместо выдуманных задач."""
    status = SOURCE_STATUS_NOT_FOUND if "not found" in reason.lower() else SOURCE_STATUS_ERROR
    return SourceResult(
        name=name,
        source_status=status,
        reason=redact(reason),
        errors=list(errors or [reason]),
        checked_at=utc_now_iso(),
    )


def add_source_exclusion(entry: dict[str, Any], reason: str, tag: str) -> dict[str, Any]:
    """Добавить причину исключения, известную источнику (не политике).

    Применяется, когда сам источник сообщает факт, влияющий на доступность задачи:
    например BountyBureau помечает запись как ``taken`` или ``tier=rejected``.
    """
    reasons = list(entry.get("exclusion_reasons") or [])
    if reason not in reasons:
        reasons.append(reason)
    entry["exclusion_reasons"] = reasons
    if not entry.get("exclusion_reason"):
        entry["exclusion_reason"] = reason
    if not entry.get("exclusion_tag"):
        entry["exclusion_tag"] = tag
    entry["agent_compatible"] = False
    return entry


#: Признаки страницы-заглушки: продажа домена, парковка, редирект на «lander».
PARKING_MARKERS: Final[tuple[str, ...]] = (
    "domain for sale",
    "premium domain",
    "buy now",
    "lease to own",
    "this domain is for sale",
    "hugedomains",
    "godaddy",
    "parked domain",
    "parking",
    "/lander",
    "tokyo",
)


async def probe_hosts(
    client: httpx.AsyncClient, urls: tuple[str, ...], *, platform: str
) -> dict[str, Any]:
    """Проверить хосты платформы вживую: доступность и признаки заглушки.

    Нужно, чтобы не выдавать несуществующую платформу за рабочий источник: если
    домен продаётся или отдаёт страницу-парковку, это фиксируется как факт.

    :returns: ``{"probes": [...], "real_platform": bool}``.
    """
    probes: list[dict[str, Any]] = []
    real_platform = False
    for url in urls:
        page = await fetch_page(
            client,
            url,
            accept="text/html,application/xhtml+xml",
            user_agent=PUBLIC_USER_AGENT,
            max_retries=1,
            backoff=1.0,
        )
        text = " ".join((page.get("text") or "").split())
        lowered = text.lower()
        markers = [marker for marker in PARKING_MARKERS if marker in lowered]
        parking = bool(markers) or (page.get("reachable") and len(text) < 200)
        probe = {
            "url": url,
            "http_status": page.get("http_status"),
            "reachable": bool(page.get("reachable")),
            "bytes": page.get("length"),
            "looks_like_parking_or_for_sale": parking,
            "markers": markers,
            "error": redact(str(page.get("error") or "")),
            "platform": platform,
        }
        probes.append(probe)
        if probe["reachable"] and not parking and len(text) >= 200:
            real_platform = True
    return {"probes": probes, "real_platform": real_platform}
