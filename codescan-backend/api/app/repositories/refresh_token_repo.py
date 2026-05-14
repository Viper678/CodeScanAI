from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Result, Select, func, select, update

from app.core.uuid7 import uuid7
from app.models.refresh_token import RefreshToken
from app.repositories.base import BaseRepo


class RefreshTokenRepo(BaseRepo[RefreshToken]):
    async def get_by_id(self, id: UUID, *, user_id: UUID) -> RefreshToken | None:
        result = await self.session.execute(
            select(RefreshToken).where(RefreshToken.id == id, RefreshToken.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RefreshToken]:
        result = await self.session.execute(
            select(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .order_by(RefreshToken.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        user_id: UUID,
        family_id: UUID | None,
        token_hash: str,
        expires_at: datetime,
        user_agent: str | None,
        ip: str | None,
    ) -> RefreshToken:
        refresh_token = RefreshToken(
            id=uuid7(),
            user_id=user_id,
            family_id=family_id,
            token_hash=token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            ip=ip,
        )
        self.session.add(refresh_token)
        await self.session.flush()
        return refresh_token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Look up a refresh token by hash before user ownership is known.

        This is the one repository read that intentionally bypasses the usual
        mandatory `user_id` filter because refresh authentication starts from
        the presented token hash itself; the row provides the `user_id`.
        """

        result: Result[tuple[RefreshToken]] = await self.session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def revoke(self, token_id: UUID) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )

    async def revoke_family(self, user_id: UUID, family_id: UUID) -> int:
        statement: Select[tuple[UUID]] = (
            select(RefreshToken.id)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .with_for_update()
        )
        token_ids = list((await self.session.execute(statement)).scalars().all())
        if not token_ids:
            return 0

        await self.session.execute(
            update(RefreshToken).where(RefreshToken.id.in_(token_ids)).values(revoked_at=func.now())
        )
        return len(token_ids)
