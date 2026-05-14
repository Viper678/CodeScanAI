"""Repository for the scan_findings table.

The ``scan_findings`` table is owned transitively through ``scans.user_id`` —
there's no ``user_id`` column on the row itself. Per docs/SECURITY.md §3
(and the BaseRepo contract), every read is scoped by the caller's
``user_id`` via a JOIN onto ``scans``.

Severity ordering for sorted listings is critical → high → medium → low →
info, expressed via a ``CASE`` expression to mirror the SQL example in
docs/SCHEMA.md.

Filtered list / count / streaming-export methods used by the
``GET /scans/{id}/findings`` and ``GET /scans/{id}/export`` endpoints
share the same WHERE-clause builder so the cursor page, the unfiltered
``total`` count, and the export payload always agree on what "matches".
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Row, Select, case, func, select

from app.models.file import File
from app.models.scan import Scan
from app.models.scan_finding import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_INFO,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    ScanFinding,
)
from app.repositories.base import BaseRepo

_SEVERITY_RANK = case(
    {
        SEVERITY_CRITICAL: 0,
        SEVERITY_HIGH: 1,
        SEVERITY_MEDIUM: 2,
        SEVERITY_LOW: 3,
        SEVERITY_INFO: 4,
    },
    value=ScanFinding.severity,
    else_=99,
)


@dataclass(frozen=True)
class FindingRow:
    """Flattened row joining ``scan_findings`` to ``files``.

    The router serializes this directly; we don't hand back ORM ``ScanFinding``
    instances to the service layer because each row needs ``file.path`` and
    forcing a per-row lazy load would defeat the JOIN.
    """

    id: UUID
    scan_type: str
    severity: str
    title: str
    message: str
    recommendation: str | None
    file_id: UUID
    file_path: str
    line_start: int | None
    line_end: int | None
    snippet: str | None
    rule_id: str | None
    confidence: float | None
    created_at: datetime
    severity_rank: int


def _apply_filters(
    statement: Select[Any],
    *,
    severities: Sequence[str] | None,
    scan_types: Sequence[str] | None,
    file_id: UUID | None,
) -> Select[Any]:
    """Apply ANY-OF filters to a base SELECT — shared by list/count/export.

    Empty sequences are treated like ``None`` (no filter) — that matches the
    "param omitted" semantics; the router never passes empty lists, but
    defending here keeps the contract obvious.
    """

    if severities:
        statement = statement.where(ScanFinding.severity.in_(list(severities)))
    if scan_types:
        statement = statement.where(ScanFinding.scan_type.in_(list(scan_types)))
    if file_id is not None:
        statement = statement.where(ScanFinding.file_id == file_id)
    return statement


# Sort keys returned alongside each row so we can build a stable cursor.
# Ordering is (severity_rank ASC, created_at DESC, id DESC):
#  - severity_rank ASC puts critical before info (matches the rank table)
#  - created_at DESC puts newer findings first within a severity bucket
#  - id DESC tie-breaks (and uuid7 ids embed a timestamp, so it's monotonic
#    enough to keep the cursor stable even if two rows share a created_at)
_SEVERITY_RANK_LABEL = "_severity_rank"


def _select_row_columns() -> Select[Any]:
    return select(
        ScanFinding.id,
        ScanFinding.scan_type,
        ScanFinding.severity,
        ScanFinding.title,
        ScanFinding.message,
        ScanFinding.recommendation,
        ScanFinding.file_id,
        File.path,
        ScanFinding.line_start,
        ScanFinding.line_end,
        ScanFinding.snippet,
        ScanFinding.rule_id,
        ScanFinding.confidence,
        ScanFinding.created_at,
        _SEVERITY_RANK.label(_SEVERITY_RANK_LABEL),
    )


def _row_from_record(record: Row[Any]) -> FindingRow:
    # ``record`` is a SQLAlchemy Row matching ``_select_row_columns`` shape;
    # we narrow each cell with ``cast`` so mypy --strict accepts the
    # FindingRow construction without per-cell ``Any`` leakage downstream.
    confidence_raw = record[12]
    return FindingRow(
        id=cast(UUID, record[0]),
        scan_type=cast(str, record[1]),
        severity=cast(str, record[2]),
        title=cast(str, record[3]),
        message=cast(str, record[4]),
        recommendation=cast("str | None", record[5]),
        file_id=cast(UUID, record[6]),
        file_path=cast(str, record[7]),
        line_start=cast("int | None", record[8]),
        line_end=cast("int | None", record[9]),
        snippet=cast("str | None", record[10]),
        rule_id=cast("str | None", record[11]),
        confidence=float(confidence_raw) if confidence_raw is not None else None,
        created_at=cast(datetime, record[13]),
        severity_rank=int(cast(int, record[14])),
    )


class ScanFindingRepo(BaseRepo[ScanFinding]):
    async def get_by_id(self, id: UUID, *, user_id: UUID) -> ScanFinding | None:
        result = await self.session.execute(
            select(ScanFinding)
            .join(Scan, Scan.id == ScanFinding.scan_id)
            .where(ScanFinding.id == id, Scan.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[ScanFinding]:
        # Cross-scan listing is provided for symmetry with BaseRepo; routers
        # use ``list_for_scan`` instead. Capped by ``limit``. Severity ordering
        # uses ``_SEVERITY_RANK`` to stay consistent with ``list_for_scan`` —
        # raw column ordering would be alphabetical (info < low < medium ...),
        # which is not the documented severity priority.
        result = await self.session.execute(
            select(ScanFinding)
            .join(Scan, Scan.id == ScanFinding.scan_id)
            .where(Scan.user_id == user_id)
            .order_by(ScanFinding.scan_id, _SEVERITY_RANK, ScanFinding.file_id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_for_scan(
        self,
        *,
        scan_id: UUID,
        user_id: UUID,
        severity: str | None = None,
        scan_type: str | None = None,
        file_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ScanFinding]:
        statement = (
            select(ScanFinding)
            .join(Scan, Scan.id == ScanFinding.scan_id)
            .where(ScanFinding.scan_id == scan_id, Scan.user_id == user_id)
        )
        if severity is not None:
            statement = statement.where(ScanFinding.severity == severity)
        if scan_type is not None:
            statement = statement.where(ScanFinding.scan_type == scan_type)
        if file_id is not None:
            statement = statement.where(ScanFinding.file_id == file_id)
        statement = (
            statement.order_by(_SEVERITY_RANK, ScanFinding.file_id, ScanFinding.line_start)
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # T4.1: filtered + paginated listing for the findings endpoint.
    # ------------------------------------------------------------------

    def _scoped_select(self, *, scan_id: UUID, user_id: UUID) -> Select[Any]:
        return (
            _select_row_columns()
            .join(Scan, Scan.id == ScanFinding.scan_id)
            .join(File, File.id == ScanFinding.file_id)
            .where(ScanFinding.scan_id == scan_id, Scan.user_id == user_id)
        )

    async def list_for_scan_paginated(
        self,
        *,
        scan_id: UUID,
        user_id: UUID,
        severities: Sequence[str] | None = None,
        scan_types: Sequence[str] | None = None,
        file_id: UUID | None = None,
        cursor: tuple[int, datetime, UUID] | None = None,
        limit: int,
    ) -> list[FindingRow]:
        """Return up to ``limit`` rows after ``cursor`` for the ordered set.

        Ordering is ``(severity_rank ASC, created_at DESC, id DESC)`` — the
        cursor is the last row's ``(severity_rank, created_at, id)`` tuple,
        and we ask for rows strictly after it under that lexicographic order.

        The "after cursor" predicate is the standard tuple comparison expanded
        manually because Postgres doesn't understand mixed ASC/DESC tuple
        comparisons cleanly:

            severity_rank > c_rank
            OR (severity_rank = c_rank AND created_at < c_created)
            OR (severity_rank = c_rank AND created_at = c_created AND id < c_id)
        """

        statement = self._scoped_select(scan_id=scan_id, user_id=user_id)
        statement = _apply_filters(
            statement,
            severities=severities,
            scan_types=scan_types,
            file_id=file_id,
        )
        if cursor is not None:
            c_rank, c_created, c_id = cursor
            # NB: comparisons go ``column OP literal`` so mypy sees each clause
            # as ``ColumnElement[bool]`` (the ``|`` / ``&`` overloads need that
            # — putting the literal on the left collapses the operand to
            # Python ``bool`` and breaks the operator). Ruff's SIM300 (Yoda
            # condition) flags this as "literal on the right"; the rule is
            # meaningless for SQLAlchemy expressions, so we silence it locally.
            statement = statement.where(
                (_SEVERITY_RANK > c_rank)  # noqa: SIM300
                | (
                    (_SEVERITY_RANK == c_rank)  # noqa: SIM300
                    & (ScanFinding.created_at < c_created)
                )
                | (
                    (_SEVERITY_RANK == c_rank)  # noqa: SIM300
                    & (ScanFinding.created_at == c_created)
                    & (ScanFinding.id < c_id)
                )
            )
        statement = statement.order_by(
            _SEVERITY_RANK.asc(),
            ScanFinding.created_at.desc(),
            ScanFinding.id.desc(),
        ).limit(limit)
        result = await self.session.execute(statement)
        return [_row_from_record(record) for record in result.all()]

    async def count_for_scan(
        self,
        *,
        scan_id: UUID,
        user_id: UUID,
        severities: Sequence[str] | None = None,
        scan_types: Sequence[str] | None = None,
        file_id: UUID | None = None,
    ) -> int:
        """Total rows matching the filter set (cursor-independent).

        Used by the findings endpoint to surface ``total`` so the UI can show
        "showing 47 of 312" without paging through everything.
        """

        statement = (
            select(func.count())
            .select_from(ScanFinding)
            .join(Scan, Scan.id == ScanFinding.scan_id)
            .where(ScanFinding.scan_id == scan_id, Scan.user_id == user_id)
        )
        statement = _apply_filters(
            statement,
            severities=severities,
            scan_types=scan_types,
            file_id=file_id,
        )
        result = await self.session.execute(statement)
        return int(result.scalar_one())

    async def iter_for_export(
        self,
        *,
        scan_id: UUID,
        user_id: UUID,
        severities: Sequence[str] | None = None,
        scan_types: Sequence[str] | None = None,
        file_id: UUID | None = None,
        chunk_size: int = 500,
    ) -> AsyncIterator[FindingRow]:
        """Yield every matching finding for streaming export.

        Uses ``yield_per`` so the underlying driver fetches in chunks rather
        than buffering the whole result set — important for scans with
        thousands of findings.
        """

        statement = self._scoped_select(scan_id=scan_id, user_id=user_id)
        statement = _apply_filters(
            statement,
            severities=severities,
            scan_types=scan_types,
            file_id=file_id,
        )
        statement = statement.order_by(
            _SEVERITY_RANK.asc(),
            ScanFinding.created_at.desc(),
            ScanFinding.id.desc(),
        ).execution_options(yield_per=chunk_size)
        result = await self.session.stream(statement)
        async for record in result:
            yield _row_from_record(record)
