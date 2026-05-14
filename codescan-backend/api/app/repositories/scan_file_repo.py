"""Repository for the scan_files table.

The ``scan_files`` table is owned transitively through ``scans.user_id`` —
there's no ``user_id`` column on the row itself. Per docs/SECURITY.md §3
(and the BaseRepo contract), every read still has to be scoped by the
caller's ``user_id``: we enforce that with a JOIN onto ``scans`` so a stolen
``id`` for some other user's row is impossible to surface even if a router
forgets to check ownership first.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from app.core.uuid7 import uuid7
from app.models.file import File
from app.models.scan import Scan
from app.models.scan_file import SCAN_FILE_STATUS_PENDING, ScanFile
from app.repositories.base import BaseRepo


class ScanFileRepo(BaseRepo[ScanFile]):
    async def get_by_id(self, id: UUID, *, user_id: UUID) -> ScanFile | None:
        result = await self.session.execute(
            select(ScanFile)
            .join(Scan, Scan.id == ScanFile.scan_id)
            .where(ScanFile.id == id, Scan.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[ScanFile]:
        # Cross-scan listing is provided for symmetry with BaseRepo; routers
        # use ``list_for_scan`` instead. Capped by ``limit``.
        result = await self.session.execute(
            select(ScanFile)
            .join(Scan, Scan.id == ScanFile.scan_id)
            .where(Scan.user_id == user_id)
            .order_by(ScanFile.scan_id, ScanFile.file_id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_for_scan(
        self,
        *,
        scan_id: UUID,
        user_id: UUID,
    ) -> list[ScanFile]:
        """Return every ``scan_files`` row for a scan owned by ``user_id``."""

        result = await self.session.execute(
            select(ScanFile)
            .join(Scan, Scan.id == ScanFile.scan_id)
            .where(ScanFile.scan_id == scan_id, Scan.user_id == user_id)
            .order_by(ScanFile.file_id)
        )
        return list(result.scalars().all())

    async def list_recent_for_scan(
        self,
        *,
        scan_id: UUID,
        user_id: UUID,
        limit: int,
    ) -> list[tuple[ScanFile, str]]:
        """Return the N most-recently-finalized rows for a scan.

        Joined to ``files`` so the caller has the path alongside each row.
        Ordered by ``finished_at DESC NULLS LAST, ScanFile.id DESC`` so freshly
        finalized rows lead and pending/running rows trail. Ownership is
        enforced via the JOIN onto ``scans`` (per the BaseRepo contract).

        Returns a list of ``(ScanFile, path)`` tuples. The router caps
        ``limit`` to a sane ceiling — repo trusts the caller.
        """

        result = await self.session.execute(
            select(ScanFile, File.path)
            .join(Scan, Scan.id == ScanFile.scan_id)
            .join(File, File.id == ScanFile.file_id)
            .where(ScanFile.scan_id == scan_id, Scan.user_id == user_id)
            .order_by(
                ScanFile.finished_at.desc().nullslast(),
                ScanFile.id.desc(),
            )
            .limit(limit)
        )
        return [(row, path) for row, path in result.all()]

    async def bulk_create(
        self,
        *,
        scan_id: UUID,
        file_ids: Sequence[UUID],
    ) -> list[ScanFile]:
        """Insert one PENDING ``scan_files`` row per ``file_id`` in a single flush.

        Caller is expected to have already validated ownership of ``scan_id``
        — this method does not enforce it.
        """

        rows = [
            ScanFile(
                id=uuid7(),
                scan_id=scan_id,
                file_id=file_id,
                status=SCAN_FILE_STATUS_PENDING,
            )
            for file_id in file_ids
        ]
        self.session.add_all(rows)
        await self.session.flush()
        return rows
