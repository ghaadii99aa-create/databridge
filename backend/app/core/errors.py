"""Domain errors raised by services and translated to HTTP responses in one place."""
from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFound(DomainError):
    status_code = 404
    code = "not_found"


class ValidationFailed(DomainError):
    status_code = 422
    code = "validation_failed"


class UnsupportedFile(DomainError):
    status_code = 415
    code = "unsupported_file"


class FileTooLarge(DomainError):
    status_code = 413
    code = "file_too_large"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


class ProviderError(DomainError):
    status_code = 502
    code = "ai_provider_error"


class ReadOnly(DomainError):
    status_code = 403
    code = "read_only"


class LimitExceeded(DomainError):
    status_code = 413
    code = "limit_exceeded"


class RateLimited(DomainError):
    status_code = 429
    code = "rate_limited"
