"""Superteam Earn hybrid search.

Гибридный поиск актуальных открытых заданий Superteam Earn: Agent API
(обнаружение, включая скрытые ``AGENT_ONLY``) + публичный сайт (актуальная
лента) + проверка каждой карточки (главный источник истины) +
deterministic-скоринг без внешнего AI.

Запуск: ``python -m superteam_agent``.
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"
