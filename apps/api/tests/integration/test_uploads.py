from __future__ import annotations

import io
import shutil
import zipfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.uuid7 import uuid7
from app.models.file import File
from app.models.scan import Scan
from app.models.scan_file import ScanFile
from app.models.scan_finding import ScanFinding
from app.models.upload import Upload
from app.storage import reset_storage_cache

CSRF_HEADERS = {"X-Requested-With": "codescan"}


def _zip_bytes(entries: dict[str, str] | None = None) -> bytes:
    """Return the bytes of a small in-memory zip with one or more entries."""

    payload = entries or {"hello.py": "print('hello, world')\n"}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in payload.items():
            archive.writestr(name, body)
    return buffer.getvalue()


@pytest.fixture
def upload_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect storage to a temp dir for the duration of the test.

    Post-M2 the LocalStorage impl is cached by the storage factory; the
    cache is invalidated before AND after each test so the test sees a
    fresh storage rooted at its ``tmp_path`` and doesn't leak that root
    to the next test.
    """

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    reset_storage_cache()
    yield tmp_path
    reset_storage_cache()


@pytest.fixture
def mock_enqueue() -> Iterator[MagicMock]:
    """Replace the broker enqueue with a mock — tests must never hit Redis."""

    with patch(
        "app.services.upload_service.enqueue_prepare_upload",
        new=MagicMock(),
    ) as mocked:
        yield mocked


async def test_post_zip_upload_happy_path(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    body = _zip_bytes({"src/main.py": "print(1)\n", "README.md": "hi"})

    response = await authed_client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": ("repo.zip", body, "application/zip")},
        data={"kind": "zip"},
    )

    assert response.status_code == 202
    payload = response.json()
    upload_id = UUID(payload["id"])
    assert payload["status"] == "received"
    assert payload["kind"] == "zip"
    assert payload["original_name"] == "repo.zip"
    assert payload["size_bytes"] == len(body)

    # Post-M2: the api writes the raw zip to the canonical
    # ``uploads/<id>/raw.zip`` storage key (not the user-supplied
    # filename). On the LocalStorage backend that's
    # ``<data_dir>/uploads/<id>/raw.zip``.
    stored = upload_data_dir / "uploads" / str(upload_id) / "raw.zip"
    assert stored.exists()
    assert stored.read_bytes() == body

    row = await db_session.scalar(select(Upload).where(Upload.id == upload_id))
    assert row is not None
    assert row.status == "received"
    assert row.kind == "zip"
    assert row.size_bytes == len(body)
    assert row.storage_path == f"uploads/{upload_id}/raw.zip"

    mock_enqueue.assert_called_once_with(upload_id)


async def test_post_loose_upload_with_single_py_file(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    body = b"def hello():\n    return 1\n"

    response = await authed_client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": ("snippet.py", body, "text/x-python")},
        data={"kind": "loose"},
    )

    assert response.status_code == 202
    payload = response.json()
    upload_id = UUID(payload["id"])
    assert payload["kind"] == "loose"
    assert payload["status"] == "received"
    assert payload["original_name"] == "snippet.py"
    assert payload["size_bytes"] == len(body)

    stored = upload_data_dir / "uploads" / str(upload_id) / "loose" / "snippet.py"
    assert stored.exists()
    assert stored.read_bytes() == body

    row = await db_session.scalar(select(Upload).where(Upload.id == upload_id))
    assert row is not None
    assert row.kind == "loose"
    # Post-M2: storage_path is the upload-level prefix
    # (``uploads/<id>``, no trailing slash) — the worker walks it for
    # loose-file uploads.
    assert row.storage_path == f"uploads/{upload_id}"
    mock_enqueue.assert_called_once_with(upload_id)


async def test_post_loose_upload_with_multiple_files(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    response = await authed_client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files=[
            ("file", ("a.py", b"a = 1\n", "text/x-python")),
            ("file", ("b.py", b"b = 2\n", "text/x-python")),
        ],
        data={"kind": "loose"},
    )

    assert response.status_code == 202
    payload = response.json()
    upload_id = UUID(payload["id"])
    assert payload["original_name"].startswith("loose-")
    assert payload["size_bytes"] == len(b"a = 1\n") + len(b"b = 2\n")

    loose_dir = upload_data_dir / "uploads" / str(upload_id) / "loose"
    assert (loose_dir / "a.py").read_bytes() == b"a = 1\n"
    assert (loose_dir / "b.py").read_bytes() == b"b = 2\n"

    row = await db_session.scalar(select(Upload).where(Upload.id == upload_id))
    assert row is not None
    assert row.kind == "loose"
    mock_enqueue.assert_called_once_with(upload_id)


async def test_post_upload_unauthenticated_returns_401(
    client: httpx.AsyncClient,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    response = await client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": ("snippet.py", b"x = 1", "text/x-python")},
        data={"kind": "loose"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    mock_enqueue.assert_not_called()


async def test_post_upload_without_csrf_header_returns_403(
    authed_client: httpx.AsyncClient,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    response = await authed_client.post(
        "/api/v1/uploads",
        files={"file": ("snippet.py", b"x = 1", "text/x-python")},
        data={"kind": "loose"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    mock_enqueue.assert_not_called()


async def test_post_loose_upload_rejects_disallowed_extension(
    authed_client: httpx.AsyncClient,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    response = await authed_client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": ("payload.exe", b"\x4d\x5a", "application/octet-stream")},
        data={"kind": "loose"},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    mock_enqueue.assert_not_called()


async def test_post_zip_upload_rejects_non_zip_payload(
    authed_client: httpx.AsyncClient,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    response = await authed_client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": ("repo.zip", b"this is not a zip", "application/zip")},
        data={"kind": "zip"},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    mock_enqueue.assert_not_called()


async def test_post_zip_upload_rejects_oversize_payload(
    authed_client: httpx.AsyncClient,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Drop the cap to 1 byte so any zip we craft trips the limit.
    monkeypatch.setattr(settings, "max_upload_size_mb", 0)

    response = await authed_client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": ("repo.zip", _zip_bytes(), "application/zip")},
        data={"kind": "zip"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    mock_enqueue.assert_not_called()


async def test_post_upload_with_missing_kind_returns_422(
    authed_client: httpx.AsyncClient,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    response = await authed_client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": ("snippet.py", b"x = 1", "text/x-python")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    mock_enqueue.assert_not_called()


async def test_post_upload_with_no_file_returns_422(
    authed_client: httpx.AsyncClient,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    response = await authed_client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        data={"kind": "loose"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    mock_enqueue.assert_not_called()


async def test_post_upload_with_unknown_kind_returns_422(
    authed_client: httpx.AsyncClient,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    response = await authed_client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": ("snippet.py", b"x = 1", "text/x-python")},
        data={"kind": "tarball"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    mock_enqueue.assert_not_called()


async def test_get_upload_returns_detail_for_owner(
    authed_client: httpx.AsyncClient,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    create = await authed_client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": ("repo.zip", _zip_bytes(), "application/zip")},
        data={"kind": "zip"},
    )
    assert create.status_code == 202
    upload_id = create.json()["id"]

    response = await authed_client.get(f"/api/v1/uploads/{upload_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == upload_id
    assert body["status"] == "received"
    assert body["file_count"] == 0
    assert body["scannable_count"] == 0


async def test_get_upload_returns_404_for_unknown_id(
    authed_client: httpx.AsyncClient,
    upload_data_dir: Path,
) -> None:
    response = await authed_client.get(f"/api/v1/uploads/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_get_upload_returns_404_for_other_users_upload(
    client: httpx.AsyncClient,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    # User A creates an upload.
    register_a = await client.post(
        "/api/v1/auth/register",
        json={"email": "owner@example.com", "password": "correct-horse"},
    )
    assert register_a.status_code == 201
    create = await client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": ("repo.zip", _zip_bytes(), "application/zip")},
        data={"kind": "zip"},
    )
    assert create.status_code == 202
    upload_id = create.json()["id"]

    # User B logs in (clear A's cookies first).
    client.cookies.clear()
    register_b = await client.post(
        "/api/v1/auth/register",
        json={"email": "intruder@example.com", "password": "correct-horse"},
    )
    assert register_b.status_code == 201

    response = await client.get(f"/api/v1/uploads/{upload_id}")

    # Must be 404, not 403 — we don't reveal that the upload exists.
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_list_uploads_returns_only_current_user_uploads(
    client: httpx.AsyncClient,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "correct-horse"},
    )
    await client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": ("a.zip", _zip_bytes(), "application/zip")},
        data={"kind": "zip"},
    )

    client.cookies.clear()
    await client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "correct-horse"},
    )
    own = await client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": ("b.zip", _zip_bytes(), "application/zip")},
        data={"kind": "zip"},
    )
    own_id = own.json()["id"]

    response = await client.get("/api/v1/uploads")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == own_id


async def test_list_uploads_filters_by_status(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    """``GET /uploads?status=ready`` returns only ready rows.

    Without this, the new-scan wizard's "Use existing" picker would
    client-side filter the first page — which mis-renders the empty
    state if the latest N rows are all extracting/failed but an older
    ready row exists (newest-first ordering). Codex P2 on PR #66.
    """
    del mock_enqueue
    await client.post(
        "/api/v1/auth/register",
        json={"email": "carol@example.com", "password": "correct-horse"},
    )
    # Three uploads created via POST land in ``received``. Mutate two to
    # ``ready`` and ``extracting`` directly so the filter has variance to
    # discriminate on.
    ids = []
    for name in ("a.zip", "b.zip", "c.zip"):
        r = await client.post(
            "/api/v1/uploads",
            headers=CSRF_HEADERS,
            files={"file": (name, _zip_bytes(), "application/zip")},
            data={"kind": "zip"},
        )
        assert r.status_code == 202
        ids.append(r.json()["id"])
    rows = (
        (await db_session.execute(select(Upload).where(Upload.id.in_([UUID(x) for x in ids]))))
        .scalars()
        .all()
    )
    by_id = {str(u.id): u for u in rows}
    by_id[ids[0]].status = "ready"
    by_id[ids[1]].status = "extracting"
    # ids[2] stays ``received``
    await db_session.commit()

    # ?status=ready → 1 row
    response = await client.get("/api/v1/uploads?status=ready")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [ids[0]]

    # ?status=extracting → 1 row
    response = await client.get("/api/v1/uploads?status=extracting")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [ids[1]]

    # ?status=failed → 0 rows (the filter doesn't crash on no matches)
    response = await client.get("/api/v1/uploads?status=failed")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0

    # No filter → all 3
    response = await client.get("/api/v1/uploads")
    assert response.json()["total"] == 3


async def test_list_uploads_rejects_unknown_status(
    client: httpx.AsyncClient,
    upload_data_dir: Path,
) -> None:
    """An unknown ``status`` value must be a 422, not silently ignored.
    Silently dropping the filter would mask typos and surface a confusing
    superset of rows. Codex P2 follow-up on PR #66. The 422 + ``validation_error``
    shape matches the rest of the upload-router rejections (see
    ``InvalidUploadRequest`` in ``app/core/exceptions.py``)."""

    await client.post(
        "/api/v1/auth/register",
        json={"email": "carol2@example.com", "password": "correct-horse"},
    )
    response = await client.get("/api/v1/uploads?status=somethingweird")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_list_uploads_unauthenticated_returns_401(
    client: httpx.AsyncClient,
    upload_data_dir: Path,
) -> None:
    client.cookies.clear()
    response = await client.get("/api/v1/uploads")

    assert response.status_code == 401


async def test_post_zip_upload_marks_failed_when_broker_unavailable(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
) -> None:
    body = _zip_bytes()
    failing_enqueue = MagicMock(side_effect=ConnectionError("broker down"))

    with patch(
        "app.services.upload_service.enqueue_prepare_upload",
        new=failing_enqueue,
    ):
        response = await authed_client.post(
            "/api/v1/uploads",
            headers=CSRF_HEADERS,
            files={"file": ("repo.zip", body, "application/zip")},
            data={"kind": "zip"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "queue_unavailable"

    failing_enqueue.assert_called_once()
    upload_id = failing_enqueue.call_args.args[0]

    await db_session.commit()  # release any open snapshot before re-reading
    row = await db_session.scalar(select(Upload).where(Upload.id == upload_id))
    assert row is not None
    assert row.status == "failed"
    assert row.error == "queue_unavailable"


async def test_post_loose_upload_marks_failed_when_broker_unavailable(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
) -> None:
    failing_enqueue = MagicMock(side_effect=RuntimeError("kombu boom"))

    with patch(
        "app.services.upload_service.enqueue_prepare_upload",
        new=failing_enqueue,
    ):
        response = await authed_client.post(
            "/api/v1/uploads",
            headers=CSRF_HEADERS,
            files={"file": ("snippet.py", b"x = 1\n", "text/x-python")},
            data={"kind": "loose"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "queue_unavailable"

    upload_id = failing_enqueue.call_args.args[0]
    await db_session.commit()
    row = await db_session.scalar(select(Upload).where(Upload.id == upload_id))
    assert row is not None
    assert row.status == "failed"
    assert row.error == "queue_unavailable"


# ---------------------------------------------------------------------------
# DELETE /api/v1/uploads/{id}
# ---------------------------------------------------------------------------


async def _create_upload_via_api(
    authed_client: httpx.AsyncClient,
    *,
    body: bytes | None = None,
) -> UUID:
    """POST a tiny zip and return the new upload id."""

    response = await authed_client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": ("repo.zip", body or _zip_bytes(), "application/zip")},
        data={"kind": "zip"},
    )
    assert response.status_code == 202, response.text
    return UUID(response.json()["id"])


async def test_delete_upload_returns_204_and_wipes_disk(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    upload_id = await _create_upload_via_api(authed_client)
    upload_dir = upload_data_dir / "uploads" / str(upload_id)
    assert upload_dir.exists()  # raw artifact landed on disk

    response = await authed_client.delete(
        f"/api/v1/uploads/{upload_id}",
        headers=CSRF_HEADERS,
    )

    assert response.status_code == 204
    assert response.content == b""

    assert not upload_dir.exists(), "raw upload tree should be gone"

    await db_session.commit()
    row = await db_session.scalar(select(Upload).where(Upload.id == upload_id))
    assert row is None


async def test_delete_upload_cascades_to_files_scans_and_findings(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    """Deleting an upload must leave no row referencing it.

    Seeds an upload + one file + one scan + one scan_file + one scan_finding,
    plus an extract directory on disk distinct from the upload dir, then
    asserts the DELETE wipes everything in one shot. This is the contract
    that makes the endpoint safe to surface to data-retention-conscious
    customers.
    """

    upload_id = await _create_upload_via_api(authed_client)
    upload = await db_session.scalar(select(Upload).where(Upload.id == upload_id))
    assert upload is not None

    # Post-M2: extracted files live under the upload's storage prefix
    # (``uploads/<id>/extracted/...``). The DELETE wipes that entire
    # prefix in one shot, so we plant a representative artifact under
    # the LocalStorage root to assert it disappears.
    extract_dir = upload_data_dir / "uploads" / str(upload_id) / "extracted"
    extract_dir.mkdir(parents=True)
    (extract_dir / "main.py").write_text("print('hi')\n")
    upload.extract_path = f"uploads/{upload_id}/extracted"
    upload.status = "ready"

    file_row = File(
        id=uuid7(),
        upload_id=upload.id,
        path="src/main.py",
        name="main.py",
        parent_path="src",
        size_bytes=10,
        language="python",
        is_binary=False,
        is_excluded_by_default=False,
        excluded_reason=None,
        sha256="deadbeef",
    )
    db_session.add(file_row)
    scan_row = Scan(
        id=uuid7(),
        user_id=upload.user_id,
        upload_id=upload.id,
        name="test scan",
        scan_types=["security"],
        keywords={},
        status="completed",
        progress_done=1,
        progress_total=1,
        model="gemma-4-31b-it",
        model_settings={},
    )
    db_session.add(scan_row)
    await db_session.flush()
    scan_file_row = ScanFile(
        id=uuid7(),
        scan_id=scan_row.id,
        file_id=file_row.id,
        status="done",
    )
    finding_row = ScanFinding(
        id=uuid7(),
        scan_id=scan_row.id,
        file_id=file_row.id,
        scan_type="security",
        severity="high",
        title="example",
        message="example",
    )
    db_session.add_all([scan_file_row, finding_row])
    await db_session.commit()

    response = await authed_client.delete(
        f"/api/v1/uploads/{upload_id}",
        headers=CSRF_HEADERS,
    )
    assert response.status_code == 204

    await db_session.commit()
    assert (await db_session.scalar(select(Upload).where(Upload.id == upload_id))) is None
    assert (await db_session.scalar(select(File).where(File.id == file_row.id))) is None
    assert (await db_session.scalar(select(Scan).where(Scan.id == scan_row.id))) is None
    sf_row = await db_session.scalar(
        select(ScanFile).where(ScanFile.id == scan_file_row.id),
    )
    assert sf_row is None
    finding = await db_session.scalar(
        select(ScanFinding).where(ScanFinding.id == finding_row.id),
    )
    assert finding is None

    assert not extract_dir.exists(), "extract tree should be gone"
    assert not (upload_data_dir / "uploads" / str(upload_id)).exists()


async def test_delete_upload_404_for_other_user(
    client: httpx.AsyncClient,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    register_a = await client.post(
        "/api/v1/auth/register",
        json={"email": "owner-del@example.com", "password": "correct-horse"},
    )
    assert register_a.status_code == 201
    create = await client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": ("repo.zip", _zip_bytes(), "application/zip")},
        data={"kind": "zip"},
    )
    assert create.status_code == 202
    upload_id = UUID(create.json()["id"])

    client.cookies.clear()
    register_b = await client.post(
        "/api/v1/auth/register",
        json={"email": "intruder-del@example.com", "password": "correct-horse"},
    )
    assert register_b.status_code == 201

    response = await client.delete(
        f"/api/v1/uploads/{upload_id}",
        headers=CSRF_HEADERS,
    )

    # 404, not 403 — same no-enumeration rule as GET /uploads/{id}.
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    # Disk artifact must survive — the cross-user request is not authorized
    # to delete it.
    assert (upload_data_dir / "uploads" / str(upload_id)).exists()


async def test_delete_upload_404_for_unknown_id(
    authed_client: httpx.AsyncClient,
    upload_data_dir: Path,
) -> None:
    response = await authed_client.delete(
        f"/api/v1/uploads/{uuid4()}",
        headers=CSRF_HEADERS,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_delete_upload_unauthenticated_returns_401(
    client: httpx.AsyncClient,
    upload_data_dir: Path,
) -> None:
    response = await client.delete(
        f"/api/v1/uploads/{uuid4()}",
        headers=CSRF_HEADERS,
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_delete_upload_without_csrf_header_returns_403(
    authed_client: httpx.AsyncClient,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    upload_id = await _create_upload_via_api(authed_client)

    response = await authed_client.delete(f"/api/v1/uploads/{upload_id}")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    # And the upload must still be there.
    assert (upload_data_dir / "uploads" / str(upload_id)).exists()


async def test_delete_upload_tolerates_missing_disk_artifacts(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    """A pre-wiped on-disk tree (e.g. the cleanup beat task already ran) must
    not block deletion — the row should still be removed."""

    upload_id = await _create_upload_via_api(authed_client)
    upload_dir = upload_data_dir / "uploads" / str(upload_id)
    shutil.rmtree(upload_dir)
    assert not upload_dir.exists()

    response = await authed_client.delete(
        f"/api/v1/uploads/{upload_id}",
        headers=CSRF_HEADERS,
    )

    assert response.status_code == 204
    await db_session.commit()
    row = await db_session.scalar(select(Upload).where(Upload.id == upload_id))
    assert row is None


async def test_delete_upload_tolerates_null_extract_path(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    """An upload that never finished extracting still deletes cleanly — the
    extract_path is null, so we only wipe the raw upload dir."""

    upload_id = await _create_upload_via_api(authed_client)
    upload = await db_session.scalar(select(Upload).where(Upload.id == upload_id))
    assert upload is not None
    assert upload.extract_path is None  # received → never got past worker

    response = await authed_client.delete(
        f"/api/v1/uploads/{upload_id}",
        headers=CSRF_HEADERS,
    )

    assert response.status_code == 204
    await db_session.commit()
    row = await db_session.scalar(select(Upload).where(Upload.id == upload_id))
    assert row is None
    assert not (upload_data_dir / "uploads" / str(upload_id)).exists()
