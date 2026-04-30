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
    op.create_index(
        op.f("ix_refresh_tokens_user_id_family_id"),
        "refresh_tokens",
        ["user_id", "family_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_refresh_tokens_user_id_family_id"), table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "family_id")
