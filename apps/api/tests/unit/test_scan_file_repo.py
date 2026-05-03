from __future__ import annotations

from uuid import UUID

from conftest import SampleUserFactory
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.uuid7 import uuid7
from app.models.file import File
from app.models.scan import Scan
from app.models.scan_file import SCAN_FILE_STATUS_PENDING
from app.models.upload import UPLOAD_KIND_ZIP, UPLOAD_STATUS_RECEIVED
from app.models.user import User
from app.repositories.scan_file_repo import ScanFileRepo
from app.repositories.scan_repo import ScanRepo
from app.repositories.upload_repo import UploadRepo


async def _make_file(session: AsyncSession, *, upload_id: UUID, name: str) -> File:
    file = File(
        id=uuid7(),
        upload_id=upload_id,
        path=name,
        name=name,
        parent_path="",
        size_bytes=10,
        language="python",
        is_binary=False,
        is_excluded_by_default=False,
        excluded_reason=None,
        sha256="0" * 64,
    )
    session.add(file)
    await session.flush()
    return file


async def _scan_with_files(
    session: AsyncSession,
    sample_user_factory: SampleUserFactory,
    *,
    file_count: int = 3,
) -> tuple[User, list[File], Scan]:
    user = await sample_user_factory()
    upload = await UploadRepo(session).create(
        user_id=user.id,
        original_name="src.zip",
        kind=UPLOAD_KIND_ZIP,
        size_bytes=1024,
        storage_path="data/uploads/src.zip",
        status=UPLOAD_STATUS_RECEIVED,
    )
    files = [
        await _make_file(session, upload_id=upload.id, name=f"file_{i}.py")
        for i in range(file_count)
    ]
    scan = await ScanRepo(session).create(
        user_id=user.id,
        upload_id=upload.id,
        name="t",
        scan_types=["security"],
        progress_total=file_count,
    )
    return user, files, scan


async def test_bulk_create_inserts_pending_rows(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    _, files, scan = await _scan_with_files(db_session, sample_user_factory)
    repo = ScanFileRepo(db_session)

    rows = await repo.bulk_create(scan_id=scan.id, file_ids=[f.id for f in files])

    assert len(rows) == len(files)
    assert {row.file_id for row in rows} == {f.id for f in files}
    assert all(row.status == SCAN_FILE_STATUS_PENDING for row in rows)
    assert all(row.scan_id == scan.id for row in rows)


async def test_list_for_scan_returns_owner_rows(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user, files, scan = await _scan_with_files(db_session, sample_user_factory)
    repo = ScanFileRepo(db_session)
    await repo.bulk_create(scan_id=scan.id, file_ids=[f.id for f in files])

    rows = await repo.list_for_scan(scan_id=scan.id, user_id=user.id)

    assert len(rows) == len(files)
    assert {row.file_id for row in rows} == {f.id for f in files}


async def test_list_for_scan_hides_rows_from_non_owner(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    _, files, scan = await _scan_with_files(db_session, sample_user_factory)
    intruder = await sample_user_factory()
    repo = ScanFileRepo(db_session)
    await repo.bulk_create(scan_id=scan.id, file_ids=[f.id for f in files])

    rows = await repo.list_for_scan(scan_id=scan.id, user_id=intruder.id)

    assert rows == []


async def test_get_by_id_owner_vs_other(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user, files, scan = await _scan_with_files(db_session, sample_user_factory, file_count=1)
    intruder = await sample_user_factory()
    repo = ScanFileRepo(db_session)
    [row] = await repo.bulk_create(
        scan_id=scan.id,
        file_ids=[files[0].id],
    )

    assert (await repo.get_by_id(row.id, user_id=user.id)) is not None
    assert (await repo.get_by_id(row.id, user_id=intruder.id)) is None
