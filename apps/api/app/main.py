from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import redis.asyncio as redis_async
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.db import engine
from app.core.exceptions import AppError, RateLimited
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.routers.scans import router as scans_router
from app.routers.uploads import router as uploads_router

# Configure structured JSON logging at import time so any startup logs
# (database connectivity check in lifespan, uvicorn boot messages) emit in
# the right shape. ``configure_logging`` is idempotent.
configure_logging(level=settings.log_level)

logger = logging.getLogger(__name__)


_SENTRY_API_KEY_PATTERN = re.compile(r"AIza[A-Za-z0-9_-]{35}")
_SENTRY_REDACTED = "AIza<redacted>"


def _scrub_sentry_value(value: Any) -> Any:
    """Recursive scrub for Sentry event payloads.

    Sentry captures exceptions directly via ``event_from_exception`` —
    bypassing :class:`app.core.logging.ApiKeyScrubFilter`. The api
    doesn't hold ``GOOGLE_AI_API_KEY`` directly, but a worker-side error
    surfaced through the api (e.g. a ``QueueUnavailable`` whose chained
    cause carries the key) could still ship through this process's
    Sentry hook. Defense in depth: redact ``AIza…`` shapes here too,
    matching the worker's ``observability._sentry_before_send`` so the
    two surfaces stay consistent.
    """

    if isinstance(value, str):
        return _SENTRY_API_KEY_PATTERN.sub(_SENTRY_REDACTED, value)
    if isinstance(value, dict):
        return {k: _scrub_sentry_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_sentry_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_sentry_value(item) for item in value)
    return value


def _sentry_before_send(event: Any, _hint: dict[str, Any]) -> Any:
    """``sentry_sdk`` ``before_send`` hook — last-line scrub for API keys.

    Typed as ``Any`` to match ``sentry_sdk``'s typed ``Event`` TypedDict
    without importing it at module scope (the SDK is an optional dep).
    """

    return _scrub_sentry_value(event)


def _init_sentry_if_configured() -> None:
    """Initialize Sentry when ``SENTRY_DSN`` is set; no-op otherwise.

    Imports happen lazily so that an install without ``sentry-sdk`` (e.g. a
    minimal smoke build) doesn't crash on import. ``traces_sample_rate=0``
    means no perf data is shipped by default — operators tune it via
    ``SENTRY_TRACES_SAMPLE_RATE`` if they want tracing.
    """

    if settings.sentry_dsn is None:
        return
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        integrations=[FastApiIntegration(), StarletteIntegration()],
        traces_sample_rate=0.0,
        send_default_pii=False,
        # Last-line API-key scrub — see ``_sentry_before_send`` rationale.
        before_send=_sentry_before_send,
    )
    logger.info("sentry initialized for api")


HTTP_ERROR_CODES = {
    400: "validation_error",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
}


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
            },
        },
    )


async def app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    app_error = cast(AppError, exc)
    return _error_response(
        status_code=app_error.status_code,
        code=app_error.error_code,
        message=app_error.message,
    )


async def validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    validation_error = cast(RequestValidationError, exc)
    details = [
        {
            "loc": list(error["loc"]),
            "msg": str(error["msg"]),
        }
        for error in validation_error.errors()
    ]
    return _error_response(
        status_code=422,
        code="validation_error",
        message="Validation error",
        details=details,
    )


async def http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    http_error = cast(HTTPException, exc)
    message = http_error.detail if isinstance(http_error.detail, str) else "HTTP error"
    return _error_response(
        status_code=http_error.status_code,
        code=HTTP_ERROR_CODES.get(http_error.status_code, "internal_error"),
        message=message,
    )


async def rate_limited_handler(_: Request, exc: Exception) -> JSONResponse:
    """429 + standard error envelope + ``Retry-After`` header.

    Registered before ``app_error_handler`` so the more specific class wins
    dispatch — FastAPI walks the MRO and picks the closest match.
    """

    err = cast(RateLimited, exc)
    response = _error_response(
        status_code=err.status_code,
        code=err.error_code,
        message=err.message,
    )
    response.headers["Retry-After"] = str(err.retry_after_seconds)
    return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        logger.info("database connectivity check succeeded")
    except (OSError, SQLAlchemyError):
        logger.exception("database connectivity check failed during startup")

    # Single async Redis client per process. ``decode_responses=True`` so the
    # rate limiter sees `str` rather than `bytes` from ZRANGE — keeps the
    # call sites readable. The pool size defaults are fine for v1; bump
    # ``max_connections`` if we add hot-path Redis use elsewhere.
    # ``from_url`` lacks a typed signature in redis-py 5.x; cast + ignore
    # keeps mypy --strict happy without disabling stubs project-wide.
    redis_client: redis_async.Redis = redis_async.from_url(  # type: ignore[no-untyped-call]
        settings.redis_url,
        decode_responses=True,
    )
    app.state.redis = redis_client

    try:
        yield
    finally:
        await engine.dispose()
        await redis_client.aclose()


def create_app() -> FastAPI:
    _init_sentry_if_configured()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    # Starlette wraps middlewares in reverse insertion order: the LAST
    # ``add_middleware`` is the OUTERMOST handler. We add the request
    # logger FIRST and the CORS middleware LAST so:
    #
    # - CORS is the outermost layer, which means the 500 response we
    #   build inside ``RequestLoggingMiddleware`` (when an inner route
    #   raises) still flows back through CORS on its way out — gaining
    #   ``Access-Control-Allow-Origin`` / ``Access-Control-Expose-
    #   Headers``. Without this ordering a cross-origin browser would
    #   see an opaque CORS failure on every 500 (no headers, can't
    #   read the X-Request-ID we attached, can't read the error body).
    # - The trade-off: CORS preflight ``OPTIONS`` responses are now
    #   built by CORSMiddleware without going through our access logger,
    #   so we don't emit an access line / X-Request-ID for them. Fine —
    #   preflights are protocol noise, not application traffic.
    app.add_middleware(RequestLoggingMiddleware)
    # Browser → API is cross-origin (web on 3000/3001, API on 8000). The
    # frontend sets credentials:'include' for the cookie session, so we must
    # echo back a specific origin (wildcard is not allowed with credentials)
    # and the CSRF header (X-Requested-With) on the allow-list.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        # ``X-Request-ID`` appears in both lists: ``allow_headers`` lets a
        # browser-side caller forward an upstream id (e.g. from the gateway)
        # via fetch / XHR; ``expose_headers`` lets the JS client read the
        # echoed id off the response so the UI can show / report it.
        # Without ``expose_headers`` browsers strip the header out of the
        # JS-visible response object even though it's on the wire.
        allow_headers=["Content-Type", "Accept", "X-Requested-With", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    # The RateLimited handler must be registered BEFORE the AppError one so
    # FastAPI's MRO-walking dispatch picks the more specific subclass and
    # we get the ``Retry-After`` header on 429s.
    app.add_exception_handler(RateLimited, rate_limited_handler)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    # Note: there is no ``add_exception_handler(Exception, ...)`` here on
    # purpose. Starlette routes that registration to ``ServerErrorMiddleware``
    # (the OUTERMOST middleware), so the 500 response would be built outside
    # ``RequestLoggingMiddleware``'s response path and the ``X-Request-ID``
    # header would never be attached. Instead, the middleware itself catches
    # unhandled exceptions and constructs the 500 response — see
    # ``RequestLoggingMiddleware.dispatch`` in ``app.core.logging``.
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(uploads_router)
    app.include_router(scans_router)
    return app


app = create_app()
