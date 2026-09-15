"""Адаптер OpenBounty: проверка реального наличия открытых bounty.

Поведение строго по заданию: если открытых bounty нет, возвращается
``source_status = EMPTY`` (или ``NOT_FOUND``, если платформа по проверенным
адресам не существует) — фиктивные результаты не создаются.

Проверка выполняется вживую, поэтому статус отражает текущее состояние, а не
исторические списки.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import OPENBOUNTY_CANDIDATE_URLS, SOURCE_STATUS_EMPTY, SOURCE_STATUS_NOT_FOUND
from ..core.models import utc_now_iso
from .base import SourceResult, probe_hosts

#: Имя источника в отчёте.
SOURCE_NAME: str = "openbounty"


async def collect(
    client: httpx.AsyncClient, *, per_source_limit: int = 25, **_: Any
) -> SourceResult:
    """Проверить OpenBounty вживую и вернуть честный статус источника."""
    probe = await probe_hosts(client, OPENBOUNTY_CANDIDATE_URLS, platform="OpenBounty")
    diagnostics: dict[str, Any] = {
        "probes": probe["probes"],
        "real_platform": probe["real_platform"],
        "discovered_total": 0,
    }
    if not probe["real_platform"]:
        return SourceResult(
            name=SOURCE_NAME,
            source_status=SOURCE_STATUS_NOT_FOUND,
            reason=(
                "OpenBounty как bounty-платформа не обнаружена: проверенные адреса отдают "
                "страницу-заглушку/парковку либо не разрешаются в DNS (детали в diagnostics.probes)"
            ),
            discovered=0,
            diagnostics=diagnostics,
            checked_at=utc_now_iso(),
        )
    return SourceResult(
        name=SOURCE_NAME,
        source_status=SOURCE_STATUS_EMPTY,
        reason="на хосте не найдено открытых bounty — пустой результат без фиктивных записей",
        discovered=0,
        diagnostics=diagnostics,
        checked_at=utc_now_iso(),
    )
