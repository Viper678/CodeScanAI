from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.exceptions import InvalidToken, Unauthorized
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user_repo import UserRepo


async def get_current_user(
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
    return user
