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
from starlette.responses import JSONResponse, Response
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
        # Scrub the FORMATTED message — ``record.getMessage()`` interpolates
        # ``record.args`` after the scrub filter has already run, so an
        # exception object (or any non-string ``%s`` arg) whose ``__str__``
        # contains an API key would leak the key here even though the
        # filter "ran". Applying the regex to the final rendered string
        # is the only way to catch interpolation-time leaks.
        rendered_message = _API_KEY_PATTERN.sub(_REDACTED, record.getMessage())

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": rendered_message,
        }

        # Forward record extras — both the contextvar snapshots set by
        # :class:`CorrelationFilter` and any ``extra={}`` kwargs supplied
        # by the caller. Anything that isn't a built-in attr is fair game.
        for key, value in record.__dict__.items():
            if key in _BUILTIN_RECORD_ATTRS or key in payload or key.startswith("_"):
                continue
            payload[key] = value

        if record.exc_info:
            # ``formatException`` walks ``exc_info`` directly; the scrub
            # filter only mutates ``record.msg`` / ``record.args`` /
            # extras, so an API key embedded in the exception message or
            # a chained ``__cause__`` would otherwise survive into the
            # serialized traceback. Re-apply the scrub here.
            payload["exc"] = _API_KEY_PATTERN.sub(_REDACTED, self.formatException(record.exc_info))
        if record.stack_info:
            payload["stack"] = _API_KEY_PATTERN.sub(_REDACTED, self.formatStack(record.stack_info))

        # Final-line scrub. ``json.dumps(..., default=str)`` stringifies any
        # non-JSON-serializable extras (Exception instances, Pydantic
        # models, custom dataclasses) AFTER the scrub filter has already
        # run — and the filter only walks string-typed values, so a
        # non-string ``extra={"err": some_object}`` whose ``__str__``
        # contains the key would slip through. One regex pass over the
        # rendered line catches anything ``default=str`` produces.
        return _API_KEY_PATTERN.sub(_REDACTED, json.dumps(payload, default=str, ensure_ascii=False))


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
    # ``fullmatch`` (not ``match``) — Python's ``$`` anchor matches before a
    # *trailing* newline by default, so ``re.match(r"^…$", "abc\n")``
    # succeeds and the trailing ``\n`` would slip into the access log line
    # AND get echoed back as the ``X-Request-ID`` response header. The
    # existing parametrized test for `"has\nnewline"` covered mid-string
    # newlines but missed the trailing case.
    if raw is not None and _REQUEST_ID_PATTERN.fullmatch(raw):
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
        try:
            try:
                response = await call_next(request)
            except Exception:
                # Build the 500 response ourselves rather than re-raising —
                # if we let it bubble to Starlette's outer
                # ``ServerErrorMiddleware``, the 500 is constructed AFTER
                # this middleware has exited and the ``X-Request-ID`` header
                # never lands. The standard error envelope is documented in
                # ``docs/API.md`` §"Error response".
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                error_extras: dict[str, Any] = {
                    "method": request.method,
                    "path": request.url.path,
                    "status": 500,
                    "latency_ms": elapsed_ms,
                }
                # Mirror the success-path enrichment: the auth dep stamps
                # ``request.state.user_id`` BEFORE the route raises, so
                # 500s from authenticated requests should still carry the
                # user correlation. (``user_id_var`` is unset in this
                # parent task — see the success branch below for the same
                # rationale.)
                user_id = getattr(request.state, "user_id", None)
                if isinstance(user_id, str):
                    error_extras["user_id"] = user_id
                self._logger.exception("request errored", extra=error_extras)
                response = JSONResponse(
                    status_code=500,
                    content={
                        "error": {
                            "code": "internal_error",
                            "message": "Internal server error",
                            "details": [],
                        },
                    },
                )
            else:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                extras: dict[str, Any] = {
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "latency_ms": elapsed_ms,
                }
                # Pull user_id off ``request.state`` if the auth dep stamped
                # it there. We can't read ``user_id_var`` here — Starlette's
                # ``BaseHTTPMiddleware`` ran ``call_next`` in a child task,
                # and contextvar mutations inside the child don't propagate
                # back to this parent task. ``request.state`` is shared so
                # we use that.
                user_id = getattr(request.state, "user_id", None)
                if isinstance(user_id, str):
                    extras["user_id"] = user_id
                self._logger.info("request", extra=extras)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            # Reset both contextvars so the next request starts clean.
            # Single reset path now (no early reset in the error branch),
            # so the suppression is a defensive belt rather than a real
            # double-reset guard.
            with suppress(RuntimeError, LookupError, ValueError):
                request_id_var.reset(request_id_token)
            with suppress(RuntimeError, LookupError, ValueError):
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

    coerced = _coerce_level(level)
    root = logging.getLogger()
    root.setLevel(coerced)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    # Set the HANDLER level too, not just the root logger level. Otherwise
    # records propagated up from child loggers (uvicorn at INFO,
    # sqlalchemy.engine, asyncio, …) bypass the root level filter and
    # always reach this handler — Python checks ``record.levelno >=
    # hdlr.level`` per ``Logger.callHandlers``, NOT the parent logger's
    # level. Setting the handler level enforces the documented LOG_LEVEL
    # contract: an operator who exports ``LOG_LEVEL=error`` shouldn't see
    # INFO lines from child loggers slipping through.
    handler.setLevel(coerced)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ApiKeyScrubFilter())
    handler.addFilter(CorrelationFilter())
    root.addHandler(handler)
    # Snapshot contextvars onto every LogRecord at creation time — this
    # fires before any handler (incl. pytest ``caplog``) sees the record.
    _install_correlation_record_factory()

    # Silence uvicorn's access log — our middleware emits a structured
    # access line per request and we don't want duplicates.
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False
    # Route uvicorn's startup / error log records through our JSON handler.
    # Uvicorn configures the parent ``uvicorn`` logger with its own
    # ``DefaultFormatter`` handler and ``propagate=False`` BEFORE importing
    # ``app.main``; if we leave that wiring in place, ``uvicorn.error``
    # records (server boot, "Application startup complete", lifespan errors)
    # emit as plaintext while every other line in the api emits as JSON.
    # Strip uvicorn's own handlers and re-enable propagation so the records
    # reach the root JSON handler we just installed above.
    for uv_name in ("uvicorn", "uvicorn.error"):
        uv_logger = logging.getLogger(uv_name)
        uv_logger.handlers = []
        uv_logger.propagate = True

    # Quiet noisy libs unless the operator deliberately bumped LOG_LEVEL.
    if root.level > logging.DEBUG:
        for noisy in ("sqlalchemy.engine", "asyncio", "httpx", "httpcore"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
