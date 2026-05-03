from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.db import engine
from app.core.exceptions import AppError
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.routers.scans import router as scans_router
from app.routers.uploads import router as uploads_router

logger = logging.getLogger(__name__)

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


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        logger.info("database connectivity check succeeded")
    except (OSError, SQLAlchemyError):
        logger.exception("database connectivity check failed during startup")

    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    # Browser → API is cross-origin (web on 3000/3001, API on 8000). The
    # frontend sets credentials:'include' for the cookie session, so we must
    # echo back a specific origin (wildcard is not allowed with credentials)
    # and the CSRF header (X-Requested-With) on the allow-list.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "X-Requested-With"],
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(uploads_router)
    app.include_router(scans_router)
    return app


app = create_app()
