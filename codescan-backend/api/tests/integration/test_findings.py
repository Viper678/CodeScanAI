"""Integration tests for the findings list + export endpoints (T4.1).

Findings are created by the worker in production, but the API surface only
cares about reading them — so we stage rows directly via the test session
and exercise the router. Each test is self-contained: it registers a user
(or two, for cross-tenant cases), seeds an upload + files + scan + a known
set of findings, then asserts the JSON / CSV response shape.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.uuid7 import uuid7
from app.models.file import File
from app.models.scan import SCAN_STATUS_COMPLETED, Scan
from app.models.scan_finding import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_INFO,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    ScanFinding,
)
from app.models.upload import UPLOAD_KIND_ZIP, UPLOAD_STATUS_READY, Upload
from app.models.user import User


async def _current_user(client: httpx.AsyncClient) -> User:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200, response.text
    body = response.json()
    return User(
        id=UUID(body["id"]),
        email=body["email"],
        password_hash="not-real",  # noqa: S106 - test placeholder
        is_active=True,
    )


def _make_upload(*, user_id: UUID) -> Upload:
    return Upload(
        id=uuid7(),
        user_id=user_id,
        original_name="repo.zip",
        kind=UPLOAD_KIND_ZIP,
        size_bytes=100,
        storage_path=f"/tmp/{uuid4()}",  # noqa: S108 - test placeholder
        status=UPLOAD_STATUS_READY,
        file_count=0,
        scannable_count=0,
    )


def _make_file(*, upload_id: UUID, path: str) -> File:
    return File(
        id=uuid7(),
        upload_id=upload_id,
        path=path,
        name=path.rsplit("/", 1)[-1],
        parent_path="/".join(path.rsplit("/", 1)[:-1]) if "/" in path else "",
        size_bytes=42,
        language="python",
        is_binary=False,
        is_excluded_by_default=False,
        excluded_reason=None,
        sha256="0" * 64,
    )


def _make_scan(*, user_id: UUID, upload_id: UUID) -> Scan:
    return Scan(
        id=uuid7(),
        user_id=user_id,
        upload_id=upload_id,
        name="results-test",
        scan_types=["security", "bugs", "keywords"],
        keywords={},
        status=SCAN_STATUS_COMPLETED,
        progress_done=0,
        progress_total=0,
        model_settings={},
    )


def _make_finding(
    *,
    scan_id: UUID,
    file_id: UUID,
    severity: str,
    scan_type: str = "security",
    title: str = "demo",
    message: str = "msg",
    recommendation: str | None = "fix",
    rule_id: str | None = "R1",
    line_start: int | None = 10,
    line_end: int | None = 12,
    snippet: str | None = "x = 1",
    confidence: Decimal | None = Decimal("0.90"),
    created_at: datetime | None = None,
) -> ScanFinding:
    finding = ScanFinding(
        id=uuid7(),
        scan_id=scan_id,
        file_id=file_id,
        scan_type=scan_type,
        severity=severity,
        title=title,
        message=message,
        recommendation=recommendation,
        line_start=line_start,
        line_end=line_end,
        snippet=snippet,
        rule_id=rule_id,
        confidence=confidence,
    )
    if created_at is not None:
        finding.created_at = created_at
    return finding


async def _seed_scan_with_findings(
    db_session: AsyncSession,
    *,
    user_id: UUID,
    finding_specs: list[dict[str, object]] | None = None,
) -> tuple[Scan, list[File], list[ScanFinding]]:
    upload = _make_upload(user_id=user_id)
    db_session.add(upload)
    await db_session.flush()
    files = [_make_file(upload_id=upload.id, path=f"src/file_{i}.py") for i in range(2)]
    db_session.add_all(files)
    await db_session.flush()
    scan = _make_scan(user_id=user_id, upload_id=upload.id)
    db_session.add(scan)
    await db_session.flush()

    if finding_specs is None:
        finding_specs = [
            {"severity": SEVERITY_HIGH, "scan_type": "security", "file_idx": 0},
            {"severity": SEVERITY_CRITICAL, "scan_type": "security", "file_idx": 0},
            {"severity": SEVERITY_LOW, "scan_type": "bugs", "file_idx": 1},
            {"severity": SEVERITY_MEDIUM, "scan_type": "bugs", "file_idx": 0},
            {"severity": SEVERITY_INFO, "scan_type": "keywords", "file_idx": 1},
        ]
    findings: list[ScanFinding] = []
    for i, spec in enumerate(finding_specs):
        raw_file_idx = spec.get("file_idx", 0)
        assert isinstance(raw_file_idx, int)
        file_idx = raw_file_idx
        findings.append(
            _make_finding(
                scan_id=scan.id,
                file_id=files[file_idx].id,
                severity=str(spec["severity"]),
                scan_type=str(spec.get("scan_type", "security")),
                title=str(spec.get("title", f"finding-{i}")),
                message=str(spec.get("message", f"msg-{i}")),
            )
        )
    db_session.add_all(findings)
    await db_session.commit()
    for finding in findings:
        await db_session.refresh(finding)
    await db_session.refresh(scan)
    for f in files:
        await db_session.refresh(f)
    return scan, files, findings


# ---------------------------------------------------------------------------
# GET /api/v1/scans/{id}/findings
# ---------------------------------------------------------------------------


async def test_findings_happy_path_returns_owned_findings(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _current_user(authed_client)
    scan, files, findings = await _seed_scan_with_findings(db_session, user_id=user.id)

    response = await authed_client.get(f"/api/v1/scans/{scan.id}/findings")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == len(findings)
    assert body["next_cursor"] is None
    assert len(body["items"]) == len(findings)
    # Severity ordering: critical first, info last.
    severities = [item["severity"] for item in body["items"]]
    assert severities[0] == "critical"
    assert severities[-1] == "info"
    # File ref is embedded.
    paths_by_id = {str(f.id): f.path for f in files}
    for item in body["items"]:
        assert item["file"]["path"] == paths_by_id[item["file"]["id"]]
    # Optional fields surface.
    high_item = next(item for item in body["items"] if item["severity"] == "high")
    assert high_item["rule_id"] == "R1"
    assert high_item["recommendation"] == "fix"
    assert high_item["confidence"] == 0.9


async def test_findings_404_for_other_user(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    register_a = await client.post(
        "/api/v1/auth/register",
        json={"email": "owner-find@example.com", "password": "correct-horse"},
    )
    assert register_a.status_code == 201
    user_a = await _current_user(client)
    scan, _files, _findings = await _seed_scan_with_findings(db_session, user_id=user_a.id)

    client.cookies.clear()
    register_b = await client.post(
        "/api/v1/auth/register",
        json={"email": "intruder-find@example.com", "password": "correct-horse"},
    )
    assert register_b.status_code == 201

    response = await client.get(f"/api/v1/scans/{scan.id}/findings")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_findings_auth_required(client: httpx.AsyncClient) -> None:
    client.cookies.clear()
    response = await client.get(f"/api/v1/scans/{uuid4()}/findings")
    assert response.status_code == 401


async def test_findings_filters_compose_severity_scan_type_file_id(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """severity AND scan_type AND file_id all narrow correctly (AND across params)."""

    user = await _current_user(authed_client)
    scan, files, _findings = await _seed_scan_with_findings(db_session, user_id=user.id)

    # severity=high,critical → 2 (both on files[0]).
    r = await authed_client.get(f"/api/v1/scans/{scan.id}/findings?severity=high,critical")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert {item["severity"] for item in body["items"]} == {"high", "critical"}

    # scan_type=bugs → 2 (low on files[1], medium on files[0]).
    r = await authed_client.get(f"/api/v1/scans/{scan.id}/findings?scan_type=bugs")
    body = r.json()
    assert body["total"] == 2
    assert {item["scan_type"] for item in body["items"]} == {"bugs"}

    # file_id=files[0] → 3 (high, critical, medium).
    r = await authed_client.get(f"/api/v1/scans/{scan.id}/findings?file_id={files[0].id}")
    body = r.json()
    assert body["total"] == 3
    assert all(item["file"]["id"] == str(files[0].id) for item in body["items"])

    # AND composition: severity=high AND scan_type=security AND file_id=files[0] → 1.
    r = await authed_client.get(
        f"/api/v1/scans/{scan.id}/findings"
        f"?severity=high&scan_type=security&file_id={files[0].id}"
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["severity"] == "high"
    assert body["items"][0]["scan_type"] == "security"

    # Composition that matches nothing: severity=info AND scan_type=security.
    r = await authed_client.get(
        f"/api/v1/scans/{scan.id}/findings?severity=info&scan_type=security"
    )
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_findings_empty_filters_returns_all(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _current_user(authed_client)
    scan, _files, findings = await _seed_scan_with_findings(db_session, user_id=user.id)

    r = await authed_client.get(f"/api/v1/scans/{scan.id}/findings?severity=&scan_type=")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == len(findings)


async def test_findings_pagination_walks_cursor_to_end(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Limit=2, walk cursor to end. Assert no dupes, no skips, last cursor is null."""

    user = await _current_user(authed_client)
    # Five findings — staggered created_at so the secondary sort key differs.
    upload = _make_upload(user_id=user.id)
    db_session.add(upload)
    await db_session.flush()
    file_row = _make_file(upload_id=upload.id, path="src/x.py")
    db_session.add(file_row)
    await db_session.flush()
    scan = _make_scan(user_id=user.id, upload_id=upload.id)
    db_session.add(scan)
    await db_session.flush()
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
    severities = [SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW, SEVERITY_INFO]
    findings = [
        _make_finding(
            scan_id=scan.id,
            file_id=file_row.id,
            severity=sev,
            title=f"f-{i}",
            created_at=base + timedelta(minutes=i),
        )
        for i, sev in enumerate(severities)
    ]
    db_session.add_all(findings)
    await db_session.commit()

    seen_ids: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        url = f"/api/v1/scans/{scan.id}/findings?limit=2"
        if cursor is not None:
            url += f"&cursor={cursor}"
        r = await authed_client.get(url)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 5
        seen_ids.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        pages += 1
        if cursor is None:
            break
        assert pages < 10, "cursor walk did not terminate"

    # No dupes, no skips → all 5 unique ids in severity order.
    assert len(seen_ids) == 5
    assert len(set(seen_ids)) == 5
    expected_order = [str(f.id) for f in findings]  # critical, high, medium, low, info
    assert seen_ids == expected_order
    # Last page's next_cursor must be null.
    assert cursor is None


async def test_findings_pagination_cursor_respects_filter(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A cursor walked under a filter must keep filtering on subsequent pages."""

    user = await _current_user(authed_client)
    upload = _make_upload(user_id=user.id)
    db_session.add(upload)
    await db_session.flush()
    file_row = _make_file(upload_id=upload.id, path="src/x.py")
    db_session.add(file_row)
    await db_session.flush()
    scan = _make_scan(user_id=user.id, upload_id=upload.id)
    db_session.add(scan)
    await db_session.flush()
    # 3 high (security), 3 low (bugs).
    findings: list[ScanFinding] = []
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
    for i in range(3):
        findings.append(
            _make_finding(
                scan_id=scan.id,
                file_id=file_row.id,
                severity=SEVERITY_HIGH,
                scan_type="security",
                title=f"sec-{i}",
                created_at=base + timedelta(minutes=i),
            )
        )
    for i in range(3):
        findings.append(
            _make_finding(
                scan_id=scan.id,
                file_id=file_row.id,
                severity=SEVERITY_LOW,
                scan_type="bugs",
                title=f"bug-{i}",
                created_at=base + timedelta(minutes=10 + i),
            )
        )
    db_session.add_all(findings)
    await db_session.commit()

    seen: list[str] = []
    cursor: str | None = None
    while True:
        url = f"/api/v1/scans/{scan.id}/findings?limit=2&scan_type=security"
        if cursor:
            url += f"&cursor={cursor}"
        r = await authed_client.get(url)
        body = r.json()
        assert body["total"] == 3
        for item in body["items"]:
            assert item["scan_type"] == "security"
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 3


async def test_findings_rejects_bad_limit(authed_client: httpx.AsyncClient) -> None:
    r = await authed_client.get(f"/api/v1/scans/{uuid4()}/findings?limit=0")
    assert r.status_code == 422
    r = await authed_client.get(f"/api/v1/scans/{uuid4()}/findings?limit=201")
    assert r.status_code == 422


async def test_findings_rejects_bad_severity(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _current_user(authed_client)
    scan, _files, _findings = await _seed_scan_with_findings(db_session, user_id=user.id)
    r = await authed_client.get(f"/api/v1/scans/{scan.id}/findings?severity=high,nope")
    assert r.status_code == 422


async def test_findings_rejects_bad_cursor(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _current_user(authed_client)
    scan, _files, _findings = await _seed_scan_with_findings(db_session, user_id=user.id)
    r = await authed_client.get(f"/api/v1/scans/{scan.id}/findings?cursor=not-a-cursor")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/scans/{id}/export
# ---------------------------------------------------------------------------


async def test_export_json_returns_full_filtered_list(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _current_user(authed_client)
    scan, _files, findings = await _seed_scan_with_findings(db_session, user_id=user.id)

    r = await authed_client.get(f"/api/v1/scans/{scan.id}/export?fmt=json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert (
        r.headers["content-disposition"] == f'attachment; filename="scan-{scan.id}-findings.json"'
    )
    body = r.json()
    assert "items" in body
    assert len(body["items"]) == len(findings)

    # With a filter.
    r = await authed_client.get(f"/api/v1/scans/{scan.id}/export?fmt=json&severity=critical,high")
    body = r.json()
    assert len(body["items"]) == 2
    assert {item["severity"] for item in body["items"]} == {"critical", "high"}


async def test_export_json_404_for_other_user(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    register_a = await client.post(
        "/api/v1/auth/register",
        json={"email": "owner-export@example.com", "password": "correct-horse"},
    )
    assert register_a.status_code == 201
    user_a = await _current_user(client)
    scan, _files, _findings = await _seed_scan_with_findings(db_session, user_id=user_a.id)

    client.cookies.clear()
    register_b = await client.post(
        "/api/v1/auth/register",
        json={"email": "intruder-export@example.com", "password": "correct-horse"},
    )
    assert register_b.status_code == 201

    r = await client.get(f"/api/v1/scans/{scan.id}/export?fmt=json")
    assert r.status_code == 404


async def test_export_csv_round_trip_parsable(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Reading the CSV back via ``csv.DictReader`` must yield one row per finding.

    Tricky payloads (commas, newlines, quotes) must survive round-trip via
    csv's QUOTE_MINIMAL escaping.
    """

    user = await _current_user(authed_client)
    upload = _make_upload(user_id=user.id)
    db_session.add(upload)
    await db_session.flush()
    file_row = _make_file(upload_id=upload.id, path="src/tricky,name.py")
    db_session.add(file_row)
    await db_session.flush()
    scan = _make_scan(user_id=user.id, upload_id=upload.id)
    db_session.add(scan)
    await db_session.flush()
    nasty_message = 'message with, comma\nand a newline and "embedded quotes"'
    findings = [
        _make_finding(
            scan_id=scan.id,
            file_id=file_row.id,
            severity=SEVERITY_HIGH,
            scan_type="security",
            title='title with "quote"',
            message=nasty_message,
            recommendation=None,
            rule_id=None,
        ),
        _make_finding(
            scan_id=scan.id,
            file_id=file_row.id,
            severity=SEVERITY_LOW,
            scan_type="bugs",
            title="plain",
            message="plain msg",
            line_start=None,
            line_end=None,
        ),
    ]
    db_session.add_all(findings)
    await db_session.commit()

    r = await authed_client.get(f"/api/v1/scans/{scan.id}/export?fmt=csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == f'attachment; filename="scan-{scan.id}-findings.csv"'

    reader = csv.DictReader(io.StringIO(r.text))
    rows = list(reader)
    assert len(rows) == 2
    # Row count matches DB.
    # The first row in severity order is high (file path with comma in it).
    assert rows[0]["severity"] == "high"
    assert rows[0]["file_path"] == "src/tricky,name.py"
    assert rows[0]["title"] == 'title with "quote"'
    assert rows[0]["message"] == nasty_message
    assert rows[0]["recommendation"] == ""
    assert rows[0]["rule_id"] == ""
    # Row two: nullable line_start/line_end serialize as empty strings.
    assert rows[1]["severity"] == "low"
    assert rows[1]["line_start"] == ""
    assert rows[1]["line_end"] == ""


async def test_export_csv_filtered(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _current_user(authed_client)
    scan, _files, _findings = await _seed_scan_with_findings(db_session, user_id=user.id)

    r = await authed_client.get(f"/api/v1/scans/{scan.id}/export?fmt=csv&scan_type=bugs")
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 2
    assert {row["scan_type"] for row in rows} == {"bugs"}


async def test_export_rejects_bad_fmt(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _current_user(authed_client)
    scan, _files, _findings = await _seed_scan_with_findings(db_session, user_id=user.id)

    r = await authed_client.get(f"/api/v1/scans/{scan.id}/export?fmt=xml")
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "validation_error"


async def test_export_csv_header_only_when_no_matches(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _current_user(authed_client)
    scan, _files, _findings = await _seed_scan_with_findings(db_session, user_id=user.id)

    r = await authed_client.get(
        f"/api/v1/scans/{scan.id}/export?fmt=csv&severity=info&scan_type=security"
    )
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows == []


async def test_export_json_empty_filtered(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _current_user(authed_client)
    scan, _files, _findings = await _seed_scan_with_findings(db_session, user_id=user.id)

    r = await authed_client.get(f"/api/v1/scans/{scan.id}/export?fmt=json&file_id={uuid4()}")
    assert r.status_code == 200
    body = r.json()
    assert body == {"items": []}


@pytest.mark.parametrize("fmt", ["json", "csv"])
async def test_export_auth_required(client: httpx.AsyncClient, fmt: str) -> None:
    client.cookies.clear()
    r = await client.get(f"/api/v1/scans/{uuid4()}/export?fmt={fmt}")
    assert r.status_code == 401
