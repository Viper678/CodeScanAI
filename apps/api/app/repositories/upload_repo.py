"""Repository for the uploads table.

Reads always filter on ``user_id`` per BaseRepo's contract — that's how we get
the "no enumeration" guarantee for ``GET /uploads/{id}`` (docs/API.md §Uploads
+ docs/SECURITY.md §3).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from app.core.uuid7 import uuid7
from app.models.upload import Upload
from app.repositories.base import BaseRepo


class UploadRepo(BaseRepo[Upload]):
    async def get_by_id(self, id: UUID, *, user_id: UUID) -> Upload | None:
        result = await self.session.execute(
            select(Upload).where(Upload.id == id, Upload.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Upload]:
        result = await self.session.execute(
            select(Upload)
            .where(Upload.user_id == user_id)
            .order_by(Upload.created_at.desc(), Upload.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_for_user(self, *, user_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Upload).where(Upload.user_id == user_id)
        )
        total = result.scalar_one()
        return int(total)

    async def create(
        self,
        *,
        upload_id: UUID | None = None,
        user_id: UUID,
        original_name: str,
        kind: str,
        size_bytes: int,
        storage_path: str,
        status: str,
    ) -> Upload:
        upload = Upload(
            id=upload_id or uuid7(),
            user_id=user_id,
            original_name=original_name,
            kind=kind,
            size_bytes=size_bytes,
            storage_path=storage_path,
            status=status,
        )
        self.session.add(upload)
        await self.session.flush()
        return upload
