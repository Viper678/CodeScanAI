from __future__ import annotations

import pytest
from starlette.requests import Request

from app.core.deps import require_csrf_header
from app.core.exceptions import CsrfHeaderInvalid


def _request_with_headers(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/refresh",
            "headers": headers,
        }
    )


async def test_require_csrf_header_accepts_codescan_value() -> None:
    request = _request_with_headers([(b"x-requested-with", b"codescan")])

    await require_csrf_header(request)


async def test_require_csrf_header_rejects_missing_header() -> None:
    request = _request_with_headers([])

    with pytest.raises(CsrfHeaderInvalid):
        await require_csrf_header(request)


async def test_require_csrf_header_rejects_wrong_value() -> None:
    request = _request_with_headers([(b"x-requested-with", b"notcodescan")])

    with pytest.raises(CsrfHeaderInvalid):
        await require_csrf_header(request)
