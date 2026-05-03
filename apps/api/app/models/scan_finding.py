"""ScanFinding persistence model.

One row per finding produced by a scan, keyed to a specific file. The full
schema lives in docs/SCHEMA.md §scan_findings; severity ordering for sorted
listings is critical → high → medium → low → info.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.uuid7 import uuid7

# Severity enum literals — TEXT to mirror SCHEMA.md and avoid Postgres ENUM churn.
SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"
SEVERITY_INFO = "info"


class ScanFinding(Base):
    __tablename__ = "scan_findings"

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
    scan_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    # `metadata` is reserved on the SQLAlchemy declarative base — keep the DB
    # column name but expose it as `meta` on the model.
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_scan_findings_scan_id_severity", "scan_id", "severity"),
        Index("ix_scan_findings_scan_id_scan_type", "scan_id", "scan_type"),
        Index("ix_scan_findings_scan_id_file_id", "scan_id", "file_id"),
    )

    def __repr__(self) -> str:
        return (
            f"ScanFinding(id={self.id!s}, scan_id={self.scan_id!s}, "
            f"file_id={self.file_id!s}, severity={self.severity!r}, "
            f"scan_type={self.scan_type!r})"
        )
