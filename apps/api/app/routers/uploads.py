"""Upload endpoints.

The router stays intentionally thin — validation and persistence live in
``app.services.upload_service``. Auth is enforced via a router-wide
``Depends(get_current_user)`` and CSRF on the mutating ``POST``.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.deps import get_current_user, require_csrf_header
from app.core.exceptions import InvalidUploadRequest, NotFound
from app.models.upload import UPLOAD_KIND_LOOSE, UPLOAD_KIND_ZIP, Upload
from app.models.user import User
from app.repositories.upload_repo import UploadRepo
from app.schemas.upload import (
    TreeResponse,
    UploadCreateResponse,
    UploadDetail,
    UploadKind,
    UploadListResponse,
    UploadStatus,
)
from app.services.file_content_service import FileContentService
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


@router.get("/{upload_id}/tree", response_model=TreeResponse)
async def get_upload_tree(
    upload_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TreeResponse:
    """Return the materialized tree (flat list) for an upload.

    See docs/API.md §Uploads. Returns ``files=[]`` while the upload is being
    processed; the response includes the upload's current ``status`` so the
    UI can poll without a second request to ``GET /uploads/{id}``.
    """

    service = UploadService(session)
    # NotFound is raised inside the service when the upload is missing or
    # belongs to another user — handler maps it to 404 (never 403).
    return await service.get_tree(upload_id=upload_id, user_id=current_user.id)


@router.get("/{upload_id}/files/{file_id}/content")
async def get_file_content(
    upload_id: UUID,
    file_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StreamingResponse:
    """Stream the raw bytes of a file inside an upload (T4.3).

    Resolves ``upload.extract_path / file.path``, asserts the result
    stays under ``extract_path`` (defense-in-depth — see
    docs/SECURITY.md §4), refuses files larger than
    ``MAX_VIEWABLE_FILE_SIZE_MB`` with 413, and refuses binary content
    with 415. Returns a plain-text body so the frontend's CodeMirror
    component can render it without any further negotiation.

    Auth + ownership: 404 (never 403) for any miss — see
    docs/SECURITY.md §3.
    """

    service = FileContentService(
        session,
        max_size_bytes=settings.max_viewable_file_size_mb * 1024 * 1024,
    )
    content = await service.load_file_for_viewer(
        upload_id=upload_id,
        file_id=file_id,
        user_id=current_user.id,
    )
    return StreamingResponse(
        content.stream,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Length": str(content.size_bytes),
            # Cache-Control: file content is immutable per (upload, file)
            # — once an extract is on disk it doesn't change. We keep this
            # short rather than ``immutable`` because we'd rather a stale
            # disk eviction surface as a fresh 404 than a cached body.
            "Cache-Control": "private, max-age=60",
        },
    )
