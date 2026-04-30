"""add family id to refresh tokens

Revision ID: 20260430_000002
Revises: 20260429_000001
Create Date: 2026-04-30 00:00:02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260430_000002"
down_revision: str | None = "20260429_000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY token_hash
                    ORDER BY
                        CASE WHEN revoked_at IS NULL THEN 0 ELSE 1 END,
                        created_at DESC,
                        id DESC
                ) AS row_rank
            FROM refresh_tokens
        )
        DELETE FROM refresh_tokens
        WHERE id IN (
            SELECT id
            FROM ranked
            WHERE row_rank > 1
        )
        """
    )
    op.drop_index(op.f("ix_refresh_tokens_token_hash"), table_name="refresh_tokens")
    op.create_unique_constraint(
        op.f("uq_refresh_tokens_token_hash"),
        "refresh_tokens",
        ["token_hash"],
    )
    op.create_index(
        op.f("ix_refresh_tokens_user_id_family_id"),
        "refresh_tokens",
        ["user_id", "family_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_refresh_tokens_user_id_family_id"), table_name="refresh_tokens")
    op.drop_constraint(
        op.f("uq_refresh_tokens_token_hash"),
        "refresh_tokens",
        type_="unique",
    )
    op.create_index(
        op.f("ix_refresh_tokens_token_hash"),
        "refresh_tokens",
        ["token_hash"],
        unique=False,
    )
    op.drop_column("refresh_tokens", "family_id")
