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
