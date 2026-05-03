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
