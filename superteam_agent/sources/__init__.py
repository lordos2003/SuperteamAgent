"""Реестр источников bounty и параллельный запуск с изоляцией ошибок.

Каждый источник — независимый модуль-адаптер с функцией ``collect``. Ошибка
одного источника не останавливает остальные: исключение превращается в
``SourceResult`` со статусом ``ERROR`` и причиной (требование задания).

Новый источник добавляется двумя шагами: модуль в этом пакете + запись в
:data:`SOURCE_REGISTRY` и :data:`DEFAULT_SOURCE_ORDER`.
"""
from __future__ import annotations

import asyncio
from typing import Any, Final, Sequence

import httpx

from ..config import SOURCE_STATUS_ERROR
from ..core.models import utc_now_iso
from ..secrets import redact
from . import bountybureau, github, openbounty, opire, superteam, warpspeed
from .base import SourceResult

#: Доступные источники: имя → модуль-адаптер.
SOURCE_REGISTRY: Final[dict[str, Any]] = {
    "superteam": superteam,
    "github": github,
    "bountybureau": bountybureau,
    "opire": opire,
    "warpspeed": warpspeed,
    "openbounty": openbounty,
}

#: Порядок источников по умолчанию (приоритет: crypto/on-chain → GitHub → агрегаторы).
DEFAULT_SOURCE_ORDER: Final[tuple[str, ...]] = (
    "superteam",
    "github",
    "bountybureau",
    "opire",
    "warpspeed",
    "openbounty",
)


def available_sources() -> list[str]:
    """Список имён источников для CLI и отчёта."""
    return list(DEFAULT_SOURCE_ORDER)


def resolve_sources(names: Sequence[str] | str | None) -> list[str]:
    """Проверить и нормализовать список источников из CLI.

    Принимает и готовый список, и строку ``"github,opire"`` (как её передаёт
    ``--sources``), поэтому символьная итерация по строке исключена.

    :raises ValueError: если указан неизвестный источник.
    """
    if not names:
        return list(DEFAULT_SOURCE_ORDER)
    if isinstance(names, str):
        candidates: Sequence[str] = names.replace(";", ",").split(",")
    else:
        candidates = names
    resolved: list[str] = []
    for name in candidates:
        clean = str(name or "").strip().lower()
        if not clean:
            continue
        if clean not in SOURCE_REGISTRY:
            raise ValueError(
                f"unknown source: {name!r} (available: {', '.join(available_sources())})"
            )
        if clean not in resolved:
            resolved.append(clean)
    return resolved or list(DEFAULT_SOURCE_ORDER)


async def collect_source(
    name: str, client: httpx.AsyncClient, *, per_source_limit: int = 25
) -> SourceResult:
    """Запустить один источник; любая ошибка превращается в статус ``ERROR``."""
    module = SOURCE_REGISTRY[name]
    try:
        result = await module.collect(client, per_source_limit=per_source_limit)
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 — источник не должен ронять весь поиск
        reason = f"{type(error).__name__}: {redact(str(error))}"
        return SourceResult(
            name=name,
            source_status=SOURCE_STATUS_ERROR,
            reason=reason,
            errors=[reason],
            checked_at=utc_now_iso(),
        )
    return result


async def run_all_sources(
    client: httpx.AsyncClient,
    *,
    sources: Sequence[str] | None = None,
    per_source_limit: int = 25,
) -> list[SourceResult]:
    """Запустить выбранные источники параллельно и вернуть результаты в порядке реестра."""
    names = resolve_sources(sources)
    results = await asyncio.gather(
        *(collect_source(name, client, per_source_limit=per_source_limit) for name in names)
    )
    return list(results)
