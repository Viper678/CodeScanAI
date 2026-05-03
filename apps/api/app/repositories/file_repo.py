"""Repository for the files table.

The ``files`` table is owned transitively through ``uploads.user_id`` — there's
no ``user_id`` column on the row itself. Per docs/SECURITY.md §3 (and the
BaseRepo contract), every read still has to be scoped by the caller's
``user_id``: we enforce that with a JOIN onto ``uploads`` so a stolen ``id`` for
some other user's row is impossible to surface even if a router forgets to
check ownership first.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from app.models.file import File
from app.models.upload import Upload
from app.repositories.base import BaseRepo


class FileRepo(BaseRepo[File]):
    async def get_by_id(self, id: UUID, *, user_id: UUID) -> File | None:
        result = await self.session.execute(
            select(File)
            .join(Upload, Upload.id == File.upload_id)
            .where(File.id == id, Upload.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[File]:
        # Not used for the tree endpoint (which is per-upload), but BaseRepo
        # makes us implement it. Returns the user's files in path order across
        # all their uploads — handy for diagnostics; capped by limit.
        result = await self.session.execute(
            select(File)
            .join(Upload, Upload.id == File.upload_id)
            .where(Upload.user_id == user_id)
            .order_by(File.upload_id, File.path)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_for_upload(
        self,
        *,
        upload_id: UUID,
        user_id: UUID,
    ) -> list[File]:
        """Return every ``files`` row for an upload owned by ``user_id``.

        Sorted by ``path`` lexicographically so the frontend can build the
        tree in one pass — see docs/FILE_HANDLING.md §"Tree presentation
        contract" and docs/SCHEMA.md §files. No pagination: uploads are
        capped at 20k rows by the upload limits and the UI wants the full
        tree at once.
        """

        result = await self.session.execute(
            select(File)
            .join(Upload, Upload.id == File.upload_id)
            .where(Upload.id == upload_id, Upload.user_id == user_id)
            .order_by(File.path)
        )
        return list(result.scalars().all())
