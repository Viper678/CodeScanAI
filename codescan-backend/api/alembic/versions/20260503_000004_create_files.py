"""create files table

Revision ID: 20260503_000004
Revises: 20260503_000003
Create Date: 2026-05-03 00:00:04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260503_000004"
down_revision: str | None = "20260503_000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("upload_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("parent_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("is_binary", sa.Boolean(), nullable=False),
        sa.Column("is_excluded_by_default", sa.Boolean(), nullable=False),
        sa.Column("excluded_reason", sa.Text(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["uploads.id"],
            name=op.f("fk_files_upload_id_uploads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_files")),
        sa.UniqueConstraint("upload_id", "path", name="uq_files_upload_id_path"),
    )
    op.create_index(
        "ix_files_upload_id_path",
        "files",
        ["upload_id", "path"],
    )
    op.create_index(
        "ix_files_upload_id_parent_path",
        "files",
        ["upload_id", "parent_path"],
    )


def downgrade() -> None:
    op.drop_index("ix_files_upload_id_parent_path", table_name="files")
    op.drop_index("ix_files_upload_id_path", table_name="files")
    op.drop_table("files")
