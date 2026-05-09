"""Structured JSON logging + correlation IDs for the worker (T5.4).

Mirrors ``apps/api/app/core/logging.py``. The two trees don't share code today,
so this is a deliberate copy — kept ~1:1 with the api version so an operator
sees the same log shape from both processes. If we ever extract a shared
``codescan_common`` package, this module collapses with the api one.

Worker-side correlation ids come from Celery signals (set on ``task_prerun``,
reset on ``task_postrun``) rather than HTTP middleware:

- ``task_id``  — Celery's UUID for the task instance.
- ``scan_id``  — args[0] when the task is ``run_scan``.
- ``upload_id`` — args[0] when the task is ``prepare_upload``.
- ``file_id``  — set by inner code (``run_scan._process_file``) when scanning
  a specific file; left ``None`` otherwise.
"""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Final

# ---- Correlation context vars ----------------------------------------------

task_id_var: ContextVar[str | None] = ContextVar("task_id", default=None)
scan_id_var: ContextVar[str | None] = ContextVar("scan_id", default=None)
upload_id_var: ContextVar[str | None] = ContextVar("upload_id", default=None)
file_id_var: ContextVar[str | None] = ContextVar("file_id", default=None)


# ---- JSON formatter --------------------------------------------------------

_BUILTIN_RECORD_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


_CORRELATION_VARS = (
    ("task_id", task_id_var),
    ("scan_id", scan_id_var),
    ("upload_id", upload_id_var),
    ("file_id", file_id_var),
)


def _install_correlation_record_factory() -> None:
    """Install a global ``LogRecord`` factory that snapshots correlation
    contextvars at record-creation time.

    See ``apps/api/app/core/logging.py`` for the rationale — same trick
    here: filters mounted on the root logger only run for records that
    originate at root, so we use the factory to fire for every record
    regardless of source logger.
    """

    base_factory = logging.getLogRecordFactory()

    def correlation_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = base_factory(*args, **kwargs)
        for attr, var in _CORRELATION_VARS:
            value = var.get()
            if value is not None:
                setattr(record, attr, value)
        return record

    logging.setLogRecordFactory(correlation_factory)


class CorrelationFilter(logging.Filter):
    """Idempotent snapshot of contextvars onto a record (no-op if already set).

    The record factory is the primary mechanism; this filter is a defensive
    belt-and-suspenders mounted on our handler so a missing factory call
    (e.g. tests that import ``CorrelationFilter`` standalone) still works.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        for attr, var in _CORRELATION_VARS:
            value = var.get()
            if value is not None and not hasattr(record, attr):
                setattr(record, attr, value)
        return True


class JsonFormatter(logging.Formatter):
    """Emit a single JSON object per log record.

    Required fields: ``timestamp``, ``level``, ``logger``, ``message``.
    Optional: ``task_id`` / ``scan_id`` / ``upload_id`` / ``file_id``
    (snapshotted by :class:`CorrelationFilter`), plus any ``extra={}``
    kwargs the call site supplied.
    """

    def format(self, record: logging.LogRecord) -> str:
        # Scrub the FORMATTED message — ``record.getMessage()`` interpolates
        # ``record.args`` after the scrub filter has already run, so an
        # exception object (or any non-string ``%s`` arg) whose ``__str__``
        # contains an API key would leak the key here even though the
        # filter "ran". Applying the regex to the final rendered string
        # is the only way to catch interpolation-time leaks. Same fix in
        # the api copy at ``apps/api/app/core/logging.py``.
        rendered_message = _API_KEY_PATTERN.sub(_REDACTED, record.getMessage())

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": rendered_message,
        }

        for key, value in record.__dict__.items():
            if key in _BUILTIN_RECORD_ATTRS or key in payload or key.startswith("_"):
                continue
            payload[key] = value

        if record.exc_info:
            # ``formatException`` walks ``exc_info`` directly; the scrub
            # filter only mutates ``record.msg`` / ``record.args`` /
            # extras. The worker holds ``GOOGLE_AI_API_KEY`` so a Gemma
            # SDK exception whose message includes the key (e.g. a
            # request-URL-with-querystring trace) would otherwise leak
            # the key into the serialized traceback. Re-apply the scrub
            # to ``formatException``'s output as a hard backstop.
            payload["exc"] = _API_KEY_PATTERN.sub(_REDACTED, self.formatException(record.exc_info))
        if record.stack_info:
            payload["stack"] = _API_KEY_PATTERN.sub(_REDACTED, self.formatStack(record.stack_info))

        return json.dumps(payload, default=str, ensure_ascii=False)


# ---- Scrub filter ----------------------------------------------------------

_API_KEY_PATTERN: Final = re.compile(r"AIza[A-Za-z0-9_-]{35}")
_REDACTED: Final = "AIza<redacted>"


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return _API_KEY_PATTERN.sub(_REDACTED, value)
    if isinstance(value, tuple):
        return tuple(_scrub(item) for item in value)
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    return value


class ApiKeyScrubFilter(logging.Filter):
    """Redact Google API keys (``AIza…``) anywhere in the record.

    Per ``docs/SECURITY.md`` §6 — the worker actually holds the key in env
    so this is the more important of the two services to scrub, even though
    we never deliberately log it.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _API_KEY_PATTERN.sub(_REDACTED, record.msg)
        if record.args:
            record.args = _scrub(record.args)
        for key, value in list(record.__dict__.items()):
            if key in _BUILTIN_RECORD_ATTRS or key.startswith("_"):
                continue
            record.__dict__[key] = _scrub(value)
        return True


# ---- Configuration entry point --------------------------------------------


def _coerce_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    return logging.getLevelNamesMapping().get(level.strip().upper(), logging.INFO)


def configure_logging(*, level: str | int = "INFO") -> None:
    """Install the JSON handler + scrub filter on the root logger.

    Idempotent: re-running clears existing handlers so a hot-reload doesn't
    stack lines.
    """

    coerced = _coerce_level(level)
    root = logging.getLogger()
    root.setLevel(coerced)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    # Set the HANDLER level too — see the api copy's rationale at
    # ``apps/api/app/core/logging.py``: records propagated up from child
    # loggers (celery.app.trace, kombu, sqlalchemy.engine, …) bypass the
    # root logger's level filter and reach this handler regardless if it
    # stays at NOTSET. Setting handler.level honors the LOG_LEVEL contract.
    handler.setLevel(coerced)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ApiKeyScrubFilter())
    handler.addFilter(CorrelationFilter())
    root.addHandler(handler)
    # Snapshot contextvars onto every LogRecord at creation time — fires
    # before any handler (incl. pytest ``caplog``) sees the record.
    _install_correlation_record_factory()

    if root.level > logging.DEBUG:
        for noisy in ("celery.app.trace", "kombu", "amqp", "sqlalchemy.engine", "asyncio"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
