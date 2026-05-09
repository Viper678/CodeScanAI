"""Structured JSON logging + correlation IDs (T5.4).

Contract per ``docs/SECURITY.md`` §7:
- Logs are JSON, with ``request_id`` / ``user_id`` correlations.
- A scrub filter redacts Google-style API keys (``AIza…``) before emit, in
  case one ever leaks into a message or argument.

Implementation notes:
- We keep the existing ``logger.info("…", arg)`` call sites unchanged. A
  custom :class:`JsonFormatter` mounted on the root handler converts every
  ``LogRecord`` into a JSON line; correlation IDs are pulled from
  :class:`~contextvars.ContextVar`s so they propagate across ``await`` and
  ``asyncio.gather`` without explicit threading.
- Request middleware (:class:`RequestLoggingMiddleware`) generates / accepts
  a ``X-Request-ID`` per request, drives the contextvar, and emits one
  access-log line at the end of the request.
- Uvicorn's own access log is silenced (we'd double-log otherwise). Other
  noisy libraries (sqlalchemy.engine, asyncio) are pinned to WARNING.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Final

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

# ---- Correlation context vars ----------------------------------------------
# ``ContextVar`` propagates across ``await`` / ``asyncio.gather`` boundaries
# inside one request automatically (one task = one Context). Empty defaults
# are ``None`` — the formatter omits the field if unset rather than emitting
# ``"request_id": null``, which keeps log lines tight.

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)


# ---- JSON formatter --------------------------------------------------------

# Names attached to every ``LogRecord`` by stdlib ``logging``. We never want
# them on the wire — they're Python-specific noise.
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


def _install_correlation_record_factory() -> None:
    """Install a global ``LogRecord`` factory that snapshots correlation
    contextvars onto every record at creation time.

    Why not a logger / handler filter: filters mounted on the root logger
    only run for records originating *at* root (Python's ``Logger.handle``
    doesn't replay ancestor filters as a record propagates up). A
    record-factory fires for every ``LogRecord`` regardless of source
    logger, which is what we want — and crucially, the snapshot lands
    BEFORE pytest's ``caplog`` (or any batched aggregator) sees the record.
    """

    base_factory = logging.getLogRecordFactory()

    def correlation_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = base_factory(*args, **kwargs)
        request_id = request_id_var.get()
        if request_id is not None:
            record.request_id = request_id
        user_id = user_id_var.get()
        if user_id is not None:
            record.user_id = user_id
        return record

    logging.setLogRecordFactory(correlation_factory)


# Kept for backwards-compatible imports + as a defensive belt-and-suspenders
# at the handler level. The record factory is the primary mechanism.
class CorrelationFilter(logging.Filter):
    """Idempotent snapshot of contextvars onto a record (no-op if already set)."""

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = request_id_var.get()
        if request_id is not None and not hasattr(record, "request_id"):
            record.request_id = request_id
        user_id = user_id_var.get()
        if user_id is not None and not hasattr(record, "user_id"):
            record.user_id = user_id
        return True


class JsonFormatter(logging.Formatter):
    """Emit a single JSON object per log record.

    Required fields: ``timestamp``, ``level``, ``logger``, ``message``.
    Optional: ``request_id``, ``user_id`` (snapshotted onto the record by
    :class:`CorrelationFilter`); plus any ``extra={}`` kwargs the caller
    supplied (dropped if they collide with a built-in attr).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Forward record extras — both the contextvar snapshots set by
        # :class:`CorrelationFilter` and any ``extra={}`` kwargs supplied
        # by the caller. Anything that isn't a built-in attr is fair game.
        for key, value in record.__dict__.items():
            if key in _BUILTIN_RECORD_ATTRS or key in payload or key.startswith("_"):
                continue
            payload[key] = value

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


# ---- Scrub filter ----------------------------------------------------------

# Per ``docs/SECURITY.md`` §6: Google API keys look like ``AIza`` followed by
# 35 chars of [A-Za-z0-9_-]. Anything matching is redacted in-place before
# the formatter sees the record.
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
    """Redact Google API keys in record message, args, and extras.

    Mounted on the root logger so every record passes through, regardless of
    which sub-logger emitted it.
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


# ---- Request-id middleware -------------------------------------------------

# Accepted shape for an upstream-supplied ``X-Request-ID``: alphanumerics,
# dashes, and underscores up to 64 chars. Newlines / spaces / colons / etc
# are rejected to neutralize log injection (a malicious caller can't inject
# ``"} {"level":"CRITICAL"`` into a log line).
_REQUEST_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _coerce_request_id(raw: str | None) -> str:
    if raw is not None and _REQUEST_ID_PATTERN.match(raw):
        return raw
    return uuid.uuid4().hex


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Per-request: stamp request_id, time the call, log one access line.

    Logs at the end of every request — replaces uvicorn's default access log
    (which we silence in :func:`configure_logging`). The auth dep
    :func:`app.core.deps.get_current_user` sets ``user_id_var`` later in the
    request lifecycle; by the time we log here, it's populated for any auth-
    requiring route.
    """

    def __init__(self, app: ASGIApp, *, logger_name: str = "app.access") -> None:
        super().__init__(app)
        self._logger = logging.getLogger(logger_name)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _coerce_request_id(request.headers.get("x-request-id"))
        request_id_token = request_id_var.set(request_id)
        user_id_token = user_id_var.set(None)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            # Log the access line for the failed request, then re-raise so
            # FastAPI's exception handlers still run. Without this the only
            # log evidence of a 500 would be the traceback, with no request
            # context attached.
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            self._logger.exception(
                "request errored",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "latency_ms": elapsed_ms,
                },
            )
            request_id_var.reset(request_id_token)
            user_id_var.reset(user_id_token)
            raise
        else:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            extras: dict[str, Any] = {
                "method": request.method,
                "path": request.url.path,
                "status": status_code,
                "latency_ms": elapsed_ms,
            }
            # Pull user_id off ``request.state`` if the auth dep stamped it
            # there. We can't read ``user_id_var`` here — Starlette's
            # ``BaseHTTPMiddleware`` ran ``call_next`` in a child task, and
            # contextvar mutations inside the child don't propagate back to
            # this parent task. ``request.state`` is shared so we use that.
            user_id = getattr(request.state, "user_id", None)
            if isinstance(user_id, str):
                extras["user_id"] = user_id
            self._logger.info("request", extra=extras)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            # The contextvar reset must still happen so the next request
            # starts clean. ``suppress`` covers the rare case where the
            # error branch above already reset the token (LookupError /
            # ValueError on double-reset).
            with suppress(LookupError, ValueError):
                request_id_var.reset(request_id_token)
            with suppress(LookupError, ValueError):
                user_id_var.reset(user_id_token)


# ---- Configuration entry point --------------------------------------------


def _coerce_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    return logging.getLevelNamesMapping().get(level.strip().upper(), logging.INFO)


def configure_logging(*, level: str | int = "INFO") -> None:
    """Install the JSON handler + scrub filter on the root logger.

    Idempotent: clears any handlers added on previous calls so a re-init
    (e.g. via test fixtures or a hot-reload) doesn't stack lines.
    """

    root = logging.getLogger()
    root.setLevel(_coerce_level(level))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ApiKeyScrubFilter())
    handler.addFilter(CorrelationFilter())
    root.addHandler(handler)
    # Snapshot contextvars onto every LogRecord at creation time — this
    # fires before any handler (incl. pytest ``caplog``) sees the record.
    _install_correlation_record_factory()

    # Silence uvicorn's access log — our middleware emits a structured one
    # per request and we don't want duplicates. Uvicorn's error / startup
    # logs (logger ``uvicorn.error``) stay at the root level so startup
    # messages still surface.
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False

    # Quiet noisy libs unless the operator deliberately bumped LOG_LEVEL.
    if root.level > logging.DEBUG:
        for noisy in ("sqlalchemy.engine", "asyncio", "httpx", "httpcore"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
