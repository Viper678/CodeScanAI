"""Upload endpoints.

The router stays intentionally thin — validation and persistence live in
``app.services.upload_service``. Auth is enforced via a router-wide
``Depends(get_current_user)`` and CSRF on the mutating ``POST``.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_user, require_csrf_header
from app.core.exceptions import InvalidUploadRequest, NotFound
from app.models.upload import UPLOAD_KIND_LOOSE, UPLOAD_KIND_ZIP, Upload
from app.models.user import User
from app.repositories.upload_repo import UploadRepo
from app.schemas.upload import (
    UploadCreateResponse,
    UploadDetail,
    UploadKind,
    UploadListResponse,
    UploadStatus,
)
from app.services.upload_service import UploadService

router = APIRouter(
    prefix="/api/v1/uploads",
    tags=["uploads"],
    dependencies=[Depends(get_current_user)],
)


def _create_response(upload: Upload) -> UploadCreateResponse:
    return UploadCreateResponse(
        id=upload.id,
        status=cast(UploadStatus, upload.status),
        kind=cast(UploadKind, upload.kind),
        original_name=upload.original_name,
        size_bytes=upload.size_bytes,
    )


def _detail_response(upload: Upload) -> UploadDetail:
    return UploadDetail(
        id=upload.id,
        status=cast(UploadStatus, upload.status),
        kind=cast(UploadKind, upload.kind),
        original_name=upload.original_name,
        size_bytes=upload.size_bytes,
        file_count=upload.file_count,
        scannable_count=upload.scannable_count,
        created_at=upload.created_at,
        updated_at=upload.updated_at,
        error=upload.error,
    )


@router.post(
    "",
    response_model=UploadCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_csrf_header)],
)
async def create_upload(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    kind: Annotated[str, Form()],
    file: Annotated[list[UploadFile], File(description="One zip OR one-or-more loose files")],
) -> UploadCreateResponse:
    if kind not in {UPLOAD_KIND_ZIP, UPLOAD_KIND_LOOSE}:
        raise InvalidUploadRequest(f"kind must be one of: zip, loose (got {kind!r})")
    if not file:
        raise InvalidUploadRequest("At least one file is required")

    service = UploadService(session)
    if kind == UPLOAD_KIND_ZIP:
        if len(file) != 1:
            raise InvalidUploadRequest("kind=zip requires exactly one file")
        upload = await service.create_zip_upload(
            user_id=current_user.id,
            upload_file=file[0],
        )
    else:
        upload = await service.create_loose_upload(
            user_id=current_user.id,
            upload_files=list(file),
        )
    return _create_response(upload)


@router.get("", response_model=UploadListResponse)
async def list_uploads(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 20,
    offset: int = 0,
) -> UploadListResponse:
    if limit < 1 or limit > 100:
        raise InvalidUploadRequest("limit must be between 1 and 100")
    if offset < 0:
        raise InvalidUploadRequest("offset must be >= 0")
    repo = UploadRepo(session)
    rows = await repo.list_for_user(user_id=current_user.id, limit=limit, offset=offset)
    total = await repo.count_for_user(user_id=current_user.id)
    return UploadListResponse(
        items=[_detail_response(upload) for upload in rows],
        next_cursor=None,
        total=total,
    )


@router.get("/{upload_id}", response_model=UploadDetail)
async def get_upload(
    upload_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UploadDetail:
    repo = UploadRepo(session)
    upload = await repo.get_by_id(upload_id, user_id=current_user.id)
    if upload is None:
        # Intentionally 404 (not 403) to avoid leaking the existence of an
        # upload owned by someone else. See docs/SECURITY.md §3.
        raise NotFound("Upload not found")
    return _detail_response(upload)
