"""TTL-кэш проверки карточек: одна карточка не скачивается слишком часто.

Кэш лежит в JSON-файле рядом с ``.env``. TTL настраивается переменной окружения
``SUPERTEAM_VERIFICATION_CACHE_TTL`` (в секундах): значение по умолчанию —
:data:`~superteam_agent.config.VERIFICATION_CACHE_TTL_SECONDS`, ``0`` полностью
отключает кэш.

Важно: кэш не может «заморозить» статус навсегда — по истечении TTL карточка
скачивается и разбирается заново, а каждая запись хранит ``cached_at``. Любая
ошибка работы с файлом кэша не должна ломать проверку: она просто игнорируется.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Final, Mapping

from .config import (
    VERIFICATION_CACHE_FILE,
    VERIFICATION_CACHE_TTL_ENV,
    VERIFICATION_CACHE_TTL_SECONDS,
)

#: Записи кэша в памяти процесса (файл — только хранилище между запусками).
_MEMORY: dict[str, dict[str, Any]] = {}
_LOADED: bool = False


def cache_ttl_seconds() -> int:
    """TTL кэша в секундах (``0`` — кэш отключён); переопределяется через env."""
    raw = os.getenv(VERIFICATION_CACHE_TTL_ENV, "").strip()
    if not raw:
        return VERIFICATION_CACHE_TTL_SECONDS
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return VERIFICATION_CACHE_TTL_SECONDS


def _load() -> None:
    """Прочитать файл кэша один раз за процесс (ошибки игнорируются)."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    try:
        payload = json.loads(VERIFICATION_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(payload, Mapping):
        entries = payload.get("entries")
        if isinstance(entries, Mapping):
            for slug, entry in entries.items():
                if isinstance(entry, Mapping):
                    _MEMORY[str(slug)] = dict(entry)


def _flush() -> None:
    """Записать кэш на диск (ошибки записи не должны ломать проверку)."""
    payload = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ttl_seconds": cache_ttl_seconds(),
        "entries": _MEMORY,
    }
    try:
        VERIFICATION_CACHE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def cache_age_seconds(entry: Mapping[str, Any]) -> float | None:
    """Возраст записи кэша в секундах (``None``, если время не читается)."""
    raw = str(entry.get("cached_at") or "")
    if not raw:
        return None
    try:
        moment = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - moment).total_seconds()


def get_cached_card(slug: str) -> dict[str, Any] | None:
    """Вернуть свежую запись кэша для slug или ``None``.

    Запись считается свежей, если её возраст меньше TTL. Просроченные записи
    игнорируются (и не используются как «текущий» статус).
    """
    ttl = cache_ttl_seconds()
    if ttl <= 0 or not slug:
        return None
    _load()
    entry = _MEMORY.get(slug)
    if not entry:
        return None
    age = cache_age_seconds(entry)
    if age is None or age > ttl:
        return None
    card = entry.get("card")
    if not isinstance(card, Mapping):
        return None
    cached = dict(card)
    cached["from_cache"] = True
    cached["cache_age_seconds"] = round(age, 1)
    evidence = list(cached.get("evidence") or [])
    evidence.append(f"verification reused from cache (age={age:.0f}s, ttl={ttl}s)")
    cached["evidence"] = evidence
    return cached


def store_card(slug: str, card: Mapping[str, Any]) -> None:
    """Положить результат проверки в кэш (если кэш включён)."""
    if cache_ttl_seconds() <= 0 or not slug:
        return
    _load()
    stored = dict(card)
    stored.pop("from_cache", None)
    stored.pop("cache_age_seconds", None)
    _MEMORY[slug] = {
        "cached_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verification_status": str(card.get("verification_status") or ""),
        "card": stored,
    }
    _flush()


def clear_cache() -> None:
    """Полностью очистить кэш (файл и память) — используется в тестах и вручную."""
    global _LOADED
    _MEMORY.clear()
    _LOADED = True
    try:
        VERIFICATION_CACHE_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def cache_stats() -> dict[str, Any]:
    """Диагностика кэша для отчёта/логов."""
    _load()
    return {
        "file": str(VERIFICATION_CACHE_FILE),
        "ttl_seconds": cache_ttl_seconds(),
        "entries": len(_MEMORY),
    }


#: Имя файла кэша (для документации/отчётов).
CACHE_FILE_NAME: Final[str] = VERIFICATION_CACHE_FILE.name
