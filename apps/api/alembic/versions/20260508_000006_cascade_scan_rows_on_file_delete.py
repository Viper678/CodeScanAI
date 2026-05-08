"""cascade scan_files / scan_findings on file delete

Revision ID: 20260508_000006
Revises: 20260503_000005
Create Date: 2026-05-08 00:00:00

The original schema (`20260503_000005`) declared `scan_files.file_id` and
`scan_findings.file_id` as plain FKs to `files(id)` with no `ON DELETE`
behavior — defaulting to NO ACTION. That works for a one-shot scan
delete (which removes its dependents via the `scan_id` cascades), but it
*blocks* an upload-level delete: the `uploads → files` cascade tries to
remove file rows that `scan_files`/`scan_findings` still reference, and
PostgreSQL aborts with a foreign-key violation.

Customers can request a hard delete of an upload (data-retention
compliance — see docs/API.md `DELETE /uploads/{id}` and the ScanFiles +
ScanFindings cascade contract noted there). Re-issue both FKs with
`ON DELETE CASCADE` so the upload-level cascade chain works end-to-end.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260508_000006"
down_revision: str | None = "20260503_000005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("fk_scan_files_file_id_files", "scan_files", type_="foreignkey")
    op.create_foreign_key(
        "fk_scan_files_file_id_files",
        "scan_files",
        "files",
        ["file_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("fk_scan_findings_file_id_files", "scan_findings", type_="foreignkey")
    op.create_foreign_key(
        "fk_scan_findings_file_id_files",
        "scan_findings",
        "files",
        ["file_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_scan_findings_file_id_files", "scan_findings", type_="foreignkey")
    op.create_foreign_key(
        "fk_scan_findings_file_id_files",
        "scan_findings",
        "files",
        ["file_id"],
        ["id"],
    )

    op.drop_constraint("fk_scan_files_file_id_files", "scan_files", type_="foreignkey")
    op.create_foreign_key(
        "fk_scan_files_file_id_files",
        "scan_files",
        "files",
        ["file_id"],
        ["id"],
    )
