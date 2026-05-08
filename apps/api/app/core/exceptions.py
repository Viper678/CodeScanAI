from __future__ import annotations


class AppError(Exception):
    """Base class for typed application errors."""

    error_code = "internal_error"
    status_code = 500
    message = "Internal server error"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.message
        super().__init__(self.message)


class EmailAlreadyExists(AppError):
    error_code = "conflict"
    status_code = 409
    message = "Email already exists"


class InvalidCredentials(AppError):
    error_code = "unauthorized"
    status_code = 401
    message = "Invalid credentials"


class InvalidToken(AppError):
    error_code = "unauthorized"
    status_code = 401
    message = "Invalid token"


class CsrfHeaderInvalid(AppError):
    error_code = "forbidden"
    status_code = 403
    message = "Forbidden"


class Unauthorized(AppError):
    error_code = "unauthorized"
    status_code = 401
    message = "Unauthorized"


class NotFound(AppError):
    error_code = "not_found"
    status_code = 404
    message = "Not found"


class PayloadTooLarge(AppError):
    error_code = "payload_too_large"
    status_code = 413
    message = "Payload too large"


class UnsupportedFileType(AppError):
    error_code = "unsupported_media_type"
    status_code = 415
    message = "Unsupported file type"


class UnprocessableArchive(AppError):
    error_code = "unprocessable_archive"
    status_code = 422
    message = "Unprocessable archive"


class InvalidUploadRequest(AppError):
    """Validation error specific to upload composition (e.g. wrong file count)."""

    error_code = "validation_error"
    status_code = 422
    message = "Invalid upload request"


class QueueUnavailable(AppError):
    """Broker (Redis/Celery) is unreachable; the upload was marked failed."""

    error_code = "queue_unavailable"
    status_code = 503
    message = "Queue temporarily unavailable"


class InvalidScanRequest(AppError):
    """Validation error specific to scan composition (e.g. empty scan_types)."""

    error_code = "validation_error"
    status_code = 422
    message = "Invalid scan request"


class ScanFilesForbidden(AppError):
    """Caller supplied file_ids that don't all belong to them + upload_id."""

    error_code = "forbidden"
    status_code = 403
    message = "Some file_ids are not accessible"


class ScanCancelConflict(AppError):
    """Cancel attempted on a scan in a terminal (completed/failed) state."""

    error_code = "conflict"
    status_code = 409
    message = "Cannot cancel scan in current state"


class UnprocessableRerun(AppError):
    """Re-run requested on a scan whose source state can't be reconstructed.

    Surfaced by ``POST /scans/{id}/rerun`` when the source upload was deleted
    (cascade) or the source ``scan_files`` no longer point at any file the
    user can read (e.g. the upload was wiped or a row was orphaned). 422 keeps
    the ``GET /scans/{id}`` ownership check honest (we never reveal whether the
    source id exists for a different user) while still letting the UI surface a
    distinct error from a generic validation failure.
    """

    error_code = "unprocessable_rerun"
    status_code = 422
    message = "Cannot re-run scan"
