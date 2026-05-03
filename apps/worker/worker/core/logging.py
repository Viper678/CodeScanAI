"""Structured logging setup for the worker.

Mirrors the api's ``logging.basicConfig``-style baseline. Tasks should use
``logging.getLogger(__name__)`` and never ``print``.
"""

from __future__ import annotations

import logging
import os

_DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging() -> None:
    """Configure root logging once. Idempotent."""

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format=_DEFAULT_FORMAT)


configure_logging()
