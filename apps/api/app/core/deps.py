from __future__ import annotations

from typing import Annotated, cast

from fastapi import Cookie, Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.exceptions import CsrfHeaderInvalid, InvalidToken, Unauthorized
from app.core.logging import user_id_var
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user_repo import UserRepo


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    cs_access: Annotated[str | None, Cookie()] = None,
) -> User:
    if cs_access is None:
        raise Unauthorized

    try:
        claims = decode_access_token(cs_access)
    except InvalidToken as exc:
        raise Unauthorized from exc

    user = await UserRepo(session).get_by_id(claims.user_id)
    if user is None or not user.is_active:
        raise Unauthorized
    # Stamp user_id in two places:
    # - ``user_id_var`` for any log emitted later within this request's
    #   ContextVar context (handlers, services).
    # - ``request.state.user_id`` so the access-log line emitted by the
    #   request middleware can see it. Starlette's ``BaseHTTPMiddleware``
    #   runs ``call_next`` in a child task, and contextvar mutations inside
    #   that child don't propagate back to the parent task that the
    #   middleware runs in — but ``request.state`` is shared.
    user_id_str = str(user.id)
    user_id_var.set(user_id_str)
    request.state.user_id = user_id_str
    return user


async def require_csrf_header(request: Request) -> None:
    if request.headers.get("X-Requested-With") != "codescan":
        raise CsrfHeaderInvalid


def get_redis(request: Request) -> Redis:
    """Return the process-wide async Redis client.

    The client is opened in :func:`app.main.lifespan` and stashed on
    ``app.state.redis``; callers grab the same instance via this dep so we
    don't churn connections per request. Tests override this dep to inject a
    stub or a connection pointed at a test Redis db.
    """

    return cast(Redis, request.app.state.redis)
