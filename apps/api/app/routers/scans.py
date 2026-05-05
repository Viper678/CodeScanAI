"""Scan endpoints.

The router stays intentionally thin — validation and persistence live in
``app.services.scan_service``. Auth is enforced via a router-wide
``Depends(get_current_user)`` and CSRF on the mutating endpoints
(``POST /scans``, ``POST /scans/{id}/cancel``, ``DELETE /scans/{id}``).
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.deps import get_current_user, require_csrf_header
from app.core.exceptions import InvalidScanRequest
from app.models.user import User
from app.schemas.scan import (
    ScanCreateRequest,
    ScanCreateResponse,
    ScanDetail,
    ScanFilesResponse,
    ScanFindingsResponse,
    ScanListResponse,
    ScanStatus,
)
from app.services.findings_service import (
    FindingsService,
    parse_scan_status_param,
    parse_scan_type_param,
    parse_severity_param,
)
from app.services.scan_service import ScanService

router = APIRouter(
    prefix="/api/v1/scans",
    tags=["scans"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "",
    response_model=ScanCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_csrf_header)],
)
async def create_scan(
    payload: ScanCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScanCreateResponse:
    service = ScanService(session)
    scan = await service.create_scan(
        user_id=current_user.id,
        request=payload,
        max_files_per_scan=settings.max_files_per_scan,
    )
    return ScanCreateResponse(
        id=scan.id,
        status=cast(ScanStatus, scan.status),
        progress_done=scan.progress_done,
        progress_total=scan.progress_total,
    )


@router.get("", response_model=ScanListResponse)
async def list_scans(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
    upload_id: UUID | None = None,
) -> ScanListResponse:
    if limit < 1 or limit > 100:
        raise InvalidScanRequest("limit must be between 1 and 100")
    if offset < 0:
        raise InvalidScanRequest("offset must be >= 0")
    statuses = parse_scan_status_param(status)
    service = ScanService(session)
    return await service.list_scans(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
        statuses=statuses or None,
        upload_id=upload_id,
    )


@router.get("/{scan_id}", response_model=ScanDetail)
async def get_scan(
    scan_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScanDetail:
    service = ScanService(session)
    return await service.get_scan_detail(scan_id=scan_id, user_id=current_user.id)


@router.get("/{scan_id}/files", response_model=ScanFilesResponse)
async def list_recent_scan_files(
    scan_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 10,
) -> ScanFilesResponse:
    if limit < 1 or limit > 50:
        raise InvalidScanRequest("limit must be between 1 and 50")
    service = ScanService(session)
    return await service.list_recent_scan_files(
        scan_id=scan_id,
        user_id=current_user.id,
        limit=limit,
    )


@router.get("/{scan_id}/findings", response_model=ScanFindingsResponse)
async def list_scan_findings(
    scan_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    severity: str | None = None,
    scan_type: str | None = None,
    file_id: UUID | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> ScanFindingsResponse:
    if limit < 1 or limit > 200:
        raise InvalidScanRequest("limit must be between 1 and 200")
    severities = parse_severity_param(severity)
    scan_types = parse_scan_type_param(scan_type)
    service = FindingsService(session)
    return await service.list_findings(
        scan_id=scan_id,
        user_id=current_user.id,
        severities=severities,
        scan_types=scan_types,
        file_id=file_id,
        cursor=cursor,
        limit=limit,
    )


@router.get("/{scan_id}/export")
async def export_scan_findings(
    scan_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    fmt: str = "json",
    severity: str | None = None,
    scan_type: str | None = None,
    file_id: UUID | None = None,
) -> StreamingResponse:
    if fmt not in {"json", "csv"}:
        raise InvalidScanRequest("fmt must be one of: json, csv")
    severities = parse_severity_param(severity)
    scan_types = parse_scan_type_param(scan_type)
    service = FindingsService(session)
    # Resolve ownership BEFORE constructing the StreamingResponse: raising
    # inside the body generator happens after 200/headers are flushed.
    await service.assert_scan_visible(scan_id=scan_id, user_id=current_user.id)
    if fmt == "csv":
        return StreamingResponse(
            service.stream_export_csv(
                scan_id=scan_id,
                user_id=current_user.id,
                severities=severities,
                scan_types=scan_types,
                file_id=file_id,
            ),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (f'attachment; filename="scan-{scan_id}-findings.csv"'),
            },
        )
    return StreamingResponse(
        service.stream_export_json(
            scan_id=scan_id,
            user_id=current_user.id,
            severities=severities,
            scan_types=scan_types,
            file_id=file_id,
        ),
        media_type="application/json",
        headers={
            "Content-Disposition": (f'attachment; filename="scan-{scan_id}-findings.json"'),
        },
    )


@router.post(
    "/{scan_id}/rerun",
    response_model=ScanCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_csrf_header)],
)
async def rerun_scan(
    scan_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScanCreateResponse:
    """Re-run a previous scan using its original inputs.

    Reconstructs ``file_ids`` + ``scan_types`` + keywords from the source
    scan and creates a brand-new scan via the same path as ``POST /scans``
    (including the Celery enqueue). Returns the *new* scan's id; the source
    row is left untouched.
    """

    service = ScanService(session)
    scan = await service.rerun_scan(
        scan_id=scan_id,
        user_id=current_user.id,
        max_files_per_scan=settings.max_files_per_scan,
    )
    return ScanCreateResponse(
        id=scan.id,
        status=cast(ScanStatus, scan.status),
        progress_done=scan.progress_done,
        progress_total=scan.progress_total,
    )


@router.post(
    "/{scan_id}/cancel",
    response_model=ScanDetail,
    dependencies=[Depends(require_csrf_header)],
)
async def cancel_scan(
    scan_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScanDetail:
    service = ScanService(session)
    return await service.cancel_scan(scan_id=scan_id, user_id=current_user.id)


@router.delete(
    "/{scan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf_header)],
)
async def delete_scan(
    scan_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    service = ScanService(session)
    await service.delete_scan(scan_id=scan_id, user_id=current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
