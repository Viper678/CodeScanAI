"""Pydantic schemas for upload endpoints.

Mirror the contract documented in docs/API.md §Uploads. The API speaks UUIDs
and ISO-8601 timestamps; multipart inputs are parsed at the router and never
fed to a Pydantic model directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

UploadKind = Literal["zip", "loose"]
UploadStatus = Literal["received", "extracting", "ready", "failed"]


class UploadCreateResponse(BaseModel):
    """Response body for ``POST /api/v1/uploads``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: UploadStatus
    kind: UploadKind
    original_name: str
    size_bytes: int


class UploadDetail(BaseModel):
    """Response body for ``GET /api/v1/uploads/{id}``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: UploadStatus
    kind: UploadKind
    original_name: str
    size_bytes: int
    file_count: int
    scannable_count: int
    created_at: datetime
    updated_at: datetime
    error: str | None = None


class UploadListResponse(BaseModel):
    """Response body for ``GET /api/v1/uploads``.

    `next_cursor` is intentionally always ``None`` for now — pagination uses
    ``limit``/``offset`` style for this resource, but the envelope stays
    consistent with docs/API.md §Pagination.
    """

    items: list[UploadDetail] = Field(default_factory=list)
    next_cursor: str | None = None
    total: int = 0


class TreeFile(BaseModel):
    """One materialized row from the ``files`` table.

    Mirrors docs/API.md §Uploads ``GET /uploads/{id}/tree``. The frontend
    builds the visual tree from ``parent_path`` relationships; see
    docs/FILE_HANDLING.md §"Tree presentation contract".
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    path: str
    parent_path: str
    name: str
    size_bytes: int
    language: str | None = None
    is_binary: bool
    is_excluded_by_default: bool
    excluded_reason: str | None = None


class TreeResponse(BaseModel):
    """Response body for ``GET /api/v1/uploads/{id}/tree``.

    ``status`` is included so clients can poll while the worker is still
    extracting (``received``/``extracting``) without a second request to
    ``GET /uploads/{id}``. When ``status != 'ready'`` the ``files`` list is
    empty.
    """

    upload_id: UUID
    root_name: str
    status: UploadStatus
    files: list[TreeFile] = Field(default_factory=list)
