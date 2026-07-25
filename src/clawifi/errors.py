from __future__ import annotations

from typing import Any


class ClawifiError(Exception):
    """Base SDK error."""


class ClawifiTransportError(ClawifiError):
    """Raised when the HTTP transport fails before Clawifi returns an error payload."""


class ClawifiAPIError(ClawifiError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
        details: dict[str, Any] | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        self.details = details or {}
        self.response = response or {}

    @classmethod
    def from_response(cls, status_code: int, payload: dict[str, Any], *, request_id: str | None = None) -> "ClawifiAPIError":
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            return cls("Clawifi API request failed", status_code=status_code, request_id=request_id, response=payload)
        details = error.get("details") if isinstance(error.get("details"), dict) else {}
        error_request_id = error.get("request_id") or details.get("request_id") or request_id
        return cls(
            str(error.get("message") or "Clawifi API request failed"),
            status_code=status_code,
            code=error.get("code"),
            request_id=str(error_request_id) if error_request_id else None,
            details=details,
            response=payload,
        )
