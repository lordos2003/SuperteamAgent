"""Лончер: ``python superteam_agent.py`` == ``python -m superteam_agent``.

Историческое имя скрипта сохранено для удобства. Реализация живёт в пакете
``superteam_agent`` (этот файл — только точка входа и не содержит логики).
"""
from __future__ import annotations

import sys

from superteam_agent.cli import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        print("Остановлено пользователем (Ctrl+C).")
        sys.exit(130)