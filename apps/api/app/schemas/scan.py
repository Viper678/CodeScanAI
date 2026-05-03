"""Pydantic schemas for scan endpoints.

Mirror the contract documented in docs/API.md §Scans. Cross-field validation
(non-empty ``scan_types``, keywords required when ``"keywords"`` is present,
file count cap, file ownership) lives in the T3.2 service layer — this module
only encodes the shape so the router can decode requests and serialize rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ScanType = Literal["security", "bugs", "keywords"]
ScanStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
Severity = Literal["critical", "high", "medium", "low", "info"]


class KeywordsConfig(BaseModel):
    """Keyword scan configuration as documented in docs/API.md §Scans."""

    model_config = ConfigDict(extra="forbid")

    items: list[str] = Field(default_factory=list)
    case_sensitive: bool = False
    regex: bool = False


class ScanCreateRequest(BaseModel):
    """Request body for ``POST /api/v1/scans``.

    Cross-field rules (non-empty ``scan_types``, keywords required when
    ``"keywords" in scan_types``, ``file_ids`` non-empty + ownership, file
    count cap) are enforced in the T3.2 service layer.
    """

    model_config = ConfigDict(extra="forbid")

    upload_id: UUID
    name: str | None = None
    scan_types: list[ScanType]
    file_ids: list[UUID]
    keywords: KeywordsConfig | None = None
    model_settings: dict[str, Any] = Field(default_factory=dict)


class ScanCreateResponse(BaseModel):
    """Response body for ``POST /api/v1/scans`` (``202 Accepted``)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: ScanStatus
    progress_done: int
    progress_total: int


class ScanSummary(BaseModel):
    """Aggregate counts surfaced on ``GET /api/v1/scans/{id}``."""

    by_severity: dict[Severity, int] = Field(default_factory=dict)
    by_type: dict[ScanType, int] = Field(default_factory=dict)


class ScanDetail(BaseModel):
    """Response body for ``GET /api/v1/scans/{id}``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str | None = None
    upload_id: UUID
    scan_types: list[ScanType]
    status: ScanStatus
    progress_done: int
    progress_total: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    summary: ScanSummary = Field(default_factory=ScanSummary)


class ScanListResponse(BaseModel):
    """Response body for ``GET /api/v1/scans``.

    Mirrors the upload list envelope: ``next_cursor`` is reserved but not yet
    populated (limit/offset is the current pagination strategy).
    """

    items: list[ScanDetail] = Field(default_factory=list)
    next_cursor: str | None = None
    total: int = 0


class FindingFileRef(BaseModel):
    """Compact file reference embedded in finding responses."""

    id: UUID
    path: str


class ScanFindingItem(BaseModel):
    """One row in ``GET /api/v1/scans/{id}/findings``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scan_type: ScanType
    severity: Severity
    title: str
    message: str
    recommendation: str | None = None
    file: FindingFileRef
    line_start: int | None = None
    line_end: int | None = None
    snippet: str | None = None
    rule_id: str | None = None
    confidence: float | None = None


class ScanFindingsResponse(BaseModel):
    """Response body for ``GET /api/v1/scans/{id}/findings``."""

    items: list[ScanFindingItem] = Field(default_factory=list)
    next_cursor: str | None = None
    total: int = 0
