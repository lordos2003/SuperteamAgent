"""Командный интерфейс: разбор аргументов и точка входа.

Запуск: ``python superteam_agent.py`` (лончер) или ``python -m superteam_agent``.
Обычный запуск печатает человекочитаемый отчёт (Available / Excluded / Unknown /
Summary) и сохраняет его в ``superteam_report.md``; ``--json`` выводит
технический JSON, ``--report`` повторяет отчёт по последнему прогону без сети,
``--debug`` добавляет технические детали (evidence карточек, диагностика, кэш).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from .config import DEFAULT_DETAILS_LIMIT, DEFAULT_PER_SOURCE_LIMIT, DEFAULT_SHOW_LISTINGS
from .multi_source import run_multi_source_search
from .runner import run_hybrid_search, run_report_from_json
from .sources import available_sources


def configure_stdout() -> None:
    """Сделать вывод устойчивым на Windows.

    В интерактивной консоли Windows Unicode печатается корректно, поэтому
    кодировка не трогается. Если поток перенаправлен (pipe/файл), включается
    режим ``errors="replace"``, чтобы кириллица не приводила к коду ошибки.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        isatty = getattr(stream, "isatty", None)
        if callable(isatty) and isatty():
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            pass


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description=(
            "Superteam Earn hybrid search: Agent API + public website + "
            "public card verification."
        ),
    )
    parser.add_argument(
        "--show",
        type=int,
        default=DEFAULT_SHOW_LISTINGS,
        help=f"сколько заданий показать в списке (по умолчанию {DEFAULT_SHOW_LISTINGS})",
    )
    parser.add_argument(
        "--details",
        type=int,
        default=DEFAULT_DETAILS_LIMIT,
        help=f"для скольких первых заданий запросить детали (по умолчанию {DEFAULT_DETAILS_LIMIT})",
    )
    parser.add_argument(
        "--slug",
        default=None,
        help="запросить детали только для указанного slug",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="напечатать JSON ответа API (секреты вырезаны)",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="не проверять публичные карточки (только данные источников)",
    )
    parser.add_argument(
        "--verify-limit",
        type=int,
        default=0,
        help="сколько карточек проверять (0 = все, по умолчанию все)",
    )
    parser.add_argument(
        "--no-diagnostics",
        action="store_true",
        help="не проверять диагностические страницы /earn* (только публичный фид)",
    )
    parser.add_argument(
        "--all-sources",
        action="store_true",
        help=(
            "multi-source поиск оплачиваемых задач (superteam, github, bountybureau, "
            "opire, warpspeed, openbounty) вместо гибридного поиска Superteam"
        ),
    )
    parser.add_argument(
        "--sources",
        default=None,
        help=f"источники через запятую (по умолчанию все: {', '.join(available_sources())})",
    )
    parser.add_argument(
        "--per-source-limit",
        type=int,
        default=DEFAULT_PER_SOURCE_LIMIT,
        help=f"сколько записей брать из каждого источника (по умолчанию {DEFAULT_PER_SOURCE_LIMIT})",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help=(
            "показать человекочитаемый отчёт по последнему прогону из "
            "superteam_results.json (без обращения к сайту)"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="вывести технический JSON (тот же документ, что сохраняется в superteam_results.json)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "подробный технический вывод: evidence карточек, диагностика источников, "
            "статусы, статистика кэша (в обычном отчёте эти детали скрыты)"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Главная точка входа: гибридный поиск актуальных открытых заданий.

    Шаги: загрузить ``.env``, проверить API key, получить задания из Agent API
    (источник обнаружения, включая скрытые ``AGENT_ONLY``), получить актуальную
    ленту с публичного сайта, объединить по slug, проверить каждую карточку
    (:func:`superteam_agent.card.verify_listing_card`), отфильтровать по
    актуальности и финансовому риску, вывести результат и сохранить
    ``superteam_results.json``.

    :param argv: аргументы командной строки (по умолчанию — из ``sys.argv``).
    :returns: код выхода (``0`` — успех, ``1`` — ошибка ключа/Agent API).
    """
    configure_stdout()
    args = parse_args(argv)
    if args.report:
        return run_report_from_json(args)
    if args.all_sources:
        return asyncio.run(run_multi_source_search(args))
    return asyncio.run(run_hybrid_search(args))
