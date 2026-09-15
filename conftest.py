"""Подготовка окружения тестов: корень проекта в sys.path.

Благодаря этому ``import superteam_agent`` работает в тестах без установки
пакета (pytest добавляет каталог этого файла в sys.path, здесь — на всякий
случай явно). Дополнительно изолируется кэш проверки карточек: тесты не должны
делить один кэш (иначе один сценарий «протекает» в другой).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolate_verification_cache(monkeypatch, tmp_path):
    """Каждый тест получает пустой кэш проверки карточек и отключённый TTL.

    Тест, которому нужен работающий кэш, включает его сам:
    ``monkeypatch.setenv("SUPERTEAM_VERIFICATION_CACHE_TTL", "600")``.
    """
    from superteam_agent import cache as cache_module

    monkeypatch.setenv("SUPERTEAM_VERIFICATION_CACHE_TTL", "0")
    monkeypatch.setattr(cache_module, "VERIFICATION_CACHE_FILE", tmp_path / "verification_cache.json")
    cache_module.clear_cache()
    yield
    cache_module.clear_cache()
