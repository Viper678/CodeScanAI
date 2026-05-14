"""Integration tests for ``GET /api/v1/uploads/{id}/tree`` (T2.3).

The endpoint is a pure DB read on the ``files`` table. Rather than driving
the whole worker pipeline we stage rows directly via the test session and
flip the upload's ``status`` so the response logic is exercised in isolation.
"""

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
from app.core.uuid7 import uuid7
from app.models.file import File
from app.models.upload import (
    UPLOAD_STATUS_EXTRACTING,
    UPLOAD_STATUS_FAILED,
    UPLOAD_STATUS_READY,
    UPLOAD_STATUS_RECEIVED,
    Upload,
)

CSRF_HEADERS = {"X-Requested-With": "codescan"}


def _zip_bytes(entries: dict[str, str] | None = None) -> bytes:
    payload = entries or {"hello.py": "print('hi')\n"}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in payload.items():
            archive.writestr(name, body)
    return buffer.getvalue()


@pytest.fixture
def upload_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


@pytest.fixture
def mock_enqueue() -> Iterator[MagicMock]:
    with patch(
        "app.services.upload_service.enqueue_prepare_upload",
        new=MagicMock(),
    ) as mocked:
        yield mocked


async def _create_upload_via_api(
    client: httpx.AsyncClient,
    *,
    name: str = "repo.zip",
) -> UUID:
    response = await client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": (name, _zip_bytes(), "application/zip")},
        data={"kind": "zip"},
    )
    assert response.status_code == 202, response.text
    return UUID(response.json()["id"])


async def _flip_status(db_session: AsyncSession, upload_id: UUID, status: str) -> None:
    upload = await db_session.get(Upload, upload_id)
    assert upload is not None
    upload.status = status
    await db_session.commit()


def _make_file(
    upload_id: UUID,
    *,
    path: str,
    parent_path: str,
    name: str,
    size_bytes: int = 100,
    language: str | None = "python",
    is_binary: bool = False,
    is_excluded_by_default: bool = False,
    excluded_reason: str | None = None,
    sha256: str = "deadbeef",
) -> File:
    return File(
        id=uuid7(),
        upload_id=upload_id,
        path=path,
        parent_path=parent_path,
        name=name,
        size_bytes=size_bytes,
        language=language,
        is_binary=is_binary,
        is_excluded_by_default=is_excluded_by_default,
        excluded_reason=excluded_reason,
        sha256=sha256,
    )


async def test_get_tree_returns_sorted_files_for_ready_upload(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    upload_id = await _create_upload_via_api(authed_client, name="myrepo.zip")

    # Insert files in a deliberately scrambled order to prove the endpoint
    # sorts them lexicographically by `path`.
    db_session.add_all(
        [
            _make_file(
                upload_id,
                path="src/main.py",
                parent_path="src",
                name="main.py",
                size_bytes=42,
            ),
            _make_file(
                upload_id,
                path="README.md",
                parent_path="",
                name="README.md",
                size_bytes=12,
                language="markdown",
            ),
            _make_file(
                upload_id,
                path="node_modules/lodash/index.js",
                parent_path="node_modules/lodash",
                name="index.js",
                size_bytes=2048,
                language="javascript",
                is_excluded_by_default=True,
                excluded_reason="vendor_dir",
            ),
            _make_file(
                upload_id,
                path="src/api/auth.py",
                parent_path="src/api",
                name="auth.py",
                size_bytes=4321,
            ),
        ]
    )
    await _flip_status(db_session, upload_id, UPLOAD_STATUS_READY)

    response = await authed_client.get(f"/api/v1/uploads/{upload_id}/tree")

    assert response.status_code == 200
    body = response.json()
    assert body["upload_id"] == str(upload_id)
    assert body["root_name"] == "myrepo"  # `.zip` stripped
    assert body["status"] == "ready"

    paths = [f["path"] for f in body["files"]]
    assert (
        paths
        == sorted(paths)
        == [
            "README.md",
            "node_modules/lodash/index.js",
            "src/api/auth.py",
            "src/main.py",
        ]
    )

    excluded = next(f for f in body["files"] if f["path"].startswith("node_modules"))
    assert excluded["is_excluded_by_default"] is True
    assert excluded["excluded_reason"] == "vendor_dir"
    assert excluded["language"] == "javascript"

    readme = next(f for f in body["files"] if f["path"] == "README.md")
    assert readme["parent_path"] == ""
    assert readme["is_excluded_by_default"] is False
    assert readme["excluded_reason"] is None
    assert readme["size_bytes"] == 12


async def test_get_tree_returns_empty_when_status_received(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    upload_id = await _create_upload_via_api(authed_client)
    # Default status is `received` — but assert it just to be deterministic.
    await _flip_status(db_session, upload_id, UPLOAD_STATUS_RECEIVED)

    response = await authed_client.get(f"/api/v1/uploads/{upload_id}/tree")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body["files"] == []
    assert body["upload_id"] == str(upload_id)


async def test_get_tree_returns_empty_when_status_extracting(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    upload_id = await _create_upload_via_api(authed_client)
    await _flip_status(db_session, upload_id, UPLOAD_STATUS_EXTRACTING)

    response = await authed_client.get(f"/api/v1/uploads/{upload_id}/tree")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "extracting"
    assert body["files"] == []


async def test_get_tree_returns_empty_when_status_failed(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    upload_id = await _create_upload_via_api(authed_client)
    await _flip_status(db_session, upload_id, UPLOAD_STATUS_FAILED)

    response = await authed_client.get(f"/api/v1/uploads/{upload_id}/tree")

    # Tree is a query of state, not a re-throw of the upload's failure.
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["files"] == []


async def test_get_tree_unauthenticated_returns_401(
    client: httpx.AsyncClient,
    upload_data_dir: Path,
) -> None:
    client.cookies.clear()
    response = await client.get(f"/api/v1/uploads/{uuid4()}/tree")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_get_tree_returns_404_for_unknown_id(
    authed_client: httpx.AsyncClient,
    upload_data_dir: Path,
) -> None:
    response = await authed_client.get(f"/api/v1/uploads/{uuid4()}/tree")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_get_tree_returns_404_for_other_users_upload(
    client: httpx.AsyncClient,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    # User A creates an upload.
    register_a = await client.post(
        "/api/v1/auth/register",
        json={"email": "owner-tree@example.com", "password": "correct-horse"},
    )
    assert register_a.status_code == 201
    upload_id = await _create_upload_via_api(client, name="private.zip")

    # User B logs in fresh.
    client.cookies.clear()
    register_b = await client.post(
        "/api/v1/auth/register",
        json={"email": "intruder-tree@example.com", "password": "correct-horse"},
    )
    assert register_b.status_code == 201

    response = await client.get(f"/api/v1/uploads/{upload_id}/tree")

    # Must be 404, not 403 — we don't reveal that the upload exists.
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_get_tree_returns_422_for_malformed_uuid(
    authed_client: httpx.AsyncClient,
    upload_data_dir: Path,
) -> None:
    response = await authed_client.get("/api/v1/uploads/not-a-uuid/tree")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_get_tree_does_not_leak_other_users_files(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    """Belt-and-suspenders: even if a router accidentally trusted the path
    param, the FileRepo JOIN would still not expose another user's rows.
    """

    register_a = await client.post(
        "/api/v1/auth/register",
        json={"email": "alice-tree@example.com", "password": "correct-horse"},
    )
    assert register_a.status_code == 201
    a_upload_id = await _create_upload_via_api(client, name="a.zip")

    db_session.add(
        _make_file(
            a_upload_id,
            path="secrets.py",
            parent_path="",
            name="secrets.py",
        )
    )
    await _flip_status(db_session, a_upload_id, UPLOAD_STATUS_READY)

    # Sanity: the row is actually present in the DB.
    rows = (await db_session.scalars(select(File).where(File.upload_id == a_upload_id))).all()
    assert len(rows) == 1

    client.cookies.clear()
    register_b = await client.post(
        "/api/v1/auth/register",
        json={"email": "bob-tree@example.com", "password": "correct-horse"},
    )
    assert register_b.status_code == 201

    response = await client.get(f"/api/v1/uploads/{a_upload_id}/tree")
    assert response.status_code == 404


async def test_get_tree_root_name_for_loose_upload(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    upload_data_dir: Path,
    mock_enqueue: MagicMock,
) -> None:
    """For loose uploads the original name is passed through unchanged."""

    response = await authed_client.post(
        "/api/v1/uploads",
        headers=CSRF_HEADERS,
        files={"file": ("snippet.py", b"x = 1\n", "text/x-python")},
        data={"kind": "loose"},
    )
    assert response.status_code == 202
    upload_id = UUID(response.json()["id"])
    await _flip_status(db_session, upload_id, UPLOAD_STATUS_READY)

    tree = await authed_client.get(f"/api/v1/uploads/{upload_id}/tree")
    assert tree.status_code == 200
    body = tree.json()
    assert body["root_name"] == "snippet.py"
    assert body["files"] == []
