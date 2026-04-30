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


class Unauthorized(AppError):
    error_code = "unauthorized"
    status_code = 401
    message = "Unauthorized"
