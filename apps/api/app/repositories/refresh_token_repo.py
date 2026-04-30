from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.uuid7 import uuid7
from app.models.refresh_token import RefreshToken


class RefreshTokenRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
        user_agent: str | None,
        ip: str | None,
    ) -> RefreshToken:
        refresh_token = RefreshToken(
            id=uuid7(),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            ip=ip,
        )
        self.session.add(refresh_token)
        await self.session.flush()
        return refresh_token
