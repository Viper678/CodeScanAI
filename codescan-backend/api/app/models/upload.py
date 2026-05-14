"""Upload persistence model.

Tracks the lifecycle of an uploaded artifact (zip or loose-files) from
``received`` through ``ready``/``failed``. The full schema lives in
docs/SCHEMA.md §uploads.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import expression

from app.core.db import Base
from app.core.uuid7 import uuid7

# Status / kind enum literals — stored as TEXT to match SCHEMA.md and to avoid
# Postgres ENUM migrations for what may evolve.
UPLOAD_STATUS_RECEIVED = "received"
UPLOAD_STATUS_EXTRACTING = "extracting"
UPLOAD_STATUS_READY = "ready"
UPLOAD_STATUS_FAILED = "failed"

UPLOAD_KIND_ZIP = "zip"
UPLOAD_KIND_LOOSE = "loose"


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    extract_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    scannable_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
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
            "ix_uploads_user_id_created_at",
            "user_id",
            expression.desc("created_at"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"Upload(id={self.id!s}, user_id={self.user_id!s}, "
            f"kind={self.kind!r}, status={self.status!r})"
        )
