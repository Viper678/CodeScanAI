"""Scan persistence model.

Tracks a single scan run against an upload — its requested scan types,
keyword config, lifecycle status, and progress counters. Per-file rows live
in ``scan_files`` and produced rows in ``scan_findings``. The full schema
lives in docs/SCHEMA.md §scans and the lifecycle in §"Status state machines".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import expression

from app.core.db import Base
from app.core.uuid7 import uuid7

# Status / scan_type enum literals — stored as TEXT to match SCHEMA.md and
# avoid Postgres ENUM migrations for what may evolve.
SCAN_STATUS_PENDING = "pending"
SCAN_STATUS_RUNNING = "running"
SCAN_STATUS_COMPLETED = "completed"
SCAN_STATUS_FAILED = "failed"
SCAN_STATUS_CANCELLED = "cancelled"

SCAN_TYPE_SECURITY = "security"
SCAN_TYPE_BUGS = "bugs"
SCAN_TYPE_KEYWORDS = "keywords"


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    upload_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("uploads.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    scan_types: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    keywords: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    progress_done: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    progress_total: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'gemma-4-31b-it'"),
    )
    model_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_scans_user_id_created_at",
            "user_id",
            expression.desc("created_at"),
        ),
        Index("ix_scans_upload_id", "upload_id"),
        Index("ix_scans_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"Scan(id={self.id!s}, user_id={self.user_id!s}, "
            f"upload_id={self.upload_id!s}, status={self.status!r})"
        )
