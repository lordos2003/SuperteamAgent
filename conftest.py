"""Подготовка окружения тестов: корень проекта в sys.path.

Благодаря этому ``import superteam_agent`` работает в тестах без установки
пакета (pytest добавляет каталог этого файла в sys.path, здесь — на всякий
случай явно).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
