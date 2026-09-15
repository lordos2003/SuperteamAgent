"""Адаптер warpSpeed: честная проверка наличия платформы и открытых bounty.

Требование задания: не доверять старым markdown/README-спискам как доказательству
актуальности. Поэтому адаптер:

1. проверяет кандидатов-хостов warpSpeed ВЖИВУЮ — если хост отдаёт заглушку,
   парковку или страницу продажи домена, это фиксируется как факт в диагностике;
2. если платформа не обнаружена — возвращает ``NOT_FOUND`` с доказательствами,
   а НЕ выдуманные задачи;
3. если список задач был бы найден, каждая задача всё равно проверялась бы по
   первоисточнику (конкретная страница/GitHub issue) — как требует правило проекта.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import SOURCE_STATUS_EMPTY, SOURCE_STATUS_NOT_FOUND, WARPSPEED_CANDIDATE_URLS
from ..core.models import utc_now_iso
from .base import SourceResult, probe_hosts

#: Имя источника в отчёте.
SOURCE_NAME: str = "warpspeed"


async def collect(
    client: httpx.AsyncClient, *, per_source_limit: int = 25, **_: Any
) -> SourceResult:
    """Проверить warpSpeed вживую и вернуть честный статус источника."""
    probe = await probe_hosts(client, WARPSPEED_CANDIDATE_URLS, platform="warpSpeed Bounties")
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
                "warpSpeed как bounty-платформа не обнаружена: проверенные хосты отдают "
                "страницу-заглушку/парковку либо недоступны (детали в diagnostics.probes)"
            ),
            discovered=0,
            diagnostics=diagnostics,
            checked_at=utc_now_iso(),
        )
    return SourceResult(
        name=SOURCE_NAME,
        source_status=SOURCE_STATUS_EMPTY,
        reason=(
            "хост отвечает, но машиночитаемого списка открытых bounty не найдено; "
            "для проверки нужен конкретный URL задачи"
        ),
        discovered=0,
        diagnostics=diagnostics,
        checked_at=utc_now_iso(),
    )
