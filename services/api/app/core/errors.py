"""Structured errors. No error body ever contains a credential."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status


class AppError(HTTPException):
    code = "error"

    def __init__(self, detail: str, status_code: int, **extra: Any) -> None:
        super().__init__(
            status_code=status_code,
            detail={"code": self.code, "message": detail, **extra},
        )


class NotFound(AppError):
    code = "not_found"

    def __init__(self, what: str = "Resource not found") -> None:
        super().__init__(what, status.HTTP_404_NOT_FOUND)


class Forbidden(AppError):
    code = "forbidden"

    def __init__(self, what: str = "Not permitted") -> None:
        super().__init__(what, status.HTTP_403_FORBIDDEN)


class Unauthorized(AppError):
    code = "unauthorized"

    def __init__(self, what: str = "Authentication required") -> None:
        super().__init__(what, status.HTTP_401_UNAUTHORIZED)


class BadRequest(AppError):
    code = "bad_request"

    def __init__(self, what: str, **extra: Any) -> None:
        super().__init__(what, status.HTTP_400_BAD_REQUEST, **extra)


class ConnectionBlocked(AppError):
    """Inference impossible for a configuration reason.

    Deliberately distinct from a model failure: a blocked connection is NOT a
    failed test and must never be scored as one.
    """

    code = "connection_blocked"

    def __init__(self, what: str, **extra: Any) -> None:
        super().__init__(what, status.HTTP_409_CONFLICT, **extra)
