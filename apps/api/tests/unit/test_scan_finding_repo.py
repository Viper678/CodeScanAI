from __future__ import annotations

from uuid import UUID

from conftest import SampleUserFactory
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.uuid7 import uuid7
from app.models.file import File
from app.models.scan import Scan
from app.models.scan_finding import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_INFO,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    ScanFinding,
)
from app.models.upload import UPLOAD_KIND_ZIP, UPLOAD_STATUS_RECEIVED
from app.models.user import User
from app.repositories.scan_finding_repo import ScanFindingRepo
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


async def _setup_scan(
    session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> tuple[User, File, Scan]:
    user = await sample_user_factory()
    upload = await UploadRepo(session).create(
        user_id=user.id,
        original_name="src.zip",
        kind=UPLOAD_KIND_ZIP,
        size_bytes=1024,
        storage_path="data/uploads/src.zip",
        status=UPLOAD_STATUS_RECEIVED,
    )
    file = await _make_file(session, upload_id=upload.id, name="a.py")
    scan = await ScanRepo(session).create(
        user_id=user.id,
        upload_id=upload.id,
        name="t",
        scan_types=["security"],
    )
    return user, file, scan


def _make_finding(
    *,
    scan_id: UUID,
    file_id: UUID,
    severity: str,
    scan_type: str = "security",
    title: str = "demo",
) -> ScanFinding:
    return ScanFinding(
        id=uuid7(),
        scan_id=scan_id,
        file_id=file_id,
        scan_type=scan_type,
        severity=severity,
        title=title,
        message="...",
    )


async def test_list_for_scan_returns_inserted_rows(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user, file, scan = await _setup_scan(db_session, sample_user_factory)
    db_session.add(_make_finding(scan_id=scan.id, file_id=file.id, severity=SEVERITY_HIGH))
    await db_session.flush()

    rows = await ScanFindingRepo(db_session).list_for_scan(
        scan_id=scan.id,
        user_id=user.id,
    )

    assert len(rows) == 1
    assert rows[0].severity == SEVERITY_HIGH


async def test_list_for_scan_orders_by_severity(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user, file, scan = await _setup_scan(db_session, sample_user_factory)
    # Insert in deliberately scrambled order.
    scrambled = [SEVERITY_INFO, SEVERITY_CRITICAL, SEVERITY_LOW, SEVERITY_MEDIUM, SEVERITY_HIGH]
    for severity in scrambled:
        db_session.add(
            _make_finding(
                scan_id=scan.id,
                file_id=file.id,
                severity=severity,
                title=severity,
            )
        )
    await db_session.flush()

    rows = await ScanFindingRepo(db_session).list_for_scan(
        scan_id=scan.id,
        user_id=user.id,
    )

    assert [row.severity for row in rows] == [
        SEVERITY_CRITICAL,
        SEVERITY_HIGH,
        SEVERITY_MEDIUM,
        SEVERITY_LOW,
        SEVERITY_INFO,
    ]


async def test_list_for_scan_filters(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user, file, scan = await _setup_scan(db_session, sample_user_factory)
    other_file = await _make_file(db_session, upload_id=file.upload_id, name="b.py")
    db_session.add_all(
        [
            _make_finding(
                scan_id=scan.id,
                file_id=file.id,
                severity=SEVERITY_HIGH,
                scan_type="security",
            ),
            _make_finding(
                scan_id=scan.id,
                file_id=file.id,
                severity=SEVERITY_LOW,
                scan_type="bugs",
            ),
            _make_finding(
                scan_id=scan.id,
                file_id=other_file.id,
                severity=SEVERITY_HIGH,
                scan_type="keywords",
            ),
        ]
    )
    await db_session.flush()

    repo = ScanFindingRepo(db_session)

    high_rows = await repo.list_for_scan(
        scan_id=scan.id,
        user_id=user.id,
        severity=SEVERITY_HIGH,
    )
    assert len(high_rows) == 2
    assert all(row.severity == SEVERITY_HIGH for row in high_rows)

    bugs_rows = await repo.list_for_scan(
        scan_id=scan.id,
        user_id=user.id,
        scan_type="bugs",
    )
    assert len(bugs_rows) == 1
    assert bugs_rows[0].scan_type == "bugs"

    file_rows = await repo.list_for_scan(
        scan_id=scan.id,
        user_id=user.id,
        file_id=other_file.id,
    )
    assert len(file_rows) == 1
    assert file_rows[0].file_id == other_file.id


async def test_list_for_scan_scoped_to_owner(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    _, file, scan = await _setup_scan(db_session, sample_user_factory)
    intruder = await sample_user_factory()
    db_session.add(_make_finding(scan_id=scan.id, file_id=file.id, severity=SEVERITY_HIGH))
    await db_session.flush()

    rows = await ScanFindingRepo(db_session).list_for_scan(
        scan_id=scan.id,
        user_id=intruder.id,
    )

    assert rows == []


async def test_get_by_id_owner_vs_other(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user, file, scan = await _setup_scan(db_session, sample_user_factory)
    intruder = await sample_user_factory()
    finding = _make_finding(scan_id=scan.id, file_id=file.id, severity=SEVERITY_HIGH)
    db_session.add(finding)
    await db_session.flush()

    repo = ScanFindingRepo(db_session)
    assert (await repo.get_by_id(finding.id, user_id=user.id)) is not None
    assert (await repo.get_by_id(finding.id, user_id=intruder.id)) is None
