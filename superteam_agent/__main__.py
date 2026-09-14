"""Точка входа ``python -m superteam_agent``."""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        print("Остановлено пользователем (Ctrl+C).")
        sys.exit(130)
