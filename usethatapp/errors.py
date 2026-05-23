"""Exception hierarchy for the UseThatApp SDK.

Every error raised out of the public API inherits from :class:`UtaError`.
Callers should catch :class:`UtaError` (or a specific subclass) and never
``Exception``/``ValueError``.
"""

from __future__ import annotations


class UtaError(Exception):
    """Base class for every error raised by the UseThatApp SDK."""


class UtaConfigError(UtaError):
    """Raised when SDK configuration is missing or invalid."""


# ── Local validation errors (raised by get_user_from_request / payload parsing) ──

class UtaSignatureError(UtaError):
    """Signature verification failed (local verify or server returned 401)."""


class UtaPayloadExpiredError(UtaError):
    """The launch envelope's ``exp`` is in the past (beyond clock-skew)."""


class UtaAppMismatchError(UtaError):
    """The envelope's ``app_id`` does not match ``UTA_APP_ID``."""


# ── Errors mapped from get_version HTTP responses ──

class UtaBadRequestError(UtaError):
    """Server returned 400 — malformed body, ts outside window, replay, etc."""


class UtaSessionRevokedError(UtaError):
    """Server returned 403 — the user's session was revoked. Log them out."""


class UtaUnknownSessionError(UtaError):
    """Server returned 404 — unknown ``user_key`` or ``app_id``."""


class UtaServerError(UtaError):
    """Server returned 5xx. Callers MAY retry with backoff."""


__all__ = [
    "UtaError",
    "UtaConfigError",
    "UtaSignatureError",
    "UtaPayloadExpiredError",
    "UtaAppMismatchError",
    "UtaBadRequestError",
    "UtaSessionRevokedError",
    "UtaUnknownSessionError",
    "UtaServerError",
]

