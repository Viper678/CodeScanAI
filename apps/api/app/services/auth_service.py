from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import EmailAlreadyExists, InvalidCredentials, InvalidToken
from app.core.security import (
    JWT_ALGORITHM,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.core.uuid7 import uuid7
from app.models.user import User
from app.repositories.refresh_token_repo import RefreshTokenRepo
from app.repositories.user_repo import UserRepo

DUMMY_BCRYPT_HASH = "$2b$12$CwTycUXWue0Thq9StjUM0uJ8R7a9UeW9bFUY37w6f2GjjjPIbqA3u"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthCookies:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


def _decode_refresh_token(token: str) -> UUID:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
        )
        if payload.get("type") != "refresh":
            raise InvalidToken
        subject = payload.get("sub")
        issued_at = payload.get("iat")
        expires_at = payload.get("exp")
        if not isinstance(subject, str) or issued_at is None or expires_at is None:
            raise InvalidToken
        return UUID(subject)
    except (ValueError, jwt.InvalidTokenError) as exc:
        raise InvalidToken from exc


def _hash_refresh_token(raw_refresh_token: str) -> str:
    return hashlib.sha256(raw_refresh_token.encode("utf-8")).hexdigest()


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
        cookies = await self._issue_tokens(
            user=user,
            user_agent=user_agent,
            ip=ip,
            family_id=uuid7(),
        )
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

        cookies = await self._issue_tokens(
            user=user,
            user_agent=user_agent,
            ip=ip,
            family_id=uuid7(),
        )
        await self.session.commit()
        await self.session.refresh(user)
        return user, cookies

    async def refresh(
        self,
        *,
        raw_refresh_token: str,
        user_agent: str | None,
        ip: str | None,
    ) -> tuple[User, AuthCookies]:
        user_id = _decode_refresh_token(raw_refresh_token)
        refresh_hash = _hash_refresh_token(raw_refresh_token)
        refresh_row = await self.refresh_tokens.get_by_hash(refresh_hash)
        if refresh_row is None or refresh_row.user_id != user_id:
            raise InvalidToken

        user = await self.users.get_by_id(refresh_row.user_id)
        if user is None or not user.is_active:
            raise InvalidToken

        if refresh_row.revoked_at is not None:
            if refresh_row.family_id is not None:
                revoked_count = await self.refresh_tokens.revoke_family(
                    user.id,
                    refresh_row.family_id,
                )
                logger.warning(
                    "refresh_token_replay_detected",
                    extra={
                        "event": "refresh_token_replay_detected",
                        "user_id": str(user.id),
                        "family_id": str(refresh_row.family_id),
                        "tokens_revoked": revoked_count,
                        "ip": ip,
                        "user_agent": user_agent,
                    },
                )
            else:
                logger.warning(
                    "refresh_token_replay_detected_legacy",
                    extra={
                        "event": "refresh_token_replay_detected_legacy",
                        "user_id": str(user.id),
                        "ip": ip,
                        "user_agent": user_agent,
                    },
                )
            raise InvalidToken

        await self.refresh_tokens.revoke(refresh_row.id)
        family_id = refresh_row.family_id or uuid7()
        cookies = await self._issue_tokens(
            user=user,
            user_agent=user_agent,
            ip=ip,
            family_id=family_id,
        )
        await self.session.commit()
        await self.session.refresh(user)
        return user, cookies

    async def logout(self, *, raw_refresh_token: str) -> None:
        user_id = _decode_refresh_token(raw_refresh_token)
        refresh_hash = _hash_refresh_token(raw_refresh_token)
        refresh_row = await self.refresh_tokens.get_by_hash(refresh_hash)
        if refresh_row is None or refresh_row.user_id != user_id:
            raise InvalidToken

        await self.refresh_tokens.revoke(refresh_row.id)
        await self.session.commit()

    async def _issue_tokens(
        self,
        *,
        user: User,
        user_agent: str | None,
        ip: str | None,
        family_id: UUID | None = None,
    ) -> AuthCookies:
        access_token = create_access_token(user.id)
        refresh_token, refresh_hash, refresh_expires_at = create_refresh_token(user.id)
        await self.refresh_tokens.create(
            user_id=user.id,
            family_id=family_id or uuid7(),
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
