"""Repository for the scans table.

Reads always filter on ``user_id`` per BaseRepo's contract — see
docs/SECURITY.md §3. The ``scans`` table carries its own ``user_id`` so
ownership scoping is a direct WHERE clause (no JOIN needed).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.core.uuid7 import uuid7
from app.models.scan import SCAN_STATUS_PENDING, Scan
from app.repositories.base import BaseRepo


class ScanRepo(BaseRepo[Scan]):
    async def get_by_id(self, id: UUID, *, user_id: UUID) -> Scan | None:
        result = await self.session.execute(
            select(Scan).where(Scan.id == id, Scan.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        upload_id: UUID | None = None,
    ) -> list[Scan]:
        statement = select(Scan).where(Scan.user_id == user_id)
        if status is not None:
            statement = statement.where(Scan.status == status)
        if upload_id is not None:
            statement = statement.where(Scan.upload_id == upload_id)
        statement = (
            statement.order_by(Scan.created_at.desc(), Scan.id.desc()).limit(limit).offset(offset)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def count_for_user(
        self,
        *,
        user_id: UUID,
        status: str | None = None,
        upload_id: UUID | None = None,
    ) -> int:
        statement = select(func.count()).select_from(Scan).where(Scan.user_id == user_id)
        if status is not None:
            statement = statement.where(Scan.status == status)
        if upload_id is not None:
            statement = statement.where(Scan.upload_id == upload_id)
        result = await self.session.execute(statement)
        total = result.scalar_one()
        return int(total)

    async def create(
        self,
        *,
        scan_id: UUID | None = None,
        user_id: UUID,
        upload_id: UUID,
        name: str | None,
        scan_types: list[str],
        keywords: dict[str, Any] | None = None,
        model: str | None = None,
        model_settings: dict[str, Any] | None = None,
        progress_total: int = 0,
    ) -> Scan:
        scan = Scan(
            id=scan_id or uuid7(),
            user_id=user_id,
            upload_id=upload_id,
            name=name,
            scan_types=scan_types,
            keywords=keywords if keywords is not None else {},
            status=SCAN_STATUS_PENDING,
            progress_done=0,
            progress_total=progress_total,
            model_settings=model_settings if model_settings is not None else {},
        )
        # Only override the column server_default when an explicit value is
        # passed; otherwise let Postgres apply 'gemma-4-31b-it'.
        if model is not None:
            scan.model = model
        self.session.add(scan)
        await self.session.flush()
        await self.session.refresh(scan)
        return scan
