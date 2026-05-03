"""ScanFile persistence model.

Join row between a scan and a file with per-file lifecycle tracking so we can
resume / retry a scan without rescanning everything. The full schema lives in
docs/SCHEMA.md §scan_files and the lifecycle in §"Status state machines".
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.uuid7 import uuid7

# Per-file scan status — TEXT to mirror SCHEMA.md and avoid Postgres ENUM churn.
SCAN_FILE_STATUS_PENDING = "pending"
SCAN_FILE_STATUS_RUNNING = "running"
SCAN_FILE_STATUS_DONE = "done"
SCAN_FILE_STATUS_FAILED = "failed"
SCAN_FILE_STATUS_SKIPPED = "skipped"


class ScanFile(Base):
    __tablename__ = "scan_files"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    scan_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scans.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("files.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("scan_id", "file_id", name="uq_scan_files_scan_id_file_id"),
        Index("ix_scan_files_scan_id_status", "scan_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"ScanFile(id={self.id!s}, scan_id={self.scan_id!s}, "
            f"file_id={self.file_id!s}, status={self.status!r})"
        )
