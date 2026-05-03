"""create scans, scan_files, scan_findings tables

Revision ID: 20260503_000005
Revises: 20260503_000004
Create Date: 2026-05-03 00:00:05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260503_000005"
down_revision: str | None = "20260503_000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("upload_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("scan_types", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "keywords",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "progress_done",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "progress_total",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "model",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'gemma-4-31b-it'"),
        ),
        sa.Column(
            "model_settings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_scans_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["uploads.id"],
            name=op.f("fk_scans_upload_id_uploads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scans")),
    )
    # Raw SQL so we can express the descending order on `created_at`.
    op.execute("CREATE INDEX ix_scans_user_id_created_at ON scans (user_id, created_at DESC)")
    op.create_index("ix_scans_upload_id", "scans", ["upload_id"])
    op.create_index("ix_scans_status", "scans", ["status"])

    op.create_table(
        "scan_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["scan_id"],
            ["scans.id"],
            name=op.f("fk_scan_files_scan_id_scans"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name=op.f("fk_scan_files_file_id_files"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_files")),
        sa.UniqueConstraint("scan_id", "file_id", name="uq_scan_files_scan_id_file_id"),
    )
    op.create_index(
        "ix_scan_files_scan_id_status",
        "scan_files",
        ["scan_id", "status"],
    )

    op.create_table(
        "scan_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("rule_id", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"],
            ["scans.id"],
            name=op.f("fk_scan_findings_scan_id_scans"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name=op.f("fk_scan_findings_file_id_files"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_findings")),
    )
    op.create_index(
        "ix_scan_findings_scan_id_severity",
        "scan_findings",
        ["scan_id", "severity"],
    )
    op.create_index(
        "ix_scan_findings_scan_id_scan_type",
        "scan_findings",
        ["scan_id", "scan_type"],
    )
    op.create_index(
        "ix_scan_findings_scan_id_file_id",
        "scan_findings",
        ["scan_id", "file_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_scan_findings_scan_id_file_id", table_name="scan_findings")
    op.drop_index("ix_scan_findings_scan_id_scan_type", table_name="scan_findings")
    op.drop_index("ix_scan_findings_scan_id_severity", table_name="scan_findings")
    op.drop_table("scan_findings")

    op.drop_index("ix_scan_files_scan_id_status", table_name="scan_files")
    op.drop_table("scan_files")

    op.drop_index("ix_scans_status", table_name="scans")
    op.drop_index("ix_scans_upload_id", table_name="scans")
    op.drop_index("ix_scans_user_id_created_at", table_name="scans")
    op.drop_table("scans")
