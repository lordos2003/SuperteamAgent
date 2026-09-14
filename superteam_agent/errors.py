"""Класс ошибки обращения к Agent API."""
from __future__ import annotations


class SuperteamApiError(RuntimeError):
    """Ошибка обращения к Agent API.

    Сообщение об ошибке всегда безопасно: ключ и заголовок Authorization
    вырезаются через :func:`superteam_agent.secrets.redact`.

    :param status_code: HTTP-код ответа или ``None`` (сетевая ошибка/таймаут).
    :param message: безопасное сообщение об ошибке.
    """

    def __init__(self, status_code: int | None, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
