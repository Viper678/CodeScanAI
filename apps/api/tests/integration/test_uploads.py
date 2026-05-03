from __future__ import annotations

import io
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
from app.models.upload import Upload

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
def upload_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect storage to a temp dir for the duration of the test."""

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


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

    stored = upload_data_dir / "uploads" / str(upload_id) / "repo.zip"
    assert stored.exists()
    assert stored.read_bytes() == body

    row = await db_session.scalar(select(Upload).where(Upload.id == upload_id))
    assert row is not None
    assert row.status == "received"
    assert row.kind == "zip"
    assert row.size_bytes == len(body)
    assert row.storage_path == str(stored)

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
    assert row.storage_path.endswith(str(upload_id))
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


async def test_list_uploads_unauthenticated_returns_401(
    client: httpx.AsyncClient,
    upload_data_dir: Path,
) -> None:
    client.cookies.clear()
    response = await client.get("/api/v1/uploads")

    assert response.status_code == 401
