"""File persistence model.

One row per regular file inside an upload after extraction (kind=zip) or
walking (kind=loose). Directories are not stored — they're inferred from
``parent_path`` on read. The full schema lives in docs/SCHEMA.md §files and
the classification rules in docs/FILE_HANDLING.md.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.uuid7 import uuid7

# excluded_reason enum (TEXT) — must mirror docs/FILE_HANDLING.md table.
EXCLUDED_REASON_OVERSIZE = "oversize"
EXCLUDED_REASON_BINARY = "binary"
EXCLUDED_REASON_VENDOR_DIR = "vendor_dir"
EXCLUDED_REASON_VCS_DIR = "vcs_dir"
EXCLUDED_REASON_IDE_DIR = "ide_dir"
EXCLUDED_REASON_LOCKFILE = "lockfile"
EXCLUDED_REASON_BUILD_ARTIFACT = "build_artifact"
EXCLUDED_REASON_IMAGE = "image"
EXCLUDED_REASON_FONT = "font"
EXCLUDED_REASON_MEDIA = "media"
EXCLUDED_REASON_ARCHIVE = "archive"
EXCLUDED_REASON_DOTFILE = "dotfile"
EXCLUDED_REASON_UNKNOWN_EXT = "unknown_ext"


class File(Base):
    __tablename__ = "files"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    upload_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("uploads.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_binary: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_excluded_by_default: Mapped[bool] = mapped_column(Boolean, nullable=False)
    excluded_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("upload_id", "path", name="uq_files_upload_id_path"),
        Index("ix_files_upload_id_path", "upload_id", "path"),
        Index("ix_files_upload_id_parent_path", "upload_id", "parent_path"),
    )

    def __repr__(self) -> str:
        return (
            f"File(id={self.id!s}, upload_id={self.upload_id!s}, "
            f"path={self.path!r}, language={self.language!r})"
        )
