from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

_BEARER = re.compile(r"(?i)\bBearer\s+\S+")
_CLAWIFI_KEY = re.compile(r"clawifi_(live|test)_\w+")


def redact(text: object) -> str:
    """The text with any bearer token and any clawifi_live_/clawifi_test_ key replaced by ***."""
    return _CLAWIFI_KEY.sub(r"clawifi_\1_***", _BEARER.sub("Bearer ***", str(text)))


class ClawifiError(Exception):
    """Base SDK error. Its message is redacted: a bearer token or a Clawifi key in it becomes ***."""

    def __init__(self, message: object = "", *args: object) -> None:
        super().__init__(redact(message), *args)


class ClawifiTransportError(ClawifiError):
    """Raised when the HTTP transport fails before Clawifi returns an error payload."""


class ClawifiDryRunUnsupportedError(ClawifiError):
    """Raised before sending dry_run to a Clawifi API that would ignore it and run (and bill) the call."""


class ClawifiDryRunIgnoredError(ClawifiError):
    """Raised when a dry run came back without dry_run: true and charged: 0, so the API ran the call (an older node
    during a rolling deploy, say) and may have billed it. response holds what the API returned."""

    def __init__(self, message: str, *, response: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.response = response or {}


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
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        self.details = details or {}
        self.response = response or {}
        self.retry_after = retry_after

    @property
    def limit_scope(self) -> str | None:
        """Which limit a 429 hit (for example per key, per account or per address), from details.limit_scope."""
        scope = self.details.get("limit_scope")
        return str(scope) if scope is not None else None

    @classmethod
    def from_response(
        cls,
        status_code: int,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
        retry_after: float | None = None,
    ) -> "ClawifiAPIError":
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            return cls("Clawifi API request failed", status_code=status_code, request_id=request_id, response=payload, retry_after=retry_after)
        details = error.get("details") if isinstance(error.get("details"), dict) else {}
        error_request_id = error.get("request_id") or details.get("request_id") or request_id
        return cls(
            str(error.get("message") or "Clawifi API request failed"),
            status_code=status_code,
            code=error.get("code"),
            request_id=str(error_request_id) if error_request_id else None,
            details=details,
            response=payload,
            retry_after=retry_after,
        )


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Parse a Retry-After header (delay seconds or an HTTP date) into seconds to wait."""
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - (now or datetime.now(timezone.utc))).total_seconds())
