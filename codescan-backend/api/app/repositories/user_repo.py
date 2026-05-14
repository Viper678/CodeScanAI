from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.uuid7 import uuid7
from app.models.user import User
from app.repositories.base import BaseRepo


class UserRepo(BaseRepo[User]):
    """Repository for users.

    Users are the ownership root, so the row's `id` is the user-id for the
    mandatory ownership filter rule from BaseRepo.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, id: UUID, *, user_id: UUID | None = None) -> User | None:
        if user_id is not None and user_id != id:
            return None
        result = await self.session.execute(select(User).where(User.id == id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(self, email: str, password_hash: str) -> User:
        user = User(id=uuid7(), email=email, password_hash=password_hash)
        self.session.add(user)
        await self.session.flush()
        return user

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[User]:
        result = await self.session.execute(
            select(User).where(User.id == user_id).limit(limit).offset(offset)
        )
        return list(result.scalars().all())
