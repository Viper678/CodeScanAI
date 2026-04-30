from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EmailAlreadyExists, InvalidCredentials
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.repositories.refresh_token_repo import RefreshTokenRepo
from app.repositories.user_repo import UserRepo

DUMMY_BCRYPT_HASH = "$2b$12$CwTycUXWue0Thq9StjUM0uJ8R7a9UeW9bFUY37w6f2GjjjPIbqA3u"


@dataclass(frozen=True)
class AuthCookies:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepo(session)
        self.refresh_tokens = RefreshTokenRepo(session)

    async def register(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None,
        ip: str | None,
    ) -> tuple[User, AuthCookies]:
        email = email.lower()
        existing_user = await self.users.get_by_email(email)
        if existing_user is not None:
            raise EmailAlreadyExists

        user = await self.users.create(email=email, password_hash=hash_password(password))
        cookies = await self._issue_tokens(user=user, user_agent=user_agent, ip=ip)
        await self.session.commit()
        await self.session.refresh(user)
        return user, cookies

    async def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None,
        ip: str | None,
    ) -> tuple[User, AuthCookies]:
        email = email.lower()
        user = await self.users.get_by_email(email)
        password_hash = user.password_hash if user is not None else DUMMY_BCRYPT_HASH
        password_ok = verify_password(password, password_hash)
        if user is None or not user.is_active or not password_ok:
            raise InvalidCredentials

        cookies = await self._issue_tokens(user=user, user_agent=user_agent, ip=ip)
        await self.session.commit()
        await self.session.refresh(user)
        return user, cookies

    async def _issue_tokens(
        self,
        *,
        user: User,
        user_agent: str | None,
        ip: str | None,
    ) -> AuthCookies:
        access_token = create_access_token(user.id)
        refresh_token, refresh_hash, refresh_expires_at = create_refresh_token(user.id)
        await self.refresh_tokens.create(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=refresh_expires_at,
            user_agent=user_agent,
            ip=ip,
        )
        access_expires_at = decode_access_token(access_token).expires_at
        return AuthCookies(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
        )
