"""Worker-side SQLAlchemy ORM mirrors of api models.

The api package owns the migrations and is the source of truth for table
shape. The worker re-declares the subset it actually queries (uploads, files)
against a sync ``Base`` so it can use the regular synchronous ORM in tasks
without dragging in the api's async engine, FastAPI, etc.

If you change a column on the api side, mirror it here in the same PR. The
migration round-trip test in ``apps/api/tests/integration/test_migrations.py``
is the regression net for column drift.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import expression

# Same naming convention as api so the ORM doesn't try to recreate constraints
# under different names if Base.metadata is ever inspected.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# ---- Upload -----------------------------------------------------------------

UPLOAD_STATUS_RECEIVED = "received"
UPLOAD_STATUS_EXTRACTING = "extracting"
UPLOAD_STATUS_READY = "ready"
UPLOAD_STATUS_FAILED = "failed"

UPLOAD_KIND_ZIP = "zip"
UPLOAD_KIND_LOOSE = "loose"


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    extract_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    scannable_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
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


# ---- File -------------------------------------------------------------------

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

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
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
