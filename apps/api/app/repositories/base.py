from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar("ModelT")


class BaseRepo(ABC, Generic[ModelT]):
    """Base repository contract for owned tables.

    Per docs/SECURITY.md §3, every read against an owned table must be scoped by
    `user_id`. UserRepo is the explicit exception because a user record is the
    ownership root.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @abstractmethod
    async def get_by_id(self, id: UUID, *, user_id: UUID) -> ModelT | None:
        """Load one row owned by `user_id`."""

    @abstractmethod
    async def list_for_user(
        self,
        *,
        user_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[ModelT]:
        """List rows owned by `user_id`."""
