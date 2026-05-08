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
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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


# ---- Scan -------------------------------------------------------------------

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

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    # FK to users.id exists in the migration; we omit ForeignKey(...) here so
    # the worker doesn't need a Users ORM mirror just to satisfy reflection.
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
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
        Integer, nullable=False, default=0, server_default=text("0")
    )
    progress_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'gemma-4-31b-it'")
    )
    model_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
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
            "ix_scans_user_id_created_at",
            "user_id",
            expression.desc("created_at"),
        ),
        Index("ix_scans_upload_id", "upload_id"),
        Index("ix_scans_status", "status"),
    )


# ---- ScanFile ---------------------------------------------------------------

SCAN_FILE_STATUS_PENDING = "pending"
SCAN_FILE_STATUS_RUNNING = "running"
SCAN_FILE_STATUS_DONE = "done"
SCAN_FILE_STATUS_FAILED = "failed"
SCAN_FILE_STATUS_SKIPPED = "skipped"


class ScanFile(Base):
    __tablename__ = "scan_files"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
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


# ---- ScanFinding ------------------------------------------------------------

SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"
SEVERITY_INFO = "info"


class ScanFinding(Base):
    __tablename__ = "scan_findings"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
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
    # column name but expose it as `meta` on the model (matches api side).
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_scan_findings_scan_id_severity", "scan_id", "severity"),
        Index("ix_scan_findings_scan_id_scan_type", "scan_id", "scan_type"),
        Index("ix_scan_findings_scan_id_file_id", "scan_id", "file_id"),
    )
