"""create uploads table

Revision ID: 20260503_000003
Revises: 20260430_000002
Create Date: 2026-05-03 00:00:03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260503_000003"
down_revision: str | None = "20260430_000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("extract_path", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "scannable_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
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
            name=op.f("fk_uploads_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploads")),
        sa.CheckConstraint(
            "kind IN ('zip', 'loose')",
            name=op.f("ck_uploads_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('received', 'extracting', 'ready', 'failed')",
            name=op.f("ck_uploads_status"),
        ),
    )
    # Raw SQL so we can express the descending order on `created_at`.
    op.execute(
        "CREATE INDEX ix_uploads_user_id_created_at " "ON uploads (user_id, created_at DESC)"
    )


def downgrade() -> None:
    op.drop_index("ix_uploads_user_id_created_at", table_name="uploads")
    op.drop_table("uploads")
