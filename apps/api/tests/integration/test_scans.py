"""Integration tests for the scans router (T3.2).

Scans depend on a prepared upload with files. Rather than driving the worker
pipeline, we stage the parent ``Upload`` and ``File`` rows via the test
session and POST against ``/api/v1/scans`` directly.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.uuid7 import uuid7
from app.models.file import File
from app.models.scan import (
    SCAN_STATUS_CANCELLED,
    SCAN_STATUS_COMPLETED,
    SCAN_STATUS_PENDING,
    SCAN_STATUS_RUNNING,
    Scan,
)
from app.models.scan_file import ScanFile
from app.models.upload import UPLOAD_KIND_ZIP, UPLOAD_STATUS_READY, Upload
from app.models.user import User

CSRF_HEADERS = {"X-Requested-With": "codescan"}


@pytest.fixture
def mock_enqueue_run_scan() -> Iterator[MagicMock]:
    """Replace the broker enqueue with a mock — tests must never hit Redis."""

    with patch(
        "app.services.scan_service.enqueue_run_scan",
        new=MagicMock(),
    ) as mocked:
        yield mocked


async def _current_user(client: httpx.AsyncClient) -> User:
    """Resolve the logged-in user via /me; returns a User with id only."""

    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200, response.text
    body = response.json()
    return User(
        id=UUID(body["id"]),
        email=body["email"],
        password_hash="not-real",  # noqa: S106 - integration test placeholder
        is_active=True,
    )


def _make_upload(*, user_id: UUID, original_name: str = "repo.zip") -> Upload:
    return Upload(
        id=uuid7(),
        user_id=user_id,
        original_name=original_name,
        kind=UPLOAD_KIND_ZIP,
        size_bytes=100,
        storage_path=f"/tmp/{uuid4()}",  # noqa: S108 - integration test placeholder
        status=UPLOAD_STATUS_READY,
        file_count=0,
        scannable_count=0,
    )


def _make_file(
    *,
    upload_id: UUID,
    path: str,
    name: str | None = None,
    parent_path: str = "",
) -> File:
    return File(
        id=uuid7(),
        upload_id=upload_id,
        path=path,
        name=name or path.rsplit("/", 1)[-1],
        parent_path=parent_path,
        size_bytes=42,
        language="python",
        is_binary=False,
        is_excluded_by_default=False,
        excluded_reason=None,
        sha256="deadbeef",
    )


async def _seed_upload_with_files(
    db_session: AsyncSession,
    *,
    user_id: UUID,
    file_count: int = 3,
) -> tuple[Upload, list[File]]:
    upload = _make_upload(user_id=user_id)
    db_session.add(upload)
    await db_session.flush()
    files = [_make_file(upload_id=upload.id, path=f"src/file_{i}.py") for i in range(file_count)]
    db_session.add_all(files)
    await db_session.commit()
    for f in files:
        await db_session.refresh(f)
    await db_session.refresh(upload)
    return upload, files


def _scan_payload(
    *,
    upload_id: UUID,
    file_ids: list[UUID],
    scan_types: list[str] | None = None,
    keywords: dict[str, Any] | None = None,
    name: str | None = "first pass",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "upload_id": str(upload_id),
        "scan_types": scan_types if scan_types is not None else ["security", "bugs"],
        "file_ids": [str(fid) for fid in file_ids],
    }
    if name is not None:
        body["name"] = name
    if keywords is not None:
        body["keywords"] = keywords
    return body


# ---------------------------------------------------------------------------
# POST /api/v1/scans
# ---------------------------------------------------------------------------


async def test_post_scan_happy_path(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_enqueue_run_scan: MagicMock,
) -> None:
    user = await _current_user(authed_client)
    upload, files = await _seed_upload_with_files(db_session, user_id=user.id)

    response = await authed_client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(
            upload_id=upload.id,
            file_ids=[f.id for f in files],
            scan_types=["security", "bugs", "keywords"],
            keywords={"items": ["TODO", "FIXME"], "case_sensitive": False, "regex": False},
        ),
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    scan_id = UUID(payload["id"])
    assert payload["status"] == SCAN_STATUS_PENDING
    assert payload["progress_done"] == 0
    assert payload["progress_total"] == len(files)

    await db_session.commit()
    row = await db_session.scalar(select(Scan).where(Scan.id == scan_id))
    assert row is not None
    assert row.user_id == user.id
    assert row.upload_id == upload.id
    assert list(row.scan_types) == ["security", "bugs", "keywords"]
    assert row.keywords == {
        "items": ["TODO", "FIXME"],
        "case_sensitive": False,
        "regex": False,
    }
    assert row.status == SCAN_STATUS_PENDING
    assert row.progress_total == len(files)

    scan_file_rows = (
        await db_session.scalars(select(ScanFile).where(ScanFile.scan_id == scan_id))
    ).all()
    assert len(scan_file_rows) == len(files)
    assert {sf.file_id for sf in scan_file_rows} == {f.id for f in files}
    assert all(sf.status == "pending" for sf in scan_file_rows)

    mock_enqueue_run_scan.assert_called_once_with(scan_id)


async def test_post_scan_rejects_other_users_file_ids(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_enqueue_run_scan: MagicMock,
) -> None:
    """User B owns ``upload_id`` but supplies user A's file_ids — 403.

    This is the cross-upload variant the AC calls out: the upload check
    succeeds (B does own that upload), then the file ownership check trips
    because the file_ids belong to a different upload that B doesn't own.
    Documented in the brief: file_id-from-foreign-upload should also 403.
    """

    # User A — owns the files we'll try to smuggle in.
    register_a = await client.post(
        "/api/v1/auth/register",
        json={"email": "owner-scan@example.com", "password": "correct-horse"},
    )
    assert register_a.status_code == 201
    user_a = await _current_user(client)
    a_upload, a_files = await _seed_upload_with_files(db_session, user_id=user_a.id)

    # User B — owns their own upload, will reference A's file_ids in the body.
    client.cookies.clear()
    register_b = await client.post(
        "/api/v1/auth/register",
        json={"email": "intruder-scan@example.com", "password": "correct-horse"},
    )
    assert register_b.status_code == 201
    user_b = await _current_user(client)
    b_upload, _b_files = await _seed_upload_with_files(db_session, user_id=user_b.id)

    response = await client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(
            upload_id=b_upload.id,
            file_ids=[f.id for f in a_files],
        ),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    mock_enqueue_run_scan.assert_not_called()


async def test_post_scan_rejects_file_ids_from_different_upload(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_enqueue_run_scan: MagicMock,
) -> None:
    """Same user owns both uploads, but file_ids cross uploads → 403."""

    user = await _current_user(authed_client)
    upload_a, files_a = await _seed_upload_with_files(db_session, user_id=user.id)
    upload_b, _files_b = await _seed_upload_with_files(db_session, user_id=user.id)

    response = await authed_client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(
            upload_id=upload_b.id,
            file_ids=[f.id for f in files_a],
        ),
    )

    assert response.status_code == 403
    mock_enqueue_run_scan.assert_not_called()


async def test_post_scan_rejects_unknown_upload(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_enqueue_run_scan: MagicMock,
) -> None:
    user = await _current_user(authed_client)
    _upload, files = await _seed_upload_with_files(db_session, user_id=user.id)

    response = await authed_client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(
            upload_id=uuid4(),
            file_ids=[f.id for f in files],
        ),
    )

    # 404, not 403 — same no-enumeration pattern as GET /uploads/{id}.
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    mock_enqueue_run_scan.assert_not_called()


async def test_post_scan_rejects_empty_scan_types(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_enqueue_run_scan: MagicMock,
) -> None:
    user = await _current_user(authed_client)
    upload, files = await _seed_upload_with_files(db_session, user_id=user.id)

    response = await authed_client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(
            upload_id=upload.id,
            file_ids=[f.id for f in files],
            scan_types=[],
        ),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    mock_enqueue_run_scan.assert_not_called()


async def test_post_scan_rejects_missing_keywords_when_keyword_type_present(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_enqueue_run_scan: MagicMock,
) -> None:
    user = await _current_user(authed_client)
    upload, files = await _seed_upload_with_files(db_session, user_id=user.id)

    response = await authed_client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(
            upload_id=upload.id,
            file_ids=[f.id for f in files],
            scan_types=["keywords"],
        ),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    mock_enqueue_run_scan.assert_not_called()


async def test_post_scan_rejects_empty_keywords_items(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_enqueue_run_scan: MagicMock,
) -> None:
    user = await _current_user(authed_client)
    upload, files = await _seed_upload_with_files(db_session, user_id=user.id)

    response = await authed_client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(
            upload_id=upload.id,
            file_ids=[f.id for f in files],
            scan_types=["keywords"],
            keywords={"items": [], "case_sensitive": False, "regex": False},
        ),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_post_scan_rejects_empty_file_ids(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_enqueue_run_scan: MagicMock,
) -> None:
    user = await _current_user(authed_client)
    upload, _files = await _seed_upload_with_files(db_session, user_id=user.id)

    response = await authed_client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(upload_id=upload.id, file_ids=[]),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_post_scan_rejects_over_cap_file_ids(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_enqueue_run_scan: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "max_files_per_scan", 2)

    user = await _current_user(authed_client)
    upload, files = await _seed_upload_with_files(db_session, user_id=user.id, file_count=3)

    response = await authed_client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(upload_id=upload.id, file_ids=[f.id for f in files]),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "max 2" in body["error"]["message"]
    mock_enqueue_run_scan.assert_not_called()


async def test_post_scan_marks_failed_when_broker_unavailable(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _current_user(authed_client)
    upload, files = await _seed_upload_with_files(db_session, user_id=user.id)
    failing_enqueue = MagicMock(side_effect=RuntimeError("broker down"))

    with patch(
        "app.services.scan_service.enqueue_run_scan",
        new=failing_enqueue,
    ):
        response = await authed_client.post(
            "/api/v1/scans",
            headers=CSRF_HEADERS,
            json=_scan_payload(upload_id=upload.id, file_ids=[f.id for f in files]),
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "queue_unavailable"

    failing_enqueue.assert_called_once()
    scan_id = failing_enqueue.call_args.args[0]

    await db_session.commit()
    row = await db_session.scalar(select(Scan).where(Scan.id == scan_id))
    assert row is not None
    assert row.status == "failed"
    assert row.error == "queue_unavailable"


async def test_csrf_required_on_post_scan(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_enqueue_run_scan: MagicMock,
) -> None:
    user = await _current_user(authed_client)
    upload, files = await _seed_upload_with_files(db_session, user_id=user.id)

    response = await authed_client.post(
        "/api/v1/scans",
        json=_scan_payload(upload_id=upload.id, file_ids=[f.id for f in files]),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    mock_enqueue_run_scan.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/v1/scans/{id}
# ---------------------------------------------------------------------------


async def test_get_scan_returns_progress(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_enqueue_run_scan: MagicMock,
) -> None:
    user = await _current_user(authed_client)
    upload, files = await _seed_upload_with_files(db_session, user_id=user.id)

    create = await authed_client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(upload_id=upload.id, file_ids=[f.id for f in files]),
    )
    assert create.status_code == 202
    scan_id = create.json()["id"]

    response = await authed_client.get(f"/api/v1/scans/{scan_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == scan_id
    assert body["upload_id"] == str(upload.id)
    assert body["status"] == SCAN_STATUS_PENDING
    assert body["progress_done"] == 0
    assert body["progress_total"] == len(files)
    assert body["scan_types"] == ["security", "bugs"]
    assert "summary" in body
    assert body["summary"]["by_severity"] == {}
    assert body["summary"]["by_type"] == {}


async def test_get_scan_returns_404_for_other_user(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_enqueue_run_scan: MagicMock,
) -> None:
    register_a = await client.post(
        "/api/v1/auth/register",
        json={"email": "owner-get@example.com", "password": "correct-horse"},
    )
    assert register_a.status_code == 201
    user_a = await _current_user(client)
    upload, files = await _seed_upload_with_files(db_session, user_id=user_a.id)
    create = await client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(upload_id=upload.id, file_ids=[f.id for f in files]),
    )
    assert create.status_code == 202
    scan_id = create.json()["id"]

    client.cookies.clear()
    register_b = await client.post(
        "/api/v1/auth/register",
        json={"email": "intruder-get@example.com", "password": "correct-horse"},
    )
    assert register_b.status_code == 201

    response = await client.get(f"/api/v1/scans/{scan_id}")

    # Must be 404, not 403 — see docs/SECURITY.md §3.
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_auth_required_on_get_scan(
    client: httpx.AsyncClient,
) -> None:
    client.cookies.clear()
    response = await client.get(f"/api/v1/scans/{uuid4()}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


# ---------------------------------------------------------------------------
# GET /api/v1/scans
# ---------------------------------------------------------------------------


async def test_list_scans_paginates_and_filters(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_enqueue_run_scan: MagicMock,
) -> None:
    user = await _current_user(authed_client)
    upload_x, files_x = await _seed_upload_with_files(db_session, user_id=user.id)
    upload_y, files_y = await _seed_upload_with_files(db_session, user_id=user.id)

    # Two scans on upload_x (both pending), one on upload_y (will mark running).
    s1 = await authed_client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(upload_id=upload_x.id, file_ids=[f.id for f in files_x]),
    )
    s2 = await authed_client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(upload_id=upload_x.id, file_ids=[f.id for f in files_x]),
    )
    s3 = await authed_client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(upload_id=upload_y.id, file_ids=[f.id for f in files_y]),
    )
    assert s1.status_code == s2.status_code == s3.status_code == 202
    s3_id = UUID(s3.json()["id"])

    # Flip s3 to running so we have a non-pending row.
    await db_session.commit()
    row = await db_session.get(Scan, s3_id)
    assert row is not None
    row.status = SCAN_STATUS_RUNNING
    await db_session.commit()

    # Default list: all 3.
    listing = await authed_client.get("/api/v1/scans")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3

    # status=pending → 2.
    pending_only = await authed_client.get("/api/v1/scans?status=pending")
    assert pending_only.status_code == 200
    pbody = pending_only.json()
    assert pbody["total"] == 2
    assert {item["status"] for item in pbody["items"]} == {"pending"}

    # upload_id=upload_y → 1.
    by_upload = await authed_client.get(f"/api/v1/scans?upload_id={upload_y.id}")
    assert by_upload.status_code == 200
    ubody = by_upload.json()
    assert ubody["total"] == 1
    assert ubody["items"][0]["upload_id"] == str(upload_y.id)

    # limit/offset.
    paged = await authed_client.get("/api/v1/scans?limit=1&offset=1")
    assert paged.status_code == 200
    pgbody = paged.json()
    assert pgbody["total"] == 3
    assert len(pgbody["items"]) == 1


async def test_list_scans_only_returns_current_user(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_enqueue_run_scan: MagicMock,
) -> None:
    register_a = await client.post(
        "/api/v1/auth/register",
        json={"email": "alice-list@example.com", "password": "correct-horse"},
    )
    assert register_a.status_code == 201
    user_a = await _current_user(client)
    upload_a, files_a = await _seed_upload_with_files(db_session, user_id=user_a.id)
    await client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(upload_id=upload_a.id, file_ids=[f.id for f in files_a]),
    )

    client.cookies.clear()
    register_b = await client.post(
        "/api/v1/auth/register",
        json={"email": "bob-list@example.com", "password": "correct-horse"},
    )
    assert register_b.status_code == 201
    user_b = await _current_user(client)
    upload_b, files_b = await _seed_upload_with_files(db_session, user_id=user_b.id)
    own = await client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(upload_id=upload_b.id, file_ids=[f.id for f in files_b]),
    )
    own_id = own.json()["id"]

    response = await client.get("/api/v1/scans")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == own_id


async def test_list_scans_rejects_bad_limit(
    authed_client: httpx.AsyncClient,
) -> None:
    response = await authed_client.get("/api/v1/scans?limit=0")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# ---------------------------------------------------------------------------
# POST /api/v1/scans/{id}/cancel
# ---------------------------------------------------------------------------


async def _make_scan_directly(
    db_session: AsyncSession,
    *,
    user_id: UUID,
    status: str = SCAN_STATUS_PENDING,
    finished_at: datetime | None = None,
) -> Scan:
    upload = _make_upload(user_id=user_id)
    db_session.add(upload)
    await db_session.flush()
    scan = Scan(
        id=uuid7(),
        user_id=user_id,
        upload_id=upload.id,
        name="t",
        scan_types=["security"],
        keywords={},
        status=status,
        progress_done=0,
        progress_total=0,
        finished_at=finished_at,
        model_settings={},
    )
    db_session.add(scan)
    await db_session.commit()
    await db_session.refresh(scan)
    return scan


async def test_cancel_scan_pending_to_cancelled(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _current_user(authed_client)
    scan = await _make_scan_directly(db_session, user_id=user.id, status=SCAN_STATUS_PENDING)

    response = await authed_client.post(
        f"/api/v1/scans/{scan.id}/cancel",
        headers=CSRF_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == SCAN_STATUS_CANCELLED
    assert body["finished_at"] is not None

    await db_session.commit()
    row = await db_session.get(Scan, scan.id)
    assert row is not None
    assert row.status == SCAN_STATUS_CANCELLED
    assert row.finished_at is not None


async def test_cancel_scan_running_to_cancelled(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _current_user(authed_client)
    scan = await _make_scan_directly(db_session, user_id=user.id, status=SCAN_STATUS_RUNNING)

    response = await authed_client.post(
        f"/api/v1/scans/{scan.id}/cancel",
        headers=CSRF_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["status"] == SCAN_STATUS_CANCELLED


async def test_cancel_scan_idempotent_on_cancelled(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _current_user(authed_client)
    finished = datetime.now(UTC)
    scan = await _make_scan_directly(
        db_session,
        user_id=user.id,
        status=SCAN_STATUS_CANCELLED,
        finished_at=finished,
    )

    response = await authed_client.post(
        f"/api/v1/scans/{scan.id}/cancel",
        headers=CSRF_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["status"] == SCAN_STATUS_CANCELLED


async def test_cancel_scan_conflict_on_completed(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _current_user(authed_client)
    scan = await _make_scan_directly(db_session, user_id=user.id, status=SCAN_STATUS_COMPLETED)

    response = await authed_client.post(
        f"/api/v1/scans/{scan.id}/cancel",
        headers=CSRF_HEADERS,
    )

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "conflict"
    assert "completed" in body["error"]["message"]


async def test_cancel_scan_404_for_other_user(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    register_a = await client.post(
        "/api/v1/auth/register",
        json={"email": "owner-cancel@example.com", "password": "correct-horse"},
    )
    assert register_a.status_code == 201
    user_a = await _current_user(client)
    scan = await _make_scan_directly(db_session, user_id=user_a.id)

    client.cookies.clear()
    register_b = await client.post(
        "/api/v1/auth/register",
        json={"email": "intruder-cancel@example.com", "password": "correct-horse"},
    )
    assert register_b.status_code == 201

    response = await client.post(
        f"/api/v1/scans/{scan.id}/cancel",
        headers=CSRF_HEADERS,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# DELETE /api/v1/scans/{id}
# ---------------------------------------------------------------------------


async def test_delete_scan_returns_204_and_removes_row(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_enqueue_run_scan: MagicMock,
) -> None:
    user = await _current_user(authed_client)
    upload, files = await _seed_upload_with_files(db_session, user_id=user.id)
    create = await authed_client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=_scan_payload(upload_id=upload.id, file_ids=[f.id for f in files]),
    )
    assert create.status_code == 202
    scan_id = UUID(create.json()["id"])

    # Confirm scan_files exist before delete.
    await db_session.commit()
    pre = (await db_session.scalars(select(ScanFile).where(ScanFile.scan_id == scan_id))).all()
    assert len(pre) == len(files)

    response = await authed_client.delete(
        f"/api/v1/scans/{scan_id}",
        headers=CSRF_HEADERS,
    )

    assert response.status_code == 204
    assert response.content == b""

    await db_session.commit()
    row = await db_session.get(Scan, scan_id)
    assert row is None
    # FK ON DELETE CASCADE should have wiped scan_files.
    post = (await db_session.scalars(select(ScanFile).where(ScanFile.scan_id == scan_id))).all()
    assert len(post) == 0


async def test_delete_scan_404_for_other_user(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    register_a = await client.post(
        "/api/v1/auth/register",
        json={"email": "owner-del@example.com", "password": "correct-horse"},
    )
    assert register_a.status_code == 201
    user_a = await _current_user(client)
    scan = await _make_scan_directly(db_session, user_id=user_a.id)

    client.cookies.clear()
    register_b = await client.post(
        "/api/v1/auth/register",
        json={"email": "intruder-del@example.com", "password": "correct-horse"},
    )
    assert register_b.status_code == 201

    response = await client.delete(
        f"/api/v1/scans/{scan.id}",
        headers=CSRF_HEADERS,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
