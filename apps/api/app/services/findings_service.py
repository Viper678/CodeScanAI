"""Business logic for the findings list + export endpoints (T4.1).

Lives separately from ``scan_service`` so the scan-lifecycle module stays
focused on create/cancel/delete and isn't coupled to CSV serialization
internals. Both services share the same ownership-to-404 pattern (load the
scan via ``ScanRepo.get_by_id`` first; if missing, raise ``NotFound`` —
never reveal whether the id exists for some other user).

Cursor encoding: a base64-url JSON of ``{rank, created_at, id}``. The repo
orders by ``(severity_rank ASC, created_at DESC, id DESC)`` so we encode
exactly those three values from the last row in the page. Encoded string
is opaque to clients — they round-trip it verbatim.
"""

from __future__ import annotations

import base64
import csv
import io
import json
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidScanRequest, NotFound
from app.repositories.scan_finding_repo import FindingRow, ScanFindingRepo
from app.repositories.scan_repo import ScanRepo
from app.schemas.scan import (
    FindingFileRef,
    ScanFindingItem,
    ScanFindingsResponse,
    ScanType,
    Severity,
)

_VALID_SEVERITIES: frozenset[str] = frozenset({"critical", "high", "medium", "low", "info"})
_VALID_SCAN_TYPES: frozenset[str] = frozenset({"security", "bugs", "keywords"})
_VALID_SCAN_STATUSES: frozenset[str] = frozenset(
    {"pending", "running", "paused", "completed", "failed", "cancelled"}
)

# CSV columns in the order documented in docs/API.md §"GET /scans/{id}/export".
CSV_COLUMNS: tuple[str, ...] = (
    "file_path",
    "line_start",
    "line_end",
    "scan_type",
    "severity",
    "title",
    "message",
    "recommendation",
    "rule_id",
)


def _parse_csv_param(raw: str | None, *, allowed: frozenset[str], param: str) -> list[str]:
    """Split a comma-separated query param and validate each token.

    Empty / missing values become ``[]`` (no filter). An unknown token raises
    422 — the alternative (silently dropping it) makes typos invisible.
    """

    if raw is None or raw == "":
        return []
    tokens = [token.strip() for token in raw.split(",") if token.strip()]
    if not tokens:
        return []
    bad = [token for token in tokens if token not in allowed]
    if bad:
        raise InvalidScanRequest(f"{param} contains invalid value(s): {','.join(sorted(set(bad)))}")
    # De-dup while preserving order — the user's intent is "any of these"
    # and SQL ``IN (...)`` doesn't care about repeats either way.
    seen: dict[str, None] = {}
    for token in tokens:
        seen.setdefault(token, None)
    return list(seen)


def parse_severity_param(raw: str | None) -> list[str]:
    return _parse_csv_param(raw, allowed=_VALID_SEVERITIES, param="severity")


def parse_scan_type_param(raw: str | None) -> list[str]:
    return _parse_csv_param(raw, allowed=_VALID_SCAN_TYPES, param="scan_type")


def parse_scan_status_param(raw: str | None) -> list[str]:
    """Validate the ``?status=`` filter on ``GET /scans``.

    Accepts a comma-separated list of ``ScanStatus`` literals (``pending``,
    ``running``, ``completed``, ``failed``, ``cancelled``). Same shape as the
    findings ``severity`` / ``scan_type`` filters: empty / missing → no filter,
    unknown token → 422.
    """

    return _parse_csv_param(raw, allowed=_VALID_SCAN_STATUSES, param="status")


def encode_cursor(row: FindingRow) -> str:
    payload = {
        "r": row.severity_rank,
        "c": row.created_at.isoformat(),
        "i": str(row.id),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(token: str) -> tuple[int, datetime, UUID]:
    """Reverse of :func:`encode_cursor`. Raises 422 on garbage."""

    # Re-pad — we strip ``=`` on encode for URL-friendliness.
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        rank = int(payload["r"])
        created_at = datetime.fromisoformat(payload["c"])
        finding_id = UUID(payload["i"])
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidScanRequest("cursor is malformed") from exc
    return rank, created_at, finding_id


def _row_to_item(row: FindingRow) -> ScanFindingItem:
    return ScanFindingItem(
        id=row.id,
        scan_type=cast(ScanType, row.scan_type),
        severity=cast(Severity, row.severity),
        title=row.title,
        message=row.message,
        recommendation=row.recommendation,
        file=FindingFileRef(id=row.file_id, path=row.file_path),
        line_start=row.line_start,
        line_end=row.line_end,
        snippet=row.snippet,
        rule_id=row.rule_id,
        confidence=row.confidence,
    )


class FindingsService:
    """Read + export operations against ``scan_findings``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.scans = ScanRepo(session)
        self.findings = ScanFindingRepo(session)

    async def _load_scan_or_404(self, *, scan_id: UUID, user_id: UUID) -> None:
        scan = await self.scans.get_by_id(scan_id, user_id=user_id)
        if scan is None:
            # Same no-enumeration pattern as the rest of the scans router.
            raise NotFound("Scan not found")

    async def assert_scan_visible(self, *, scan_id: UUID, user_id: UUID) -> None:
        """Public alias used by the router before opening a streaming export.

        Raising inside a ``StreamingResponse`` body would happen *after*
        the 200 + headers had already been sent, so the router resolves
        ownership-to-404 synchronously before constructing the response.
        """

        await self._load_scan_or_404(scan_id=scan_id, user_id=user_id)

    async def list_findings(
        self,
        *,
        scan_id: UUID,
        user_id: UUID,
        severities: Sequence[str],
        scan_types: Sequence[str],
        file_id: UUID | None,
        cursor: str | None,
        limit: int,
    ) -> ScanFindingsResponse:
        await self._load_scan_or_404(scan_id=scan_id, user_id=user_id)
        decoded_cursor = decode_cursor(cursor) if cursor else None
        # Fetch one extra row so we can tell whether there's a next page
        # without having to issue a second COUNT(*) for the cursor predicate.
        rows = await self.findings.list_for_scan_paginated(
            scan_id=scan_id,
            user_id=user_id,
            severities=severities or None,
            scan_types=scan_types or None,
            file_id=file_id,
            cursor=decoded_cursor,
            limit=limit + 1,
        )
        next_cursor: str | None = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_cursor = encode_cursor(rows[-1])
        items = [_row_to_item(row) for row in rows]
        total = await self.findings.count_for_scan(
            scan_id=scan_id,
            user_id=user_id,
            severities=severities or None,
            scan_types=scan_types or None,
            file_id=file_id,
        )
        return ScanFindingsResponse(items=items, next_cursor=next_cursor, total=total)

    async def stream_export_json(
        self,
        *,
        scan_id: UUID,
        user_id: UUID,
        severities: Sequence[str],
        scan_types: Sequence[str],
        file_id: UUID | None,
    ) -> AsyncIterator[str]:
        """Yield a single JSON object as text chunks.

        Shape mirrors the list response (minus ``next_cursor``/``total`` —
        an export is, by definition, the whole filtered set). We stream so
        a 50k-finding scan doesn't materialize a giant string in memory.

        The router has already called ``assert_scan_visible`` before opening
        the response, so we don't re-validate here.
        """

        yield '{"items":['
        first = True
        async for row in self.findings.iter_for_export(
            scan_id=scan_id,
            user_id=user_id,
            severities=severities or None,
            scan_types=scan_types or None,
            file_id=file_id,
        ):
            item = _row_to_item(row)
            chunk = item.model_dump_json()
            if first:
                yield chunk
                first = False
            else:
                yield "," + chunk
        yield "]}"

    async def stream_export_csv(
        self,
        *,
        scan_id: UUID,
        user_id: UUID,
        severities: Sequence[str],
        scan_types: Sequence[str],
        file_id: UUID | None,
    ) -> AsyncIterator[str]:
        """Yield CSV text — header row, then one row per finding.

        Uses ``csv.writer`` with ``QUOTE_MINIMAL`` over a ``StringIO`` buffer
        we drain after each row. That keeps the embedded-comma / newline /
        quote escaping correct (we don't try to hand-roll it) while still
        streaming row-at-a-time.

        The router has already called ``assert_scan_visible`` before opening
        the response, so we don't re-validate here.
        """

        buffer = io.StringIO()
        writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(CSV_COLUMNS)
        yield _drain(buffer)
        async for row in self.findings.iter_for_export(
            scan_id=scan_id,
            user_id=user_id,
            severities=severities or None,
            scan_types=scan_types or None,
            file_id=file_id,
        ):
            writer.writerow(
                [
                    row.file_path,
                    "" if row.line_start is None else row.line_start,
                    "" if row.line_end is None else row.line_end,
                    row.scan_type,
                    row.severity,
                    row.title,
                    row.message,
                    "" if row.recommendation is None else row.recommendation,
                    "" if row.rule_id is None else row.rule_id,
                ]
            )
            yield _drain(buffer)


def _drain(buffer: io.StringIO) -> str:
    value = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return value
