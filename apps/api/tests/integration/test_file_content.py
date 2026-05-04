"""Integration tests for the file viewer endpoint (T4.3).

``GET /api/v1/uploads/{upload_id}/files/{file_id}/content`` reads the
extracted file off disk. The tests stage rows directly via the test
session and write fixture files into ``tmp_path``, mirroring the worker's
post-extraction state.

Why no fixture for the upload's on-disk dir? The endpoint resolves the
file via ``upload.extract_path``, so each test points the row at its own
``tmp_path`` subdir — no shared mutable state between tests.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.uuid7 import uuid7
from app.models.file import File
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


def _make_upload(*, user_id: UUID, extract_path: str | None) -> Upload:
    return Upload(
        id=uuid7(),
        user_id=user_id,
        original_name="repo.zip",
        kind=UPLOAD_KIND_ZIP,
        size_bytes=100,
        storage_path=f"/tmp/{uuid4()}",  # noqa: S108 - test placeholder
        extract_path=extract_path,
        status=UPLOAD_STATUS_READY,
        file_count=0,
        scannable_count=0,
    )


def _make_file(
    *,
    upload_id: UUID,
    path: str,
    size_bytes: int = 42,
    is_binary: bool = False,
) -> File:
    return File(
        id=uuid7(),
        upload_id=upload_id,
        path=path,
        name=path.rsplit("/", 1)[-1],
        parent_path="/".join(path.rsplit("/", 1)[:-1]) if "/" in path else "",
        size_bytes=size_bytes,
        language="python",
        is_binary=is_binary,
        is_excluded_by_default=False,
        excluded_reason=None,
        sha256="0" * 64,
    )


async def _seed_file_on_disk(
    db_session: AsyncSession,
    *,
    user_id: UUID,
    tmp_path: Path,
    rel_path: str = "src/hello.py",
    body: bytes = b"print('hi')\n",
    write_to_disk: bool = True,
) -> tuple[Upload, File]:
    extract_root = tmp_path / "extracts" / uuid4().hex
    extract_root.mkdir(parents=True, exist_ok=True)
    if write_to_disk:
        target = extract_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)

    upload = _make_upload(user_id=user_id, extract_path=str(extract_root))
    db_session.add(upload)
    await db_session.flush()
    file_row = _make_file(
        upload_id=upload.id,
        path=rel_path,
        size_bytes=len(body),
    )
    db_session.add(file_row)
    await db_session.commit()
    await db_session.refresh(upload)
    await db_session.refresh(file_row)
    return upload, file_row


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_get_file_content_returns_text_body(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    user = await _current_user(authed_client)
    body = b"def main():\n    return 42\n"
    upload, file_row = await _seed_file_on_disk(
        db_session, user_id=user.id, tmp_path=tmp_path, body=body
    )

    response = await authed_client.get(f"/api/v1/uploads/{upload.id}/files/{file_row.id}/content")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/plain")
    # Content-Length is set so the browser can show progress + the editor
    # can decide whether to render virtualization.
    assert response.headers["content-length"] == str(len(body))
    assert response.content == body


async def test_get_file_content_unicode_round_trip(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """UTF-8 multibyte characters must survive — the endpoint streams raw bytes
    with a ``charset=utf-8`` content type, so the bytes the editor sees are
    exactly what was on disk.
    """

    user = await _current_user(authed_client)
    body = "# café — π ≈ 3.14\nname = 'José'\n".encode()
    upload, file_row = await _seed_file_on_disk(
        db_session, user_id=user.id, tmp_path=tmp_path, body=body
    )

    response = await authed_client.get(f"/api/v1/uploads/{upload.id}/files/{file_row.id}/content")

    assert response.status_code == 200
    assert response.content == body


# ---------------------------------------------------------------------------
# Auth + ownership (404 not 403 — see docs/SECURITY.md §3)
# ---------------------------------------------------------------------------


async def test_get_file_content_requires_auth(
    client: httpx.AsyncClient,
) -> None:
    client.cookies.clear()
    response = await client.get(f"/api/v1/uploads/{uuid4()}/files/{uuid4()}/content")
    assert response.status_code == 401


async def test_get_file_content_404_for_other_user(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    register_a = await client.post(
        "/api/v1/auth/register",
        json={"email": "owner-fc@example.com", "password": "correct-horse"},
    )
    assert register_a.status_code == 201
    user_a = await _current_user(client)
    upload, file_row = await _seed_file_on_disk(db_session, user_id=user_a.id, tmp_path=tmp_path)

    client.cookies.clear()
    register_b = await client.post(
        "/api/v1/auth/register",
        json={"email": "intruder-fc@example.com", "password": "correct-horse"},
    )
    assert register_b.status_code == 201

    response = await client.get(f"/api/v1/uploads/{upload.id}/files/{file_row.id}/content")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_get_file_content_404_for_unknown_upload(
    authed_client: httpx.AsyncClient,
) -> None:
    response = await authed_client.get(f"/api/v1/uploads/{uuid4()}/files/{uuid4()}/content")
    assert response.status_code == 404


async def test_get_file_content_404_for_cross_upload_file_id(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """A file_id that exists but belongs to a different upload returns 404 —
    we don't reveal the file's existence by leaking it via cross-upload reads.
    """

    user = await _current_user(authed_client)
    upload_a, _file_a = await _seed_file_on_disk(
        db_session, user_id=user.id, tmp_path=tmp_path, rel_path="a.py"
    )
    upload_b, file_b = await _seed_file_on_disk(
        db_session, user_id=user.id, tmp_path=tmp_path, rel_path="b.py"
    )

    response = await authed_client.get(f"/api/v1/uploads/{upload_a.id}/files/{file_b.id}/content")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Disk-state edge cases
# ---------------------------------------------------------------------------


async def test_get_file_content_404_when_extract_path_is_null(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    user = await _current_user(authed_client)
    upload = _make_upload(user_id=user.id, extract_path=None)
    db_session.add(upload)
    await db_session.flush()
    file_row = _make_file(upload_id=upload.id, path="x.py")
    db_session.add(file_row)
    await db_session.commit()

    response = await authed_client.get(f"/api/v1/uploads/{upload.id}/files/{file_row.id}/content")
    assert response.status_code == 404


async def test_get_file_content_404_when_disk_file_missing(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    user = await _current_user(authed_client)
    upload, file_row = await _seed_file_on_disk(
        db_session, user_id=user.id, tmp_path=tmp_path, write_to_disk=False
    )

    response = await authed_client.get(f"/api/v1/uploads/{upload.id}/files/{file_row.id}/content")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Size + binary guards
# ---------------------------------------------------------------------------


async def test_get_file_content_413_when_too_large(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """Files larger than ``max_viewable_file_size_mb`` get 413.

    We shrink the cap to 1 byte so the test doesn't have to write 2 MiB —
    the size check is independent of the actual cap value.
    """

    from _pytest.monkeypatch import MonkeyPatch

    assert isinstance(monkeypatch, MonkeyPatch)
    monkeypatch.setattr(settings, "max_viewable_file_size_mb", 0)
    user = await _current_user(authed_client)
    # Even 1 byte is over 0 MiB.
    upload, file_row = await _seed_file_on_disk(
        db_session, user_id=user.id, tmp_path=tmp_path, body=b"x"
    )

    response = await authed_client.get(f"/api/v1/uploads/{upload.id}/files/{file_row.id}/content")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_get_file_content_415_for_binary_file(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """A NUL byte in the first 8 KiB classifies the file as binary → 415."""

    user = await _current_user(authed_client)
    body = b"PK\x03\x04\x00\x00\x00\x00not really a zip"
    upload, file_row = await _seed_file_on_disk(
        db_session, user_id=user.id, tmp_path=tmp_path, body=body
    )

    response = await authed_client.get(f"/api/v1/uploads/{upload.id}/files/{file_row.id}/content")
    assert response.status_code == 415
    body_json = response.json()
    assert body_json["error"]["code"] == "unsupported_media_type"
    assert "binary_file_not_viewable" in body_json["error"]["message"]


# ---------------------------------------------------------------------------
# Path-traversal defense
# ---------------------------------------------------------------------------


async def test_get_file_content_rejects_path_traversal(
    authed_client: httpx.AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Even if a malicious row's ``path`` contains ``..``, the resolved file
    must not escape ``extract_path``. We don't *actually* traverse — assert
    the response is 404 (the safe-resolve check rejected it).
    """

    user = await _current_user(authed_client)
    extract_root = tmp_path / "extracts" / uuid4().hex
    extract_root.mkdir(parents=True, exist_ok=True)
    # Plant a real "secret" outside the extract root that the traversal
    # would point at if our guard were off.
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"top-secret password\n")

    upload = _make_upload(user_id=user.id, extract_path=str(extract_root))
    db_session.add(upload)
    await db_session.flush()
    bad_row = _make_file(upload_id=upload.id, path="../secret.txt")
    db_session.add(bad_row)
    await db_session.commit()

    response = await authed_client.get(f"/api/v1/uploads/{upload.id}/files/{bad_row.id}/content")
    assert response.status_code == 404
    # Belt-and-suspenders: never reflect the secret bytes.
    assert b"top-secret" not in response.content
