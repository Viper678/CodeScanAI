"""Repository for the scan_findings table.

The ``scan_findings`` table is owned transitively through ``scans.user_id`` —
there's no ``user_id`` column on the row itself. Per docs/SECURITY.md §3
(and the BaseRepo contract), every read is scoped by the caller's
``user_id`` via a JOIN onto ``scans``.

Severity ordering for sorted listings is critical → high → medium → low →
info, expressed via a ``CASE`` expression to mirror the SQL example in
docs/SCHEMA.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import case, select

from app.models.scan import Scan
from app.models.scan_finding import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_INFO,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    ScanFinding,
)
from app.repositories.base import BaseRepo

_SEVERITY_RANK = case(
    {
        SEVERITY_CRITICAL: 0,
        SEVERITY_HIGH: 1,
        SEVERITY_MEDIUM: 2,
        SEVERITY_LOW: 3,
        SEVERITY_INFO: 4,
    },
    value=ScanFinding.severity,
    else_=99,
)


class ScanFindingRepo(BaseRepo[ScanFinding]):
    async def get_by_id(self, id: UUID, *, user_id: UUID) -> ScanFinding | None:
        result = await self.session.execute(
            select(ScanFinding)
            .join(Scan, Scan.id == ScanFinding.scan_id)
            .where(ScanFinding.id == id, Scan.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[ScanFinding]:
        # Cross-scan listing is provided for symmetry with BaseRepo; routers
        # use ``list_for_scan`` instead. Capped by ``limit``.
        result = await self.session.execute(
            select(ScanFinding)
            .join(Scan, Scan.id == ScanFinding.scan_id)
            .where(Scan.user_id == user_id)
            .order_by(ScanFinding.scan_id, ScanFinding.severity, ScanFinding.file_id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_for_scan(
        self,
        *,
        scan_id: UUID,
        user_id: UUID,
        severity: str | None = None,
        scan_type: str | None = None,
        file_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ScanFinding]:
        statement = (
            select(ScanFinding)
            .join(Scan, Scan.id == ScanFinding.scan_id)
            .where(ScanFinding.scan_id == scan_id, Scan.user_id == user_id)
        )
        if severity is not None:
            statement = statement.where(ScanFinding.severity == severity)
        if scan_type is not None:
            statement = statement.where(ScanFinding.scan_type == scan_type)
        if file_id is not None:
            statement = statement.where(ScanFinding.file_id == file_id)
        statement = (
            statement.order_by(_SEVERITY_RANK, ScanFinding.file_id, ScanFinding.line_start)
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
