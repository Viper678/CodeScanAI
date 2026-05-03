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
    ScanListResponse,
    ScanStatus,
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
    if status is not None and status not in {
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
    }:
        raise InvalidScanRequest(
            "status must be one of: pending, running, completed, failed, cancelled"
        )
    service = ScanService(session)
    return await service.list_scans(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
        status=status,
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
