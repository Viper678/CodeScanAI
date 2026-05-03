from __future__ import annotations

from conftest import SampleUserFactory
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.uuid7 import uuid7_timestamp_ms
from app.models.scan import (
    SCAN_STATUS_COMPLETED,
    SCAN_STATUS_PENDING,
    SCAN_STATUS_RUNNING,
    SCAN_TYPE_BUGS,
    SCAN_TYPE_SECURITY,
)
from app.models.upload import UPLOAD_KIND_ZIP, UPLOAD_STATUS_RECEIVED
from app.repositories.scan_repo import ScanRepo
from app.repositories.upload_repo import UploadRepo


async def _make_upload(session: AsyncSession, *, user_id: object) -> object:
    return await UploadRepo(session).create(
        user_id=user_id,  # type: ignore[arg-type]
        original_name="src.zip",
        kind=UPLOAD_KIND_ZIP,
        size_bytes=1024,
        storage_path="data/uploads/src.zip",
        status=UPLOAD_STATUS_RECEIVED,
    )


async def test_create_round_trips_and_uses_uuid7_id(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user = await sample_user_factory()
    upload = await _make_upload(db_session, user_id=user.id)
    repo = ScanRepo(db_session)

    scan = await repo.create(
        user_id=user.id,
        upload_id=upload.id,  # type: ignore[attr-defined]
        name="first pass",
        scan_types=[SCAN_TYPE_SECURITY, SCAN_TYPE_BUGS],
        keywords={"items": [], "case_sensitive": False, "regex": False},
        model_settings={"temperature": 0.0},
        progress_total=42,
    )

    assert scan.id is not None
    # UUIDv7 carries an embedded ms timestamp; sanity-check it's non-zero.
    assert uuid7_timestamp_ms(scan.id) > 0
    assert scan.status == SCAN_STATUS_PENDING
    assert scan.progress_done == 0
    assert scan.progress_total == 42
    assert scan.scan_types == [SCAN_TYPE_SECURITY, SCAN_TYPE_BUGS]
    assert scan.keywords == {"items": [], "case_sensitive": False, "regex": False}
    assert scan.model == "gemma-4-31b-it"  # server-side default
    assert scan.model_settings == {"temperature": 0.0}


async def test_get_by_id_returns_row_for_owner(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user = await sample_user_factory()
    upload = await _make_upload(db_session, user_id=user.id)
    repo = ScanRepo(db_session)
    scan = await repo.create(
        user_id=user.id,
        upload_id=upload.id,  # type: ignore[attr-defined]
        name=None,
        scan_types=[SCAN_TYPE_SECURITY],
    )

    loaded = await repo.get_by_id(scan.id, user_id=user.id)

    assert loaded is not None
    assert loaded.id == scan.id


async def test_get_by_id_hides_row_from_other_user(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    owner = await sample_user_factory()
    other = await sample_user_factory()
    upload = await _make_upload(db_session, user_id=owner.id)
    repo = ScanRepo(db_session)
    scan = await repo.create(
        user_id=owner.id,
        upload_id=upload.id,  # type: ignore[attr-defined]
        name=None,
        scan_types=[SCAN_TYPE_SECURITY],
    )

    assert await repo.get_by_id(scan.id, user_id=other.id) is None


async def test_list_for_user_orders_by_created_at_desc(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user = await sample_user_factory()
    upload = await _make_upload(db_session, user_id=user.id)
    repo = ScanRepo(db_session)
    first = await repo.create(
        user_id=user.id,
        upload_id=upload.id,  # type: ignore[attr-defined]
        name="first",
        scan_types=[SCAN_TYPE_SECURITY],
    )
    second = await repo.create(
        user_id=user.id,
        upload_id=upload.id,  # type: ignore[attr-defined]
        name="second",
        scan_types=[SCAN_TYPE_BUGS],
    )

    rows = await repo.list_for_user(user_id=user.id)

    assert [row.id for row in rows] == [second.id, first.id]


async def test_list_for_user_respects_limit_and_offset(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user = await sample_user_factory()
    upload = await _make_upload(db_session, user_id=user.id)
    repo = ScanRepo(db_session)
    created = []
    for index in range(3):
        created.append(
            await repo.create(
                user_id=user.id,
                upload_id=upload.id,  # type: ignore[attr-defined]
                name=f"scan-{index}",
                scan_types=[SCAN_TYPE_SECURITY],
            )
        )
    # Newest first.
    expected_order = list(reversed(created))

    page = await repo.list_for_user(user_id=user.id, limit=2, offset=0)
    assert [row.id for row in page] == [expected_order[0].id, expected_order[1].id]

    page = await repo.list_for_user(user_id=user.id, limit=2, offset=2)
    assert [row.id for row in page] == [expected_order[2].id]


async def test_list_for_user_filters_by_status(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user = await sample_user_factory()
    upload = await _make_upload(db_session, user_id=user.id)
    repo = ScanRepo(db_session)
    pending = await repo.create(
        user_id=user.id,
        upload_id=upload.id,  # type: ignore[attr-defined]
        name="pending",
        scan_types=[SCAN_TYPE_SECURITY],
    )
    running = await repo.create(
        user_id=user.id,
        upload_id=upload.id,  # type: ignore[attr-defined]
        name="running",
        scan_types=[SCAN_TYPE_SECURITY],
    )
    running.status = SCAN_STATUS_RUNNING
    await db_session.flush()

    pending_rows = await repo.list_for_user(user_id=user.id, status=SCAN_STATUS_PENDING)
    running_rows = await repo.list_for_user(user_id=user.id, status=SCAN_STATUS_RUNNING)

    assert [row.id for row in pending_rows] == [pending.id]
    assert [row.id for row in running_rows] == [running.id]


async def test_list_for_user_filters_by_upload_id(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user = await sample_user_factory()
    upload_a = await _make_upload(db_session, user_id=user.id)
    upload_b = await _make_upload(db_session, user_id=user.id)
    repo = ScanRepo(db_session)
    scan_a = await repo.create(
        user_id=user.id,
        upload_id=upload_a.id,  # type: ignore[attr-defined]
        name="a",
        scan_types=[SCAN_TYPE_SECURITY],
    )
    scan_b = await repo.create(
        user_id=user.id,
        upload_id=upload_b.id,  # type: ignore[attr-defined]
        name="b",
        scan_types=[SCAN_TYPE_SECURITY],
    )

    rows_a = await repo.list_for_user(user_id=user.id, upload_id=upload_a.id)  # type: ignore[attr-defined]
    rows_b = await repo.list_for_user(user_id=user.id, upload_id=upload_b.id)  # type: ignore[attr-defined]

    assert [row.id for row in rows_a] == [scan_a.id]
    assert [row.id for row in rows_b] == [scan_b.id]


async def test_count_for_user_matches_filtered_list(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user = await sample_user_factory()
    upload = await _make_upload(db_session, user_id=user.id)
    repo = ScanRepo(db_session)
    scan_one = await repo.create(
        user_id=user.id,
        upload_id=upload.id,  # type: ignore[attr-defined]
        name="one",
        scan_types=[SCAN_TYPE_SECURITY],
    )
    scan_two = await repo.create(
        user_id=user.id,
        upload_id=upload.id,  # type: ignore[attr-defined]
        name="two",
        scan_types=[SCAN_TYPE_SECURITY],
    )
    scan_two.status = SCAN_STATUS_COMPLETED
    await db_session.flush()

    assert await repo.count_for_user(user_id=user.id) == 2
    assert await repo.count_for_user(user_id=user.id, status=SCAN_STATUS_PENDING) == 1
    assert await repo.count_for_user(user_id=user.id, status=SCAN_STATUS_COMPLETED) == 1
    assert (
        await repo.count_for_user(
            user_id=user.id,
            upload_id=upload.id,  # type: ignore[attr-defined]
        )
        == 2
    )

    # Sanity: the count stays scoped to the owner.
    other = await sample_user_factory()
    assert await repo.count_for_user(user_id=other.id) == 0
    assert scan_one.id != scan_two.id
