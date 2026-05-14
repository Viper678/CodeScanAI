"""Health endpoints (T0.1 + T5.3).

``/healthz`` is the cheap process-up check — no I/O, no auth, returns immediately.
``/readyz`` is the dependency-readiness probe used by docker-compose's healthcheck
and any orchestrator. It hits Postgres + Redis with a 2-second per-check timeout
and returns a stable schema regardless of HTTP status (200 ok or 503 fail).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_redis

# Per-check timeout. Both checks run in parallel via ``asyncio.gather`` so
# the wall-clock budget for the endpoint is bounded by this constant, not
# twice it. Keeping it tight (2s) so a hung dep can't make the orchestrator
# wait minutes — well inside T5.3's "503 within 5s" AC.
CHECK_TIMEOUT_SECONDS = 2.0

DependencyStatus = Literal["ok", "fail"]

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyzResponse(BaseModel):
    """Body for ``/readyz``, used on **both** 200 and 503.

    Diverges deliberately from the standard error envelope used elsewhere in
    the API. Orchestrators (docker-compose, k8s readiness probes) want a
    stable schema regardless of HTTP status — they parse the same keys
    whether the probe is passing or failing. Squeezing this into the
    ``{error: {code, message}}`` envelope on 503 would force them to handle
    two shapes for the same endpoint.
    """

    status: DependencyStatus
    db: DependencyStatus
    redis: DependencyStatus


router = APIRouter()


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


async def _check_db(session: AsyncSession) -> DependencyStatus:
    """Cheap connectivity probe: ``SELECT 1`` with a hard timeout.

    A timeout, a SQLAlchemy error, or an OS-level network error all collapse
    to ``"fail"`` — orchestrators only need to know whether traffic should
    flow, not the exact failure mode. The exception is logged so an operator
    tailing api logs can still diagnose post-hoc.
    """

    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            await session.execute(text("SELECT 1"))
    except (TimeoutError, SQLAlchemyError, OSError):
        logger.warning("readyz: database check failed", exc_info=True)
        return "fail"
    return "ok"


async def _check_redis(redis_client: Redis) -> DependencyStatus:
    """Cheap connectivity probe: ``PING`` with a hard timeout."""

    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            await redis_client.ping()
    except (TimeoutError, RedisError, OSError):
        logger.warning("readyz: redis check failed", exc_info=True)
        return "fail"
    return "ok"


@router.get(
    "/readyz",
    # Document both shapes for OpenAPI; the function returns ``JSONResponse``
    # so the actual status code is set dynamically and ``response_model``
    # alone wouldn't capture the 503 path.
    responses={
        200: {"model": ReadyzResponse, "description": "All dependencies healthy"},
        503: {"model": ReadyzResponse, "description": "One or more dependencies failed"},
    },
)
async def readyz(
    session: Annotated[AsyncSession, Depends(get_session)],
    redis_client: Annotated[Redis, Depends(get_redis)],
) -> JSONResponse:
    """Dependency-readiness probe for docker-compose / orchestrators (T5.3).

    Runs the DB and Redis checks in parallel via ``asyncio.gather`` so the
    endpoint's wall-clock cost is the slower of the two, not their sum. The
    body shape is identical on 200 and 503 (see :class:`ReadyzResponse`).
    """

    db_status, redis_status = await asyncio.gather(
        _check_db(session),
        _check_redis(redis_client),
    )
    overall: DependencyStatus = "ok" if db_status == "ok" and redis_status == "ok" else "fail"
    body = ReadyzResponse(status=overall, db=db_status, redis=redis_status)
    status_code = 200 if overall == "ok" else 503
    return JSONResponse(status_code=status_code, content=body.model_dump())
