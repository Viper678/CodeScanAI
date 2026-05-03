from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.upload import UploadCreateResponse, UploadDetail


def test_create_response_round_trip() -> None:
    body = UploadCreateResponse(
        id=uuid4(),
        status="received",
        kind="zip",
        original_name="myrepo.zip",
        size_bytes=12345,
    )
    assert body.kind == "zip"
    assert body.status == "received"
    assert body.original_name == "myrepo.zip"


@pytest.mark.parametrize("kind", ["tar", "rar", "exe", ""])
def test_create_response_rejects_unknown_kind(kind: str) -> None:
    with pytest.raises(ValidationError):
        UploadCreateResponse(
            id=uuid4(),
            status="received",
            kind=kind,  # type: ignore[arg-type]
            original_name="x.zip",
            size_bytes=1,
        )


@pytest.mark.parametrize("status", ["queued", "done", ""])
def test_create_response_rejects_unknown_status(status: str) -> None:
    with pytest.raises(ValidationError):
        UploadCreateResponse(
            id=uuid4(),
            status=status,  # type: ignore[arg-type]
            kind="zip",
            original_name="x.zip",
            size_bytes=1,
        )


def test_detail_response_serializes_timestamps() -> None:
    now = datetime.now(UTC)
    detail = UploadDetail(
        id=uuid4(),
        status="ready",
        kind="loose",
        original_name="snippet.py",
        size_bytes=10,
        file_count=1,
        scannable_count=1,
        created_at=now,
        updated_at=now,
        error=None,
    )
    dumped = detail.model_dump(mode="json")
    assert dumped["status"] == "ready"
    assert dumped["created_at"].endswith("Z") or "+" in dumped["created_at"]
