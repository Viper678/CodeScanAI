"""Business logic for the scans endpoints.

Validates the scan creation payload, persists the ``Scan`` row plus per-file
``ScanFile`` rows in PENDING, and enqueues ``run_scan`` on the Celery broker.
The actual scanning lives in the worker (T3.4); this service only stands up
the resource and the row-level state machine surfaced by ``cancel`` /
``delete``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InvalidScanRequest,
    NotFound,
    QueueUnavailable,
    ScanCancelConflict,
    ScanFilesForbidden,
)
from app.models.scan import (
    SCAN_STATUS_CANCELLED,
    SCAN_STATUS_FAILED,
    SCAN_STATUS_PENDING,
    SCAN_STATUS_RUNNING,
    SCAN_TYPE_KEYWORDS,
    Scan,
)
from app.models.scan_finding import ScanFinding
from app.repositories.file_repo import FileRepo
from app.repositories.scan_file_repo import ScanFileRepo
from app.repositories.scan_repo import ScanRepo
from app.repositories.upload_repo import UploadRepo
from app.schemas.scan import (
    ScanCreateRequest,
    ScanDetail,
    ScanListResponse,
    ScanStatus,
    ScanSummary,
    ScanType,
    Severity,
)
from app.services.celery_client import enqueue_run_scan

logger = logging.getLogger(__name__)


class ScanEnqueuer(Protocol):
    """Indirection so tests can replace the broker call without monkey-patching."""

    def __call__(self, scan_id: UUID) -> None: ...


class ScanService:
    """Orchestrates scan validation, persistence, and enqueue."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        enqueuer: ScanEnqueuer | None = None,
    ) -> None:
        self.session = session
        self.scans = ScanRepo(session)
        self.scan_files = ScanFileRepo(session)
        self.uploads = UploadRepo(session)
        self.files = FileRepo(session)
        self._enqueue = enqueuer or enqueue_run_scan

    async def create_scan(
        self,
        *,
        user_id: UUID,
        request: ScanCreateRequest,
        max_files_per_scan: int,
    ) -> Scan:
        if not request.scan_types:
            raise InvalidScanRequest("scan_types must be non-empty")
        if SCAN_TYPE_KEYWORDS in request.scan_types and (
            request.keywords is None or not request.keywords.items
        ):
            raise InvalidScanRequest(
                "keywords.items is required when scan_types includes 'keywords'"
            )
        if not request.file_ids:
            raise InvalidScanRequest("file_ids must be non-empty")
        if len(request.file_ids) > max_files_per_scan:
            raise InvalidScanRequest(f"Too many files; max {max_files_per_scan} per scan")
        # SQL ``IN (...)`` collapses duplicates, so a payload like
        # [same_id, same_id] would shrink ``owned_count`` and surface as a 403.
        # Reject duplicates as a 422 instead — they're a client bug, not auth.
        if len(set(request.file_ids)) != len(request.file_ids):
            raise InvalidScanRequest("file_ids must not contain duplicates")

        upload = await self.uploads.get_by_id(request.upload_id, user_id=user_id)
        if upload is None:
            # 404 (not 403) — same no-enumeration pattern as GET /uploads/{id}.
            # See docs/SECURITY.md §3.
            raise NotFound("Upload not found")

        # One SQL round-trip — see FileRepo.count_for_upload_owned_by_user docstring;
        # do not refactor to N+1 ``get_by_id`` calls.
        owned_count = await self.files.count_for_upload_owned_by_user(
            file_ids=request.file_ids,
            upload_id=request.upload_id,
            user_id=user_id,
        )
        if owned_count != len(request.file_ids):
            raise ScanFilesForbidden("file_ids contains files you don't have access to")

        keywords_payload = request.keywords.model_dump() if request.keywords is not None else {}
        scan = await self.scans.create(
            user_id=user_id,
            upload_id=request.upload_id,
            name=request.name,
            scan_types=list(request.scan_types),
            keywords=keywords_payload,
            model_settings=request.model_settings,
            progress_total=len(request.file_ids),
        )
        await self.scan_files.bulk_create(
            scan_id=scan.id,
            file_ids=list(request.file_ids),
        )
        await self.session.commit()
        await self.session.refresh(scan)
        await self._enqueue_or_mark_failed(scan)
        return scan

    async def get_scan_detail(self, *, scan_id: UUID, user_id: UUID) -> ScanDetail:
        scan = await self.scans.get_by_id(scan_id, user_id=user_id)
        if scan is None:
            raise NotFound("Scan not found")
        summary = await self._build_summary(scan_id=scan.id)
        return _scan_to_detail(scan, summary)

    async def list_scans(
        self,
        *,
        user_id: UUID,
        limit: int,
        offset: int,
        status: str | None,
        upload_id: UUID | None,
    ) -> ScanListResponse:
        rows = await self.scans.list_for_user(
            user_id=user_id,
            limit=limit,
            offset=offset,
            status=status,
            upload_id=upload_id,
        )
        total = await self.scans.count_for_user(
            user_id=user_id,
            status=status,
            upload_id=upload_id,
        )
        items: list[ScanDetail] = []
        for row in rows:
            summary = await self._build_summary(scan_id=row.id)
            items.append(_scan_to_detail(row, summary))
        return ScanListResponse(items=items, next_cursor=None, total=total)

    async def cancel_scan(self, *, scan_id: UUID, user_id: UUID) -> ScanDetail:
        scan = await self.scans.get_by_id(scan_id, user_id=user_id)
        if scan is None:
            raise NotFound("Scan not found")

        if scan.status in (SCAN_STATUS_PENDING, SCAN_STATUS_RUNNING):
            scan.status = SCAN_STATUS_CANCELLED
            scan.finished_at = datetime.now(UTC)
            await self.session.flush()
            await self.session.commit()
            await self.session.refresh(scan)
        elif scan.status == SCAN_STATUS_CANCELLED:
            # Idempotent — return the row as-is.
            pass
        else:
            raise ScanCancelConflict(f"Cannot cancel a scan in status '{scan.status}'")

        summary = await self._build_summary(scan_id=scan.id)
        return _scan_to_detail(scan, summary)

    async def delete_scan(self, *, scan_id: UUID, user_id: UUID) -> None:
        scan = await self.scans.get_by_id(scan_id, user_id=user_id)
        if scan is None:
            raise NotFound("Scan not found")
        await self.session.delete(scan)
        await self.session.commit()

    async def _build_summary(self, *, scan_id: UUID) -> ScanSummary:
        severity_result = await self.session.execute(
            select(ScanFinding.severity, func.count())
            .where(ScanFinding.scan_id == scan_id)
            .group_by(ScanFinding.severity)
        )
        by_severity: dict[Severity, int] = {
            cast(Severity, severity): int(count) for severity, count in severity_result.all()
        }
        type_result = await self.session.execute(
            select(ScanFinding.scan_type, func.count())
            .where(ScanFinding.scan_id == scan_id)
            .group_by(ScanFinding.scan_type)
        )
        by_type: dict[ScanType, int] = {
            cast(ScanType, scan_type): int(count) for scan_type, count in type_result.all()
        }
        return ScanSummary(by_severity=by_severity, by_type=by_type)

    async def _enqueue_or_mark_failed(self, scan: Scan) -> None:
        # Mirrors UploadService._enqueue_or_mark_failed: if the broker is down,
        # we'd otherwise leave the row stuck in `pending` forever. Reflect the
        # failure in the DB and surface 503 so the client can react.
        # justify: kombu/redis raise unrelated types; catch any broker failure.
        try:
            self._enqueue(scan.id)
        except Exception:
            logger.exception(
                "failed to enqueue run_scan for scan %s; marking failed",
                scan.id,
            )
            scan.status = SCAN_STATUS_FAILED
            scan.error = "queue_unavailable"
            await self.session.commit()
            raise QueueUnavailable() from None


def _scan_to_detail(scan: Scan, summary: ScanSummary) -> ScanDetail:
    return ScanDetail(
        id=scan.id,
        name=scan.name,
        upload_id=scan.upload_id,
        scan_types=cast(list[ScanType], list(scan.scan_types)),
        status=cast(ScanStatus, scan.status),
        progress_done=scan.progress_done,
        progress_total=scan.progress_total,
        started_at=scan.started_at,
        finished_at=scan.finished_at,
        summary=summary,
    )
