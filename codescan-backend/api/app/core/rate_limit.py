"""Redis-backed sliding-window rate limiter (T5.1).

Lives under ``app.core`` because it's a cross-cutting policy applied via
FastAPI dependencies — it has no business logic of its own and no database
access, so a service-layer module would be misplaced.

Algorithm: per-key sorted set whose members are unique per request and whose
scores are timestamps. On each check we trim entries outside the window with
``ZREMRANGEBYSCORE``, count remaining members with ``ZCARD``, and only then
``ZADD`` the new slot when there's headroom. Two concurrent requests can both
see ``count < limit`` and both add (a 1-request slop at the boundary), but
that's acceptable for credential-stuffing / DoS-soft mitigation — the spec
calls this "best-effort", not a security gate.

Failure mode: if Redis is unreachable the limiter **fails open** — the
request proceeds and a WARNING-level log line is emitted. Reasoning:

1. The rate limiter is a defence-in-depth layer; the auth flow already has
   bcrypt + 401-uniformity, and the upload/scan flows have payload caps and
   user-scoped writes. None of those depend on the limiter to be correct.
2. A hard failure (5xx everywhere when Redis blips) would be a strictly
   worse outage than a brief rate-limit gap, especially because Redis is
   already on the upload/scan critical path via Celery.

Do not "fix" the fail-open behaviour by raising on RedisError without first
re-reading docs/SECURITY.md and the rationale above.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.deps import get_current_user, get_redis
from app.core.exceptions import RateLimited
from app.models.user import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of a single sliding-window check."""

    allowed: bool
    """True iff the request is under the limit."""

    retry_after_seconds: int
    """Seconds the caller should wait before retrying. 0 when allowed."""


async def check_sliding_window(
    redis_client: Redis,
    *,
    key: str,
    limit: int,
    window_seconds: float,
    clock: Callable[[], float] = time.time,
) -> RateLimitDecision:
    """Sliding-window check against a Redis sorted set.

    Order of operations:

    1. Pipeline ``ZREMRANGEBYSCORE`` (drop entries older than now-window) +
       ``ZCARD`` (count remaining). One round-trip.
    2. If the count is at or above the limit, compute ``Retry-After`` from
       the oldest in-window entry and return ``allowed=False``. We do *not*
       insert a new slot in this branch — burning a slot per rejected
       request would extend the cooldown indefinitely under sustained load,
       which is the wrong threat model for "5/min credential-stuffing".
    3. Otherwise, pipeline ``ZADD`` (insert a unique slot at the current
       timestamp) + ``EXPIRE`` (best-effort cleanup so abandoned keys don't
       linger). Return ``allowed=True``.

    The ``clock`` parameter is injected so unit tests can drive a virtual
    time without sleeping. Production callers always use ``time.time``.
    """

    current = clock()
    cutoff = current - window_seconds

    # Step 1: trim + count.
    pipe = redis_client.pipeline(transaction=False)
    pipe.zremrangebyscore(key, 0, cutoff)
    pipe.zcard(key)
    _, count_in_window = await pipe.execute()
    count_in_window = int(count_in_window)

    if count_in_window >= limit:
        oldest = await redis_client.zrange(key, 0, 0, withscores=True)
        if oldest:
            oldest_ts = float(oldest[0][1])
            # Round up so a fractional remainder still yields a non-zero
            # ``Retry-After`` — the header is integer seconds.
            retry_after = max(1, int(oldest_ts + window_seconds - current) + 1)
        else:
            # Race: window emptied between our trim and zrange. Tell the
            # client to retry immediately rather than guessing an interval.
            retry_after = 1
        return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)

    # Step 3: claim a slot. The unique member key sidesteps "two requests at
    # the same float timestamp" collisions (which would otherwise dedupe).
    member = f"{current:.6f}-{uuid.uuid4().hex}"
    pipe = redis_client.pipeline(transaction=False)
    pipe.zadd(key, {member: current})
    # ``window_seconds`` may be a float; EXPIRE wants ints. Round up so the
    # key never expires before its last tracked entry.
    pipe.expire(key, int(window_seconds) + 1)
    await pipe.execute()
    return RateLimitDecision(allowed=True, retry_after_seconds=0)


def _build_key(key_prefix: str, scope: str, value: str) -> str:
    namespace = settings.rate_limit_key_namespace
    if namespace:
        return f"rl:{namespace}:{key_prefix}:{scope}:{value}"
    return f"rl:{key_prefix}:{scope}:{value}"


def _client_ip(request: Request) -> str:
    """Best-effort client IP. Mirrors the helper in ``routers/auth.py``.

    Falls back to ``"unknown"`` so we still rate-limit something — the
    alternative (skipping the limit when client info is missing) would be
    abuseable behind a misconfigured proxy.
    """

    return request.client.host if request.client is not None else "unknown"


def rate_limit_per_ip(
    *,
    limit_factory: Callable[[], int],
    window_seconds: int,
    key_prefix: str,
) -> Callable[..., Awaitable[None]]:
    """Build a FastAPI dependency that rate-limits by client IP.

    Use on routes that run before authentication (e.g. login/register).
    ``limit_factory`` is a thunk so the value is read on every request and
    env-driven config changes don't require a process restart.
    """

    async def _dep(
        request: Request,
        redis_client: Annotated[Redis, Depends(get_redis)],
    ) -> None:
        ip = _client_ip(request)
        key = _build_key(key_prefix, "ip", ip)
        try:
            decision = await check_sliding_window(
                redis_client,
                key=key,
                limit=limit_factory(),
                window_seconds=window_seconds,
            )
        except RedisError:
            logger.warning(
                "rate_limit redis unreachable; failing open for %s",
                key_prefix,
                exc_info=True,
            )
            return
        if not decision.allowed:
            raise RateLimited(retry_after_seconds=decision.retry_after_seconds)

    return _dep


def rate_limit_per_user(
    *,
    limit_factory: Callable[[], int],
    window_seconds: int,
    key_prefix: str,
) -> Callable[..., Awaitable[None]]:
    """Build a FastAPI dependency that rate-limits by authenticated user.

    Composes with ``get_current_user`` so the route still 401s for an
    unauthenticated caller — the rate limit applies only to logged-in users
    and counts against ``user.id``, not the IP.
    """

    async def _dep(
        current_user: Annotated[User, Depends(get_current_user)],
        redis_client: Annotated[Redis, Depends(get_redis)],
    ) -> None:
        key = _build_key(key_prefix, "user", str(current_user.id))
        try:
            decision = await check_sliding_window(
                redis_client,
                key=key,
                limit=limit_factory(),
                window_seconds=window_seconds,
            )
        except RedisError:
            logger.warning(
                "rate_limit redis unreachable; failing open for %s",
                key_prefix,
                exc_info=True,
            )
            return
        if not decision.allowed:
            raise RateLimited(retry_after_seconds=decision.retry_after_seconds)

    return _dep
