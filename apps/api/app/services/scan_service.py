"""Business logic for the scans endpoints.

Validates the scan creation payload, persists the ``Scan`` row plus per-file
``ScanFile`` rows in PENDING, and enqueues ``run_scan`` on the Celery broker.
The actual scanning lives in the worker (T3.4); this service only stands up
the resource and the row-level state machine surfaced by ``cancel`` /
``delete``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
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
    ScanNotPausable,
    ScanNotResumable,
    UnprocessableRerun,
)
from app.models.scan import (
    SCAN_STATUS_CANCELLED,
    SCAN_STATUS_FAILED,
    SCAN_STATUS_PAUSED,
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
    KeywordsConfig,
    ScanCreateRequest,
    ScanDetail,
    ScanFileItem,
    ScanFilesResponse,
    ScanFileStatus,
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
        statuses: Sequence[str] | None,
        upload_id: UUID | None,
    ) -> ScanListResponse:
        rows = await self.scans.list_for_user(
            user_id=user_id,
            limit=limit,
            offset=offset,
            statuses=statuses,
            upload_id=upload_id,
        )
        total = await self.scans.count_for_user(
            user_id=user_id,
            statuses=statuses,
            upload_id=upload_id,
        )
        items: list[ScanDetail] = []
        for row in rows:
            summary = await self._build_summary(scan_id=row.id)
            items.append(_scan_to_detail(row, summary))
        return ScanListResponse(items=items, next_cursor=None, total=total)

    async def list_recent_scan_files(
        self,
        *,
        scan_id: UUID,
        user_id: UUID,
        limit: int,
    ) -> ScanFilesResponse:
        """Return the most-recently-finalized ``scan_files`` rows for a scan.

        Loads the scan first to enforce ownership-to-404 (so a stranger sees
        the same response shape as a missing row), then delegates to the repo.
        """

        scan = await self.scans.get_by_id(scan_id, user_id=user_id)
        if scan is None:
            raise NotFound("Scan not found")
        rows = await self.scan_files.list_recent_for_scan(
            scan_id=scan.id,
            user_id=user_id,
            limit=limit,
        )
        items = [
            ScanFileItem(
                id=row.id,
                file_id=row.file_id,
                path=path,
                status=cast(ScanFileStatus, row.status),
                error=row.error,
                tokens_in=row.tokens_in,
                tokens_out=row.tokens_out,
                latency_ms=row.latency_ms,
                started_at=row.started_at,
                finished_at=row.finished_at,
            )
            for row, path in rows
        ]
        return ScanFilesResponse(items=items)

    async def cancel_scan(self, *, scan_id: UUID, user_id: UUID) -> ScanDetail:
        scan = await self.scans.get_by_id(scan_id, user_id=user_id)
        if scan is None:
            raise NotFound("Scan not found")

        if scan.status in (SCAN_STATUS_PENDING, SCAN_STATUS_RUNNING, SCAN_STATUS_PAUSED):
            # paused → cancelled is a direct DB-only transition; no worker
            # wake-up needed because no worker is running. running → cancelled
            # is observed by the worker on its next between-files poll.
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

    async def pause_scan(self, *, scan_id: UUID, user_id: UUID) -> ScanDetail:
        """Flip a running scan to ``paused``; idempotent on already-paused.

        Mirrors :meth:`cancel_scan` — pause is a flag the worker polls for
        between files via the same status column. We don't notify the worker;
        it observes the new status on its next between-files check, finishes
        the in-flight file, and exits.
        """

        scan = await self.scans.get_by_id(scan_id, user_id=user_id)
        if scan is None:
            raise NotFound("Scan not found")

        if scan.status == SCAN_STATUS_RUNNING:
            scan.status = SCAN_STATUS_PAUSED
            await self.session.flush()
            await self.session.commit()
            await self.session.refresh(scan)
        elif scan.status == SCAN_STATUS_PAUSED:
            # Idempotent.
            pass
        else:
            raise ScanNotPausable(f"Cannot pause a scan in status '{scan.status}'")

        summary = await self._build_summary(scan_id=scan.id)
        return _scan_to_detail(scan, summary)

    async def resume_scan(self, *, scan_id: UUID, user_id: UUID) -> ScanDetail:
        """Flip a paused scan back to ``pending`` and re-enqueue ``run_scan``.

        The worker picks up the task and selects ``scan_files`` rows still in
        ``pending``, continuing from where the pause left off. If the broker
        is unreachable, the row stays ``paused`` so the user can retry.
        """

        scan = await self.scans.get_by_id(scan_id, user_id=user_id)
        if scan is None:
            raise NotFound("Scan not found")

        if scan.status != SCAN_STATUS_PAUSED:
            raise ScanNotResumable(f"Cannot resume a scan in status '{scan.status}'")

        scan.status = SCAN_STATUS_PENDING
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(scan)
        await self._enqueue_or_revert_to_paused(scan)
        summary = await self._build_summary(scan_id=scan.id)
        return _scan_to_detail(scan, summary)

    async def rerun_scan(
        self,
        *,
        scan_id: UUID,
        user_id: UUID,
        max_files_per_scan: int,
    ) -> Scan:
        """Reconstruct a scan's inputs from its source row and create a new one.

        Why a dedicated server-side path (vs. the client GETting the source
        and POSTing /scans):

        - ``ScanDetail`` doesn't expose ``file_ids`` or the keywords blob —
          and surfacing 500+ ids over the wire just to immediately bounce them
          back is the wrong shape.
        - One round-trip is atomic; the client double-roundtrip leaks a window
          where the source upload could be deleted between fetch and POST.
        - Same Celery enqueue + ownership validation path as ``create_scan``
          so we don't get two competing definitions of "valid scan request".

        Behavior:

        1. Load the source scan; 404 if missing or owned by someone else.
        2. Re-derive ``file_ids`` from ``scan_files`` for the source.
        3. Filter that list down to file ids that *still* exist on the upload
           (cleanup may have removed individual files since the source ran).
        4. If nothing's left, raise ``UnprocessableRerun`` — a 422 the UI can
           map to a friendly "the source has no scannable files anymore"
           message instead of a generic validation error.
        5. Build a ``ScanCreateRequest`` from the source's ``scan_types`` /
           ``keywords`` / ``model_settings`` and delegate to ``create_scan``,
           which does the rest (file-count cap, ownership re-check, persist,
           enqueue).

        Note: the ``upload_id`` FK is ``ON DELETE CASCADE``, so a deleted
        upload also wipes the source scan — which means step 1 already 404s
        for that case. ``UnprocessableRerun`` is reachable only via the
        scan-files-still-pointing-at-no-files path.
        """

        source = await self.scans.get_by_id(scan_id, user_id=user_id)
        if source is None:
            raise NotFound("Scan not found")

        scan_file_rows = await self.scan_files.list_for_scan(
            scan_id=source.id,
            user_id=user_id,
        )
        source_file_ids = [row.file_id for row in scan_file_rows]
        if not source_file_ids:
            # Source has no scan_files at all — nothing to re-run against.
            raise UnprocessableRerun("source scan has no files to re-run")

        existing_ids = await self.files.filter_existing_for_upload(
            file_ids=source_file_ids,
            upload_id=source.upload_id,
            user_id=user_id,
        )
        if not existing_ids:
            raise UnprocessableRerun("no scannable files remain in source")

        # Reconstruct the keywords blob — stored as JSONB on the row exactly
        # as posted, so re-validating through KeywordsConfig keeps the same
        # shape the original POST used. Empty dict → no keywords.
        keywords_payload: KeywordsConfig | None = None
        if source.keywords:
            try:
                keywords_payload = KeywordsConfig.model_validate(source.keywords)
            except Exception:  # pragma: no cover — defensive; create_scan re-validates
                keywords_payload = None

        request = ScanCreateRequest(
            upload_id=source.upload_id,
            name=source.name,
            scan_types=cast(list[ScanType], list(source.scan_types)),
            file_ids=existing_ids,
            keywords=keywords_payload,
            model_settings=dict(source.model_settings),
        )
        return await self.create_scan(
            user_id=user_id,
            request=request,
            max_files_per_scan=max_files_per_scan,
        )

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

    async def _enqueue_or_revert_to_paused(self, scan: Scan) -> None:
        # Resume variant of _enqueue_or_mark_failed: keep the row recoverable
        # by flipping back to `paused` rather than `failed` so the user can
        # retry resume once the broker comes back.
        # justify: kombu/redis raise unrelated types; catch any broker failure.
        try:
            self._enqueue(scan.id)
        except Exception:
            logger.exception(
                "failed to enqueue run_scan for scan %s on resume; reverting to paused",
                scan.id,
            )
            scan.status = SCAN_STATUS_PAUSED
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
        created_at=scan.created_at,
        summary=summary,
    )
