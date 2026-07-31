"""Process-wide logging configuration for WankoroBot."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterable
from typing import TextIO

DEFAULT_LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
REDACTED = "[REDACTED]"
_HANDLER_MARKER = "_wankorobot_handler"


class _MaximumLevelFilter(logging.Filter):
    def __init__(self, maximum: int) -> None:
        super().__init__()
        self.maximum = maximum

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.maximum


class _SecretRedactingFormatter(logging.Formatter):
    def __init__(self, secrets: Iterable[str | None]) -> None:
        super().__init__(LOG_FORMAT, datefmt=DATE_FORMAT)
        self.secrets = tuple(secret for secret in secrets if secret)

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        for secret in self.secrets:
            message = message.replace(secret, REDACTED)
        return message


def parse_log_level(value: str | None) -> int:
    """Return a logging level, defaulting safely for invalid input."""

    if not value:
        return logging.INFO
    level = getattr(logging, value.strip().upper(), None)
    if not isinstance(level, int):
        return logging.INFO
    return level


def configure_logging(
    level_name: str | None,
    *,
    secrets: Iterable[str | None] = (),
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> None:
    """Configure root logging without duplicating managed handlers."""

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            root.removeHandler(handler)
            handler.close()

    level = parse_log_level(level_name)
    formatter = _SecretRedactingFormatter(secrets)

    stdout_handler = logging.StreamHandler(stdout or sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.addFilter(_MaximumLevelFilter(logging.INFO))
    stdout_handler.setFormatter(formatter)
    setattr(stdout_handler, _HANDLER_MARKER, True)

    stderr_handler = logging.StreamHandler(stderr or sys.stderr)
    stderr_handler.setLevel(max(level, logging.WARNING))
    stderr_handler.setFormatter(formatter)
    setattr(stderr_handler, _HANDLER_MARKER, True)

    root.setLevel(level)
    root.addHandler(stdout_handler)
    root.addHandler(stderr_handler)
